"""Portable character packages: Markdown content, checked references, small run records."""
from datetime import datetime
import hashlib
import os
from pathlib import Path, PureWindowsPath
import random
import re
import shutil
import uuid

from bc_runs import CHECKS
import bc_specs as specs
from bc_store import (BODY_VIEWS, EXPRESSIONS, FACE_VIEWS, SKILL, digest, identifier,
                      image_info, locked, now, read, required_text, write)

SECTIONS = ['角色身份', '固定锚点', '默认外观', '默认风格', '画幅', '随机范围', '生图规则', '视觉参考']
ROLES = {'identity', 'identity_support', 'style', 'pair'}
FORMAT = 'blackcat-character-pack-v2'


def initialize_project(folder):
    root = Path(folder).expanduser().resolve()
    if root == SKILL or SKILL in root.parents:
        raise ValueError('角色项目不能存入技能发布目录。')
    for name in ['视觉资产', '候审图', '定稿图', '过程记录']:
        (root / name).mkdir(parents=True, exist_ok=True)
    return {'project': str(root), 'initialized': True}


def _inside(root, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('参考路径不能为空。')
    relative = Path(value)
    if relative.is_absolute() or PureWindowsPath(value).drive:
        raise ValueError('参考必须使用项目内相对路径。')
    actual = (root / relative).resolve()
    if not actual.is_relative_to(root):
        raise ValueError('参考路径不能逃出角色项目。')
    if not actual.is_file():
        raise ValueError(f'文件缺失：{actual}')
    return actual


def _document(document):
    path = Path(document).expanduser().resolve()
    if path.suffix.lower() != '.md' or not path.is_file():
        raise ValueError('需要已存在的角色生图 MD，直接放在角色项目总目录。')
    raw = path.read_bytes()
    markdown = raw.decode('utf-8-sig')
    if re.search(r'\{\{[\s\S]*?\}\}', markdown):
        raise ValueError('角色 MD 仍含未填写的 {{模板字段}}。')
    parts = re.split(r'^##\s+(.+?)\s*$', markdown, flags=re.M)
    sections = {}
    for heading, body in zip(parts[1::2], parts[2::2]):
        if heading in sections:
            raise ValueError(f'MD 章节重复：{heading}')
        sections[heading] = body.strip()
    if any(not sections.get(key) for key in SECTIONS):
        raise ValueError('MD 必须包含完整且非空的八个固定章节：' + '、'.join(SECTIONS))
    return path, raw, markdown, sections


def _fields(text):
    result = {}
    for line in text.splitlines():
        match = re.match(r'^\s*(?:[-*]\s*)?([^：:]+)[：:]\s*(.*?)\s*$', line)
        if match:
            key, value = match.groups()
            result[key.strip()] = value
    return result


def _manifest_path(document):
    return document.parent / '过程记录' / '角色登记' / (document.stem + '.json')


def _check_document_refs(root, sections, refs):
    links = re.findall(r'\]\((?:<([^>]+)>|([^\)\r\n]+))\)', sections['视觉参考'])
    documented = {_inside(root, a or b).relative_to(root).as_posix() for a, b in links}
    registered = {ref['path'] for ref in refs}
    if documented != registered:
        raise ValueError('MD 视觉参考链接与登记图片清单不一致；请同步后保存。')


def _history(document, data):
    path = _manifest_path(document).parent / document.stem / f'v{data["revision"]:04d}'
    if (not path.with_suffix('.md').is_file() or not path.with_suffix('.json').is_file()
            or digest(path.with_suffix('.md')) != data.get('document_sha256')
            or read(path.with_suffix('.json')) != data):
        raise ValueError('已批准版本快照缺失或与当前登记不一致。')


def _references(root, data, formal=False):
    if not isinstance(data, dict) or not isinstance(data.get('references', []), list):
        raise ValueError('参考清单必须为含 references 数组的对象。')
    refs, seen, coverage = [], set(), set()
    for source in data.get('references', []):
        if not isinstance(source, dict):
            raise ValueError('每项参考必须为对象。')
        required_text(source, ['id', 'path', 'role'])
        identifier(source['id'])
        if source['id'] in seen or source['role'] not in ROLES:
            raise ValueError('参考 ID 重复或 role 不合法。')
        seen.add(source['id'])
        tags = source.get('coverage', [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in tags):
            raise ValueError('coverage 必须为文本标签数组。')
        if source.get('visually_checked') is not True:
            raise ValueError(f'需要实际查看参考图后声明 visually_checked：{source["id"]}')
        actual = _inside(root, source['path'])
        if formal and actual.relative_to(root).parts[0] != '视觉资产':
            raise ValueError('正式参考必须先保存到项目的视觉资产目录。')
        sha = digest(actual)
        if source.get('sha256') and sha != source['sha256']:
            raise ValueError(f'参考内容被修改：{source["id"]}')
        item = {key: source[key] for key in ['id', 'role']}
        item.update(path=actual.relative_to(root).as_posix(), sha256=sha, coverage=tags,
                    visually_checked=True, **image_info(actual))
        refs.append(item)
        if item['role'] in {'identity', 'identity_support'}:
            coverage.update(tags)
    if refs and sum(ref['role'] == 'identity' for ref in refs) != 1:
        raise ValueError('参考必须有且仅有一份 identity 母版；辅助图使用 identity_support。')
    if formal:
        required_text(data, ['id', 'name', 'primary_reference'])
        identifier(data['id'])
        if not any(ref['id'] == data['primary_reference'] and ref['role'] == 'identity' for ref in refs):
            raise ValueError('primary_reference 必须指向已查看的身份母版。')
        required = {f'body:{x}' for x in BODY_VIEWS} | {f'face:{x}' for x in FACE_VIEWS} | {f'expression:{x}' for x in EXPRESSIONS}
        if data.get('anchors_mode') not in {'defined', 'none'}:
            raise ValueError('anchors_mode 必须为 defined 或 none。')
        if data['anchors_mode'] == 'defined':
            required.add('anchor:details')
        if required - coverage:
            raise ValueError('视觉资产覆盖缺项：' + ', '.join(sorted(required - coverage)))
        if not {'style', 'pair'} <= {ref['role'] for ref in refs}:
            raise ValueError('正式包需要默认风格与已认可组合参考；同一图片可分别登记两个用途。')
    return refs


def save(document, refs_data, approval, update=False):
    required_text({'approval': approval}, ['approval'])
    path, raw, _, sections = _document(document)
    root = path.parent
    initialize_project(root)
    with locked(root):
        current = _manifest_path(path)
        previous = read(current) if current.exists() else None
        if bool(previous) != bool(update):
            raise ValueError('已登记需要 update；未登记不能 update。')
        if previous and (previous.get('format') != FORMAT or previous['id'] != refs_data['id']):
            raise ValueError('登记格式或角色 ID 不匹配。')
        if previous:
            _history(path, previous)
            _references(root, previous, formal=True)
        refs = _references(root, refs_data, formal=True)
        _check_document_refs(root, sections, refs)
        revision = previous['revision'] + 1 if previous else 1
        history = current.parent / path.stem / f'v{revision:04d}'
        if history.with_suffix('.md').exists() or history.with_suffix('.json').exists():
            raise ValueError('版本快照已存在，不覆盖；请检查未完成的上次保存。')
        data = {key: refs_data[key] for key in ['id', 'name', 'anchors_mode', 'primary_reference']}
        data.update(format=FORMAT, revision=revision, document=path.name,
                    document_sha256=hashlib.sha256(raw).hexdigest(), references=refs,
                    approval=approval, approved_at=now(), approval_status='可用')
        history.parent.mkdir(parents=True, exist_ok=True)
        with history.with_suffix('.md').open('xb') as handle:
            handle.write(raw)
        write(history.with_suffix('.json'), data)
        write(current, data)
    return {'id': data['id'], 'revision': revision, 'document': str(path), 'manifest': str(current)}


def load(document):
    path, raw, markdown, sections = _document(document)
    current = _manifest_path(path)
    if not current.is_file():
        raise ValueError('角色尚未正式登记；建档候选请使用 candidate 模式。')
    data = read(current)
    if data.get('format') != FORMAT or data.get('document') != path.name or data.get('approval_status') != '可用':
        raise ValueError('角色登记格式、MD 文件名或批准状态不匹配。')
    if data.get('document_sha256') != hashlib.sha256(raw).hexdigest():
        raise ValueError('MD 已修改；请核对并明确 update 后使用，避免静默改变角色。')
    _history(path, data)
    if any(not re.fullmatch(r'[a-f0-9]{64}', ref.get('sha256', '')) for ref in data.get('references', [])):
        raise ValueError('参考登记缺少有效 SHA256。')
    refs = _references(path.parent, data, formal=True)
    _check_document_refs(path.parent, sections, refs)
    for ref in refs:
        ref['actual_path'] = str(path.parent / ref['path'])
    return {'document': str(path), 'markdown': markdown, 'sections': sections, 'manifest': data, 'references': refs}


def check(document):
    bundle = load(document)
    return {'status': 'PASS', 'document': bundle['document'], 'id': bundle['manifest']['id'],
            'revision': bundle['manifest']['revision'], 'references': len(bundle['references']),
            'note': '文件、哈希与覆盖声明通过；此命令不替代实际视觉审核。'}


def prepare(document, request='', mode='production', extra_refs=None, style_override=None,
            outfit_override=None, aspect=None, size=None, references=None, asset_type=None, image_specs=None):
    if mode not in {'production', 'candidate'}:
        raise ValueError('mode 必须为 production 或 candidate。')
    path, raw, markdown, sections = _document(document)
    if image_specs is not None:
        image_specs = specs.selection(image_specs, 'single')
        chosen = specs.resolve(image_specs)
        if aspect or size:
            raise ValueError('使用规格卡时不再混用旧 --aspect/--size；在规格卡内修改。')
        aspect, size = chosen['aspect'], 'native' if chosen['pixels'] == 'native' else 'x'.join(map(str, chosen['pixels']))
    root = path.parent
    if mode == 'production':
        bundle = load(path)
        data, refs = bundle['manifest'], bundle['references']
    else:
        data = read(references) if isinstance(references, (str, Path)) else (references or {})
        refs = _references(root, data)
        asset_type = asset_type or data.get('asset_type')
        if not refs and asset_type != 'master':
            raise ValueError('仅首张母版 asset_type=master 可不带参考；其它资产必须传入身份参考。')
        if refs and not any(ref['role'] == 'identity' for ref in refs):
            raise ValueError('候选资产必须包含身份参考。')
        for ref in refs:
            ref['actual_path'] = str(root / ref['path'])
    rendered = render(sections, data, refs, request, extra_refs, style_override,
                      outfit_override, aspect, size)
    unique = rendered['inputs']
    initialize_project(root)
    run_id = datetime.now().strftime('%H%M%S') + '-' + uuid.uuid4().hex[:12]
    folder = root / '候审图' / datetime.now().strftime('%Y-%m-%d') / run_id
    folder.mkdir(parents=True, exist_ok=False)
    for item in unique:
        item['path'] = Path(os.path.relpath(root / item['project_path'], folder)).as_posix()
    (folder / 'prompt.txt').write_text(rendered['prompt'], encoding='utf-8')
    (folder / 'document-snapshot.md').write_bytes(raw)
    write(folder / 'inputs.json', unique)
    record = {'schema_version': 2, 'run_id': run_id, 'mode': mode, 'asset_type': asset_type,
              'created': now(), 'project_root': Path(os.path.relpath(root, folder)).as_posix(),
              'document': path.name, 'document_sha256': hashlib.sha256(raw).hexdigest(),
              'character_id': data.get('id'), 'character_revision': data.get('revision'),
              'request': rendered['request'], 'random_choices': rendered['random_choices'],
              'overrides': {'style': style_override, 'outfit': outfit_override},
              'prompt_file': 'prompt.txt', 'inputs': unique, 'tool': None,
              'input_delivery_verified': False, 'original': None,
              'checks': {key: {'status': '无法判断', 'note': '尚未检查'} for key in CHECKS},
              'approval_status': '待审核'}
    if image_specs is not None:
        chosen = specs.attach(record, image_specs)
        (folder / 'prompt.txt').write_text(specs.prompt_for(rendered['prompt'], chosen), encoding='utf-8')
    write(folder / 'run.json', record)
    return {'run': str(folder), 'prompt_file': str(folder / 'prompt.txt'), 'request': rendered['request'],
            'random_choices': rendered['random_choices'],
            'inputs': [{**item, 'path': str(root / item['project_path'])} for item in unique]}


def render(sections, data, refs, request='', extra_refs=None, style_override=None,
           outfit_override=None, aspect=None, size=None, coverage=None):
    """Shared pure prompt/reference selection; batch code supplies frozen bundles."""
    primary = data.get('primary_reference') or next((ref['id'] for ref in refs if ref['role'] == 'identity'), None)
    if refs and not any(ref['id'] == primary and ref['role'] == 'identity' for ref in refs):
        raise ValueError('primary_reference 未对应有效身份参考。')
    requested = set(extra_refs or [])
    for tag in coverage or []:
        matches = [ref for ref in refs if ref['role'].startswith('identity') and tag in ref.get('coverage', [])]
        if not matches:
            raise ValueError('必要参考覆盖缺失：' + tag)
        # Prefer an already selected image, then the most focused supporting image.
        choice = min(matches, key=lambda ref: (ref['id'] not in requested and ref['id'] != primary, len(ref.get('coverage', []))))
        requested.add(choice['id'])
    if requested - {ref['id'] for ref in refs}:
        raise ValueError('指定的辅助参考 ID 不存在。')
    inputs = [ref for ref in refs if ref['id'] == primary or ref['id'] in requested or ref['role'] in {'style', 'pair'}]
    if style_override:
        inputs = [ref for ref in inputs if ref['role'] not in {'style', 'pair'}]
    actual_random = {}
    if not request.strip():
        choices = _fields(sections['随机范围'])
        for key in ['场景', '动作', '时间', '构图']:
            options = [x.strip() for x in choices.get(key, '').split('｜') if x.strip()]
            if not options:
                raise ValueError(f'随机范围缺少非空字段：{key}')
            actual_random[key] = random.choice(options)
        request = '；'.join(f'{key}：{value}' for key, value in actual_random.items())
    appearance = sections['默认外观']
    if outfit_override:
        appearance = re.sub(r'^\s*(?:[-*]\s*)?服装\s*[：:].*$', '', appearance, flags=re.M).strip()
        appearance += '\n服装：' + outfit_override
    frame = _fields(sections['画幅'])
    aspect, size = aspect or frame.get('比例'), size or frame.get('尺寸')
    if not aspect or not size:
        raise ValueError('画幅章节必须填写比例和尺寸，或在本次调用传入。')
    general = _fields(sections['默认风格']).get('通用限制', '') if style_override else ''
    prompt_parts = ['生成一张图片。', '角色身份：\n' + sections['角色身份'],
                    '固定锚点：\n' + sections['固定锚点'], '本次外观：\n' + appearance,
                    '本次风格：\n' + (style_override or sections['默认风格']),
                    '通用限制：' + general if general else '',
                    '保持同一角色身份；服装或画风变化不能改换人物。',
                    '画面约束：' + _fields(sections['生图规则']).get('画面约束', '保持本次明确要求，不添加图板、标签或无关文字。'),
                    f'画幅：{aspect}；尺寸：{size}',
                    '本次画面要求：\n' + request]
    unique, by_hash = [], {}
    for ref in inputs:
        use = {'role': ref['role'], 'allowed': '身份形状与锚点' if ref['role'].startswith('identity') else '本次默认画风及组合表现',
               'forbidden': '不照搬图板布局、文字、示例场景或示例服装；本次外观要求优先；换画风时身份参考只控制身份'}
        if ref['sha256'] in by_hash:
            by_hash[ref['sha256']]['uses'].append(use)
        else:
            item = {'number': len(unique) + 1, 'id': ref['id'], 'project_path': ref['path'],
                    'sha256': ref['sha256'], 'uses': [use]}
            unique.append(item)
            by_hash[ref['sha256']] = item
    for item in unique:
        prompt_parts.append(f'参考图 {item["number"]} 用途：' + '；'.join(use['role'] + '，' + use['allowed'] + '，' + use['forbidden'] for use in item['uses']))
    return {'prompt': '\n'.join(prompt_parts), 'request': request,
            'random_choices': actual_random, 'inputs': unique, 'aspect': aspect, 'size': size}


def archive(folder, label=None):
    folder = Path(folder).resolve()
    initial = read(folder / 'run.json')
    root = (folder / initial.get('project_root', '.')).resolve()
    if initial.get('schema_version') != 2 or folder.parent.parent != root / '候审图':
        raise ValueError('此命令仅归档角色项目候审图目录中的 v2 run。')
    label = label or initial.get('character_id') or 'character'
    if (not isinstance(label, str) or not re.fullmatch(r'[^<>:"/\\|?*\x00-\x1f]+', label)
            or label.endswith(('.', ' '))):
        raise ValueError('归档名称不是合法文件名。')
    with locked(root), locked(folder):
        data = read(folder / 'run.json')
        if data.get('approval_status') != '可用' or not data.get('approval_history'):
            raise ValueError('先记录用户明确审核通过，再归档定稿。')
        if specs.acceptance_needed(data) and not data.get('spec_acceptance'):
            raise ValueError('规格有偏差或未验证，需用户明确接受后归档。')
        original = data.get('original')
        if not original:
            raise ValueError('本轮没有已记录图片。')
        source = _inside(folder, original['path'])
        if digest(source) != original['sha256']:
            raise ValueError('原图内容被修改，拒绝归档。')
        if data.get('archive'):
            target = _inside(root, data['archive']['path'])
            if digest(target) != data['archive']['sha256']:
                raise ValueError('定稿文件被修改。')
            return {'path': str(target), 'sha256': digest(target), 'already_archived': True}
        target_folder = root / '定稿图'
        target_folder.mkdir(exist_ok=True)
        numbers = [int(match.group(1)) for file in target_folder.rglob('*') if file.is_file()
                   and file.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}
                   and (match := re.match(r'^(\d+)-', file.name))]
        target = target_folder / f'{max(numbers, default=0) + 1:03d}-{label}{source.suffix.lower()}'
        with target.open('xb') as outgoing, source.open('rb') as incoming:
            shutil.copyfileobj(incoming, outgoing)
        if digest(target) != original['sha256']:
            raise ValueError('定稿复制哈希校验失败。')
        data['archive'] = {'path': target.relative_to(root).as_posix(), 'sha256': original['sha256'], 'at': now()}
        write(folder / 'run.json', data)
    return {'path': str(target), 'sha256': original['sha256'], 'already_archived': False}
