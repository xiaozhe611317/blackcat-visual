"""Prepare exact input manifests and archive non-overwriting generation records."""
from datetime import datetime
from functools import wraps
import json
from pathlib import Path
import shutil
import uuid
import bc_specs as specs

from bc_store import digest, image_info, locked, now, read, required_text, select, write

CHECKS = ['identity', 'anchors', 'style', 'anatomy', 'request', 'textures']

def run_locked(function):
    @wraps(function)
    def guarded(folder, *args, **kwargs):
        with locked(Path(folder).resolve()):
            return function(folder, *args, **kwargs)
    return guarded

def prepare(root, character, style, request, mode='production', extra_refs=None, aspect=None, size=None):
    if not request.strip():
        raise ValueError('需要本次画面要求。')
    bundle = select(root, character, style, mode)
    c, s, pair = bundle['character'], bundle['style'], bundle['pair']
    inputs = [c['references'][0]]
    for ref_id in extra_refs or []:
        matches = [ref for ref in c['references'] if ref['id'] == ref_id]
        if not matches:
            raise ValueError(f'主角辅助参考不存在：{ref_id}')
        inputs.extend(matches)
    inputs += s['references']
    if pair:
        inputs += pair['references']
    unique = []
    by_hash = {}
    for ref in inputs:
        if ref['sha256'] in by_hash:
            previous = by_hash[ref['sha256']]
            previous['uses'].append({'role': ref['role'], 'allowed': ref['allowed'], 'forbidden': ref['forbidden']})
            continue
        entry = {'number': len(unique) + 1, 'id': ref['id'], 'path': ref['actual_path'], 'sha256': ref['sha256'], 'uses': [{'role': ref['role'], 'allowed': ref['allowed'], 'forbidden': ref['forbidden']}]}
        unique.append(entry)
        by_hash[ref['sha256']] = entry
    sections = [
        '生成一张图片。' if mode != 'edit' else '编辑指定目标图，仅改变本次明确要求的部分。',
        '人物身份（画风变化不能引入其他人的身份）：',
        *[f'{key}: {c[key]}' for key in ['name', 'age_impression', 'face_structure', 'hair', 'body_proportions', 'identity_constraints', 'allowed_changes']],
        '视觉锚点：' + json.dumps(c['anchors'], ensure_ascii=False),
        '当前风格（以下为本次完整风格，不沿用之前风格的限制）：',
        *[f'{key}: {s[key]}' for key in ['name', 'type', 'realism', 'linework', 'coloring', 'lighting', 'palette', 'materials', 'detail_density', 'preserve_textures', 'avoid']],
        '允许依据当前媒介调整表现方式，保持人物辨识特征；不要把风格图的人脸、服装、姿势或场景复制过来。',
        '画幅目标：' + (aspect or s['default_aspect']),
        '尺寸目标：' + (size or s['default_size']),
        '本次画面要求：\n' + request,
    ]
    if pair:
        sections.append('已批准组合适配：' + pair['adaptation_notes'])
    sections.append('参考图编号与用途：')
    for item in unique:
        sections.append(f'图 {item["number"]}：' + json.dumps(item['uses'], ensure_ascii=False))
    sections.append('不把设定图的多视图布局、白底、示例服装带入场景作品；被合理遮挡的锚点无需强行露出。')
    prompt = '\n'.join(sections)
    stamp = datetime.now().strftime('%Y-%m-%d')
    run_id = datetime.now().strftime('%H%M%S') + '-' + uuid.uuid4().hex[:12]
    folder = Path(bundle['output_root']) / stamp / run_id
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'prompt.txt').write_text(prompt, encoding='utf-8')
    write(folder / 'inputs.json', unique)
    write(folder / 'profiles-snapshot.json', bundle)
    data = {'schema_version': 1, 'run_id': run_id, 'mode': mode, 'created': now(), 'character_id': c['id'], 'character_revision': c['revision'], 'style_id': s['id'], 'style_revision': s['revision'], 'pair_revision': pair['revision'] if pair else None, 'request': request, 'prompt_file': 'prompt.txt', 'inputs': unique, 'tool': None, 'input_delivery_verified': False, 'original': None, 'checks': {key: {'status': '无法判断', 'note': '尚未检查'} for key in CHECKS}, 'approval_status': '待审核'}
    write(folder / 'run.json', data)
    return {'run': str(folder), 'prompt_file': str(folder / 'prompt.txt'), 'inputs': unique}

@run_locked
def add_edit_target(folder, target):
    folder = Path(folder).resolve()
    data = read(folder / 'run.json')
    if data['original']:
        raise ValueError('生成后不能修改实际输入记录。')
    if data.get('image_specs', {}).get('plan'):
        raise ValueError('规格参数计划已冻结；编辑目标应在适配前加入。')
    if any(use['role'] == 'edit_target' for item in data['inputs'] for use in item['uses']):
        raise ValueError('本轮已有唯一编辑目标；更换目标请创建新一轮。')
    target = Path(target).resolve()
    image_info(target)
    target_path = str(target)
    if data.get('schema_version') == 2:
        snapshot = folder / ('edit-target' + target.suffix.lower())
        with snapshot.open('xb') as outgoing, target.open('rb') as incoming:
            shutil.copyfileobj(incoming, outgoing)
        if digest(snapshot) != digest(target):
            raise ValueError('编辑目标复制校验失败。')
        target_path = snapshot.name
    entry = {'number': len(data['inputs']) + 1, 'id': 'edit-target', 'path': target_path, 'sha256': digest(target), 'uses': [{'role': 'edit_target', 'allowed': data['request'], 'forbidden': '保持其余身份、风格和未指定内容不变'}]}
    data['inputs'].append(entry)
    data['mode'] = 'edit'
    prompt_path = folder / 'prompt.txt'
    prompt = prompt_path.read_text(encoding='utf-8')
    prompt = prompt.replace('生成一张图片。', '编辑目标图，仅改变本次明确要求的部分。', 1)
    prompt += f'\n图 {entry["number"]} 是唯一编辑目标，其余图片仅作指定用途的参考。'
    prompt_path.write_text(prompt, encoding='utf-8')
    write(folder / 'inputs.json', data['inputs'])
    write(folder / 'run.json', data)
    actual_inputs = [{**item, 'path': str((folder / item['path']).resolve())} for item in data['inputs']]
    return {'run': str(folder), 'inputs': actual_inputs, 'prompt_file': str(prompt_path)}

@run_locked
def record(folder, source, metadata):
    folder = Path(folder).resolve()
    data = read(folder / 'run.json')
    if data.get('original'):
        raise ValueError('本轮已有原图，不能覆盖；重试请创建新一轮。')
    for key in ['tool', 'actual_submitted_prompt', 'reference_delivery', 'visible_parameters', 'request_count', 'success_count']:
        if key not in metadata:
            raise ValueError(f'记录缺少 {key}；未暴露的参数写“未暴露”，不能猜测。')
    required_text(metadata, ['tool', 'actual_submitted_prompt'])
    if not isinstance(metadata['reference_delivery'], dict) or not isinstance(metadata['reference_delivery'].get('verified'), bool):
        raise ValueError('reference_delivery.verified 必须明确为 true 或 false。')
    required_text(metadata['reference_delivery'], ['evidence'])
    counts = [metadata['request_count'], metadata['success_count']]
    if any(type(count) is not int or count < 0 for count in counts) or counts[1] > counts[0]:
        raise ValueError('调用次数和成功次数必须为非负整数，成功次数不能大于调用次数。')
    if data.get('image_specs'):
        if counts != [1, 1]:
            raise ValueError('新规格流程每轮一次调用一张图；不能把预览/精修或重试合并为一轮。')
        if data['inputs'] and metadata['reference_delivery']['verified'] is not True:
            raise ValueError('固定角色需真实参考传递证据。')
    source = Path(source).resolve()
    info = image_info(source)
    verification = specs.verify_output(folder, data, source, metadata)
    destination = folder / ('original' + source.suffix.lower())
    with destination.open('xb') as handle, source.open('rb') as incoming:
        shutil.copyfileobj(incoming, handle)
    sha = digest(source)
    if sha != digest(destination):
        raise ValueError('原图归档校验失败。')
    data.update(original={'path': destination.name, 'source_path': str(source), 'sha256': sha, **info}, tool=metadata['tool'], generation=metadata, input_delivery_verified=metadata['reference_delivery'].get('verified') is True)
    data['spec_verification'] = verification
    write(folder / 'run.json', data)
    result = {'run': str(folder), 'original': str(destination)}
    if data.get('schema_version') != 1:
        result['spec_verification'] = verification
    return result

@run_locked
def review(folder, checks=None, status=None, approval=None, accept_issues=False):
    folder = Path(folder)
    data = read(folder / 'run.json')
    if checks is None and status is None:
        return {'run': str(folder), 'approval_status': data['approval_status'], 'checks': data['checks']}
    original = data.get('original')
    if not original:
        raise ValueError('本轮尚未归档原图，不能保存视觉检查或审核决定。')
    original_path = folder / original['path']
    if not original_path.is_file() or digest(original_path) != original['sha256']:
        raise ValueError('归档原图缺失或内容被修改，不能继续审核。')
    if checks is not None:
        if not isinstance(checks, dict) or set(checks) != set(CHECKS):
            raise ValueError('需要 identity、anchors、style、anatomy、request、textures 六项检查。')
        for item in checks.values():
            if not isinstance(item, dict) or item.get('status') not in ['通过', '待修', '无法判断']:
                raise ValueError('每项检查需要合法状态及实际观察记录。不可见内容写无法判断并解释。')
            required_text(item, ['note'])
        data['checks'] = checks
        data.setdefault('check_history', []).append({'at': now(), 'checks': checks})
    if status is not None:
        if status not in ['待审核', '可用', '待修', '弃用']:
            raise ValueError('审核状态不合法。')
        required_text({'approval': approval}, ['approval'])
        if status == '可用' and specs.acceptance_needed(data):
            if not accept_issues:
                raise ValueError('规格有偏差/未验证；请展示后记录明确接受，并加 accept_issues。')
            data['spec_acceptance'] = {'at': now(), 'statement': approval,
                                       'verification_sha256': specs.fingerprint(data['spec_verification'])}
        data['approval_status'] = status
        data.setdefault('approval_history', []).append({'at': now(), 'status': status, 'statement': approval})
    write(folder / 'run.json', data)
    return {'run': str(folder), 'approval_status': data['approval_status'], 'checks': data['checks']}
