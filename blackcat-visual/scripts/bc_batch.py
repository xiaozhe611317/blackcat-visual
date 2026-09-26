"""Tool-neutral, restartable image tasks. This module never calls an image service."""
from collections import Counter
from copy import deepcopy
import html
import os
from pathlib import Path
import re
import shutil

import bc_pack as pack
import bc_runs as runs
import bc_specs as specs
from bc_store import SKILL, digest, identifier, image_info, locked, now, read, required_text, write

FORMAT = 'blackcat-batch-v3'
OVERRIDES = {'style_override', 'outfit_override', 'aspect', 'size'}
CAST_FIELDS = {'character', 'position', 'action', 'visibility', 'required_anchors',
               'reference_ids', 'coverage', 'outfit_override'}


def _text_file(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)


def _copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with Path(source).open('rb') as incoming, target.open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing)
    if digest(source) != digest(target):
        raise ValueError('复制校验失败：' + str(target))


def _source(base, value):
    # User-specified input paths may be absolute. Stored batch paths may not.
    return (base / value).resolve()


def _verified(root, ref):
    path = pack._inside(root, ref['path'])
    if digest(path) != ref['sha256']:
        raise ValueError('冻结文件被修改：' + ref['path'])
    return path


def _freeze(root, source, relative):
    target = root / relative
    _copy(source, target)
    return {'path': target.relative_to(root).as_posix(), 'sha256': digest(target)}


def scene_check(file):
    """Scene JSON is the single scene-content source; image paths are relative to it."""
    path = Path(file).resolve()
    scene = read(path)
    required_text(scene, ['id', 'name', 'location', 'layout', 'lighting', 'continuity'])
    identifier(scene['id'])
    if type(scene.get('revision')) is not int or scene['revision'] < 1:
        raise ValueError('场景 revision 必须为正整数。')
    if not isinstance(scene.get('key_objects'), list) or any(not isinstance(x, str) or not x.strip() for x in scene['key_objects']):
        raise ValueError('场景 key_objects 必须为文字数组。')
    refs, ids = [], set()
    for ref in scene.get('references', []):
        required_text(ref, ['id', 'path', 'allowed', 'forbidden'])
        identifier(ref['id'])
        if ref['id'] in ids or ref.get('visually_checked') is not True:
            raise ValueError('场景参考 ID 重复或尚未实际查看。')
        ids.add(ref['id'])
        actual = pack._inside(path.parent, ref['path'])
        sha = digest(actual)
        if ref.get('sha256', sha) != sha:
            raise ValueError('场景参考哈希不符。')
        refs.append({**ref, 'sha256': sha, 'actual_path': str(actual), **image_info(actual)})
    return {'scene': scene, 'references': refs, 'document_sha256': digest(path)}


def catalog(documents, folder):
    """Explicit documents only; no disk-wide search and no asset promotion."""
    root = Path(folder).resolve()
    if root.exists():
        raise ValueError('总览输出目录已存在；请用新目录以免覆盖。')
    root.mkdir(parents=True)
    entries = []
    for number, document in enumerate(documents, 1):
        path = Path(document).resolve()
        entry = {'document': str(path), 'name': path.stem, 'readiness': '缺项', 'thumbnail': None}
        try:
            bundle = pack.load(path)
            ref = next(x for x in bundle['references'] if x['role'] == 'identity')
            from PIL import Image
            with Image.open(ref['actual_path']) as image:
                image.thumbnail((192, 192))
                name = f'{number:03d}.png'
                image.convert('RGB').save(root / name)
            entry.update(id=bundle['manifest']['id'], name=bundle['manifest']['name'],
                         revision=bundle['manifest']['revision'], readiness='可用', thumbnail=name)
        except (ValueError, OSError, KeyError) as error:
            entry['reason'] = str(error)
        entries.append(entry)
    write(root / 'catalog.json', entries)
    cards = []
    for item in entries:
        picture = f'<img src="{item["thumbnail"]}" alt="母版缩略图">' if item['thumbnail'] else ''
        cards.append(f'<article>{picture}<h2>{html.escape(item["name"])}</h2>'
                     f'<p>{html.escape(item["readiness"])} · {html.escape(item.get("id", ""))}</p>'
                     f'<p>{html.escape(item.get("reason", "已登记；文件校验不等于本次视觉审核"))}</p>'
                     f'<a href="{html.escape(Path(item["document"]).as_uri(), quote=True)}">角色文档</a></article>')
    _text_file(root / 'index.html', '<!doctype html><meta charset="utf-8"><title>角色总览</title>'
               '<style>body{font:16px system-ui;max-width:1100px;margin:32px auto;background:#faf8f3}'
               'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px}'
               'article{padding:20px;background:white;border:1px solid #ddd}img{max-width:192px}</style>'
               '<h1>固定角色总览</h1><main>' + ''.join(cards) + '</main>')
    return {'folder': str(root), 'overview': str(root / 'index.html'), 'characters': entries}


def _validate_plan(plan):
    identifier(plan['id'])
    characters, items = plan.get('characters'), plan.get('items')
    if not isinstance(characters, list) or not characters or not isinstance(items, list) or not items:
        raise ValueError('批次需要 characters 和 items 非空数组。')
    char_ids, item_ids = set(), set()
    common = plan.get('common', {})
    if not isinstance(common, dict) or set(common) - (OVERRIDES | {'request'}):
        raise ValueError('common 仅支持 request、style_override、outfit_override、aspect、size。')
    for entry in characters:
        identifier(entry['id']); required_text(entry, ['document'])
        if entry['id'] in char_ids or entry.get('mode', 'production') not in {'production', 'candidate'}:
            raise ValueError('角色 ID 重复或 mode 非法。')
        char_ids.add(entry['id'])
    for key, value in common.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError('共用要求必须为非空文字：' + key)
    for item in items:
        identifier(item['id'])
        if item['id'] in item_ids:
            raise ValueError('任务 ID 重复。')
        item_ids.add(item['id'])
        cast = item.get('cast')
        if not isinstance(cast, list) or not cast:
            raise ValueError('每张图需要非空 cast。')
        if any(not isinstance(x, dict) for x in cast):
            raise ValueError('cast 成员必须是对象。')
        ids = [x.get('character') for x in cast]
        if len(set(ids)) != len(ids) or set(ids) - char_ids:
            raise ValueError('同框角色重复或未在 characters 中声明。')
        for member in cast:
            if not isinstance(member, dict):
                raise ValueError('cast 成员必须是对象。')
            if set(member) - CAST_FIELDS:
                raise ValueError('cast 含未知字段；画风属于整张图，不能逐角色设置。')
            for key in ['required_anchors', 'reference_ids', 'coverage']:
                if not isinstance(member.get(key, []), list) or any(not isinstance(x, str) or not x.strip() for x in member.get(key, [])):
                    raise ValueError(key + ' 必须为文字数组。')
            if len(cast) > 1:
                required_text(member, ['position', 'action', 'visibility'])
        if len(cast) > 1:
            required_text(item.get('shot', {}), ['camera', 'framing'])
        for key in OVERRIDES | {'request'}:
            if key in item and (not isinstance(item[key], str) or not item[key].strip()):
                raise ValueError('逐图要求必须为非空文字：' + key)
        if item.get('master_from'):
            if len(cast) != 1 or item.get('asset_type') not in {'body', 'face', 'expressions', 'anchors', 'style'}:
                raise ValueError('master_from 仅用于单角色派生资产。')
            item['depends_on'] = list(dict.fromkeys(item.get('depends_on', []) + [item['master_from']]))
    by_id = {x['id']: x for x in items}
    for item in items:
        deps = item.get('depends_on', [])
        if not isinstance(deps, list) or set(deps) - item_ids or item['id'] in deps:
            raise ValueError('依赖必须指向本批次其它任务。')
        if item.get('master_from'):
            parent = by_id[item['master_from']]
            if parent.get('asset_type') != 'master' or [m['character'] for m in parent['cast']] != [m['character'] for m in item['cast']]:
                raise ValueError('派生图只能使用同角色的母版任务。')
    def visit(key, trail):
        if key in trail:
            raise ValueError('任务依赖成环。')
        for dependency in by_id[key].get('depends_on', []):
            visit(dependency, trail | {key})
    for key in item_ids:
        visit(key, set())
    if 'image_specs' in plan:
        specs.selection(plan['image_specs'], 'batch', item_ids)
        if any(key in common for key in ['aspect', 'size']) or any(any(key in item for key in ['aspect', 'size']) for item in items):
            raise ValueError('使用 image_specs 时不要混用旧 aspect/size 字段；规格放共用卡与逐图例外。')


def initialize(plan_file, folder):
    plan_file, root = Path(plan_file).resolve(), Path(folder).resolve()
    if root.exists() or root == SKILL or SKILL in root.parents:
        raise ValueError('批次目录必须是技能外的新目录；已有批次使用 status/prepare 继续。')
    plan = deepcopy(read(plan_file))
    _validate_plan(plan)
    root.mkdir(parents=True)
    data = {'format': FORMAT, 'id': plan['id'], 'created': now(), 'characters': {}, 'items': {},
            'scene': None, 'policy': {'tool': 'environment-default', 'automatic_retries': 0,
                                    'on_error': 'continue-independent', 'default_concurrency': 1}}
    for source in plan['characters']:
        key = source['id']
        try:
            document = _source(plan_file.parent, source['document'])
            if source.get('mode', 'production') == 'production':
                bundle = pack.load(document)
                if bundle['manifest']['id'] != key:
                    raise ValueError('计划角色 ID 与正式登记不符。')
            else:
                path, _, markdown, sections = pack._document(document)
                manifest = read(_source(plan_file.parent, source['references'])) if source.get('references') else {'id': key, 'references': []}
                if manifest.get('id', key) != key:
                    raise ValueError('候选参考属于其它角色。')
                refs = pack._references(path.parent, manifest)
                for ref in refs:
                    ref['actual_path'] = str(path.parent / ref['path'])
                bundle = {'markdown': markdown, 'sections': sections, 'manifest': manifest, 'references': refs}
            snapshot = _freeze(root, document, f'snapshots/characters/{key}/character.md')
            refs = []
            for number, ref in enumerate(bundle['references'], 1):
                target = f'snapshots/characters/{key}/{number:02d}{Path(ref["actual_path"]).suffix.lower()}'
                frozen = _freeze(root, ref['actual_path'], target)
                refs.append({**{k: v for k, v in ref.items() if k not in {'actual_path', 'path'}}, **frozen})
            data['characters'][key] = {'mode': source.get('mode', 'production'), 'document': snapshot,
                                       'manifest': bundle['manifest'], 'references': refs}
        except (ValueError, OSError, KeyError) as error:
            data['characters'][key] = {'error': str(error)}
    if plan.get('scene'):
        try:
            scene_file = _source(plan_file.parent, plan['scene'])
            checked = scene_check(scene_file)
            frozen = _freeze(root, scene_file, 'snapshots/scene/scene.json')
            refs = []
            for number, ref in enumerate(checked['references'], 1):
                frozen_ref = _freeze(root, ref['actual_path'], f'snapshots/scene/{number:02d}{Path(ref["actual_path"]).suffix.lower()}')
                refs.append({**{k: v for k, v in ref.items() if k not in {'actual_path', 'path'}}, **frozen_ref})
            data['scene'] = {'document': frozen, 'references': refs}
        except (ValueError, OSError, KeyError) as error:
            data['scene'] = {'error': str(error)}
    # Freeze random choices now, so a retry never silently changes the requested scene.
    for item in plan['items']:
        request = '\n'.join(x for x in [plan.get('common', {}).get('request', ''), item.get('request', '')] if x)
        item['resolved_request'] = request
        if not request and not item.get('shot') and not plan.get('scene') and len(item['cast']) == 1:
            char = data['characters'][item['cast'][0]['character']]
            if 'error' not in char:
                _, _, _, sections = pack._document(_verified(root, char['document']))
                rendered = pack.render(sections, {}, [], '')
                item['resolved_request'], item['random_choices'] = rendered['request'], rendered['random_choices']
        data['items'][item['id']] = {'state': 'queued', 'attempts': [], 'events': []}
    write(root / 'plan.json', plan)
    data['plan_sha256'] = digest(root / 'plan.json')
    write(root / 'batch.json', data)
    return status(root)


def _load(root):
    root = Path(root).resolve()
    data = read(root / 'batch.json')
    if data.get('format') != FORMAT or digest(root / 'plan.json') != data.get('plan_sha256'):
        raise ValueError('批次格式或冻结计划哈希不符；变更要求请建新批次。')
    return root, data, read(root / 'plan.json')


def _item(plan, key):
    matches = [x for x in plan['items'] if x['id'] == key]
    if not matches:
        raise ValueError('任务 ID 不存在：' + key)
    return matches[0]


def _run(root, state, number=None):
    attempts = state['attempts']
    index = len(attempts) if number is None else number
    if type(index) is not int or not 1 <= index <= len(attempts):
        raise ValueError('任务轮次不存在。')
    folder = pack._inside(root, attempts[index - 1]['path'] + '/run.json').parent
    run = read(folder / 'run.json')
    if digest(folder / 'prompt.txt') != run['prompt_sha256']:
        raise ValueError('任务提示词被修改。')
    for ref in run['inputs']:
        actual = (folder / ref['path']).resolve()
        if not actual.is_relative_to(root) or not actual.is_file() or digest(actual) != ref['sha256']:
            raise ValueError('任务输入缺失、越界或被修改。')
    if run.get('original'):
        _verified(folder, run['original'])
    return folder, run


def _state(root, data, item):
    entry = data['items'][item['id']]
    if entry['attempts'] and entry['state'] != 'queued':
        _, run = _run(root, entry)
        if run.get('approval_status') == '可用':
            return 'approved'
        if run.get('qa'):
            return 'needs_repair' if run['qa']['needs_repair'] else 'reviewed'
        if run.get('original'):
            return 'generated'
    if entry['state'] != 'queued':
        return entry['state']
    if data.get('scene') and data['scene'].get('error'):
        return 'blocked'
    if any(data['characters'][x['character']].get('error') for x in item['cast']):
        return 'blocked'
    orphan = root / '候审图' / '批次' / f'{item["id"]}-a{len(entry["attempts"]) + 1:04d}'
    if orphan.exists():
        return 'orphaned'
    for dependency in item.get('depends_on', []):
        dep = data['items'][dependency]
        bound = entry.get('dependency_attempts', {}).get(dependency)
        if not dep['attempts'] or (dep['state'] == 'queued' and bound is None):
            return 'waiting_dependency'
        _, run = _run(root, dep, bound)
        if not run.get('continuation_approval') and run.get('approval_status') != '可用':
            return 'waiting_dependency'
    return 'ready'


def status(folder):
    root, data, plan = _load(folder)
    items = []
    for item in plan['items']:
        try:
            current = _state(root, data, item)
            reason = data['items'][item['id']].get('reason')
        except (ValueError, OSError, KeyError) as error:
            current, reason = 'blocked', str(error)
        items.append({'id': item['id'], 'cast': [m['character'] for m in item['cast']],
                      'state': current, 'attempts': len(data['items'][item['id']]['attempts']), 'reason': reason})
    calls = {'confirmed_requests': 0, 'confirmed_successes': 0, 'attempts_without_final_receipt': 0}
    for entry in data['items'].values():
        for number in range(1, len(entry['attempts']) + 1):
            try:
                _, run = _run(root, entry, number)
                if run.get('generation'):
                    calls['confirmed_requests'] += run['generation']['request_count']
                    calls['confirmed_successes'] += run['generation']['success_count']
                elif run.get('failure_receipt', {}).get('request_count') is not None:
                    calls['confirmed_requests'] += run['failure_receipt']['request_count']
                else:
                    calls['attempts_without_final_receipt'] += 1
            except (ValueError, OSError, KeyError):
                calls['attempts_without_final_receipt'] += 1
    return {'batch': str(root), 'id': data['id'], 'total': len(items), 'counts': dict(Counter(x['state'] for x in items)),
            'calls': calls,
            'next': next((x['id'] for x in items if x['state'] in {'ready', 'prepared'}), None),
            'items': items, 'character_errors': {k: v['error'] for k, v in data['characters'].items() if 'error' in v},
            'scene_error': (data.get('scene') or {}).get('error')}


def _event(entry, action, evidence):
    entry['events'].append({'at': now(), 'action': action, 'evidence': evidence})


def _inputs_and_prompt(root, data, plan, item):
    settings = {key: value for key, value in plan.get('common', {}).items() if key in OVERRIDES}
    settings.update({key: item[key] for key in OVERRIDES if key in item})
    chosen = specs.resolve(plan['image_specs'], item['id']) if 'image_specs' in plan else None
    if chosen:
        settings.update(aspect=chosen['aspect'], size='native' if chosen['pixels'] == 'native' else 'x'.join(map(str, chosen['pixels'])))
    cast = item['cast']
    if len(cast) > 1 and not all(settings.get(key) for key in ['style_override', 'aspect', 'size']):
        raise ValueError('同框图需要明确本张统一 style_override、aspect、size，避免多个默认画风/画幅冲突。')
    inputs, sections = [], ['生成一张图片。']
    if len(cast) > 1:
        sections += [f'同框恰好 {len(cast)} 个指定角色；不可遗漏、重复、合并身份或增加路人。',
                     '按角色 ID 绑定外观、锚点、服装、动作与位置；任何参考脸都不能替换其它角色。']
    for member in cast:
        key = member['character']; char = data['characters'][key]
        if char.get('error'):
            raise ValueError(char['error'])
        _, _, _, content = pack._document(_verified(root, char['document']))
        refs = deepcopy(char['references']); manifest = deepcopy(char['manifest'])
        for ref in refs:
            _verified(root, ref)
        if item.get('master_from'):
            parent_state = data['items'][item['master_from']]
            bound = data['items'][item['id']].get('dependency_attempts', {}).get(item['master_from'])
            parent_folder, parent_run = _run(root, parent_state, bound)
            master = _verified(parent_folder, parent_run['original'])
            refs = [{'id': 'batch-master', 'role': 'identity', 'path': master.relative_to(root).as_posix(),
                     'sha256': digest(master), 'coverage': []}]
            manifest['primary_reference'] = 'batch-master'
        if not refs and not (char['mode'] == 'candidate' and item.get('asset_type') == 'master' and len(cast) == 1):
            raise ValueError('缺身份参考；仅新角色首次母版可纯文字生成。')
        options = dict(settings)
        if 'outfit_override' in member:
            options['outfit_override'] = member['outfit_override']
        rendered = pack.render(content, manifest, refs, item['resolved_request'] or '按本次场景、镜头和角色任务生成。',
                               extra_refs=member.get('reference_ids'), coverage=member.get('coverage'), **options)
        # The pure renderer's reference numbers are local. Replace them with one global mapping.
        character_prompt = '\n'.join(line for line in rendered['prompt'].splitlines()
                                     if not line.startswith('参考图 ') and line != '生成一张图片。')
        sections += [f'【角色 {key}】', character_prompt]
        if len(cast) > 1:
            sections += [f'位置：{member["position"]}；动作：{member["action"]}；可见范围：{member["visibility"]}']
        if member.get('required_anchors'):
            sections += ['本镜头必须可见的锚点：' + '、'.join(member['required_anchors'])]
        for ref in rendered['inputs']:
            inputs.append({'id': key + '/' + ref['id'], 'owner': key, 'path': ref['project_path'],
                           'sha256': ref['sha256'], 'uses': ref['uses']})
    scene = data.get('scene')
    if scene:
        if scene.get('error'):
            raise ValueError(scene['error'])
        content = read(_verified(root, scene['document']))
        sections += ['【固定场景】', *[f'{key}：{content[key]}' for key in ['name', 'location', 'layout', 'key_objects', 'lighting', 'continuity']],
                     '同一地点、布局、关键物件保持一致，允许依照本镜头换机位；空间左右以场景坐标为准，不是屏幕左右。']
        for ref in scene['references']:
            _verified(root, ref)
            inputs.append({'id': 'scene/' + ref['id'], 'owner': 'scene:' + content['id'],
                           'path': ref['path'], 'sha256': ref['sha256'],
                           'uses': [{'role': 'scene', 'allowed': ref['allowed'], 'forbidden': ref['forbidden']}]})
    if item.get('shot'):
        sections += ['【本次镜头】', *[f'{key}：{value}' for key, value in item['shot'].items()]]
    for number, ref in enumerate(inputs, 1):
        ref['number'] = number
        sections += [f'参考图 {number} 仅属于 {ref["owner"]}：' + '；'.join(f'{use["role"]}，允许：{use["allowed"]}；禁止：{use["forbidden"]}' for use in ref['uses'])]
    # Do not deduplicate across owners: equal bytes are not permission to blend identities.
    sections += ['合理遮挡的非必见锚点不必强行展示；不能把图板、标签、白底或风格参考中的陌生人物照搬进成片。']
    prompt = '\n'.join(sections)
    return inputs, specs.prompt_for(prompt, chosen) if chosen else prompt


def prepare(folder, key):
    root = Path(folder).resolve()
    with locked(root):
        root, data, plan = _load(root)
        item, entry = _item(plan, key), data['items'][key]
        state = _state(root, data, item)
        if state == 'prepared':
            target, run = _run(root, entry)
            return _delivery(target, run, already_prepared=True)
        if state != 'ready':
            raise ValueError(f'任务不可启动：{state}；不可重复提交 running/unknown/handoff。')
        try:
            inputs, prompt = _inputs_and_prompt(root, data, plan, item)
        except (ValueError, OSError, KeyError) as error:
            entry['state'] = 'blocked'; entry['reason'] = str(error)
            _event(entry, 'preflight-blocked', str(error))
            write(root / 'batch.json', data)
            raise
        number = len(entry['attempts']) + 1
        target = root / '候审图' / '批次' / f'{key}-a{number:04d}'
        target.mkdir(parents=True, exist_ok=False)
        for ref in inputs:
            ref['path'] = Path(os.path.relpath(root / ref['path'], target)).as_posix()
        run = {'schema_version': 2, 'batch_format': FORMAT, 'batch_id': data['id'], 'item_id': key,
               'run_id': target.name, 'attempt': number, 'created': now(), 'mode': 'batch',
               'asset_type': item.get('asset_type'), 'project_root': '../../..',
               'character_id': item['cast'][0]['character'] if len(item['cast']) == 1 else data['id'],
               'cast': item['cast'], 'request': item['resolved_request'], 'random_choices': item.get('random_choices', {}),
               'prompt_file': 'prompt.txt', 'inputs': inputs, 'tool': None, 'input_delivery_verified': False,
               'original': None, 'checks': {k: {'status': '无法判断', 'note': '尚未检查'} for k in runs.CHECKS},
               'approval_status': '待审核'}
        if 'image_specs' in plan:
            specs.attach(run, plan['image_specs'], key)
        _text_file(target / 'prompt.txt', prompt)
        write(target / 'inputs.json', inputs); write(target / 'run.json', run)
        repair = entry.get('repair')
        if repair:
            prompt += '\n【本轮修复】\n' + repair['note']
            (target / 'prompt.txt').write_text(prompt, encoding='utf-8')
            if repair['base'] == 'attempt':
                previous, previous_run = _run(root, entry, repair['source_attempt'])
                runs.add_edit_target(target, _verified(previous, previous_run['original']))
                run = read(target / 'run.json')
            run['repair'] = repair
        run['prompt_sha256'] = digest(target / 'prompt.txt')
        write(target / 'run.json', run)
        entry['attempts'].append({'path': target.relative_to(root).as_posix(), 'number': number})
        entry['state'] = 'prepared'
        _event(entry, 'prepared', f'attempt {number}; no image call made')
        write(root / 'batch.json', data)
        return _delivery(target, run)


def _delivery(folder, run, **extra):
    return {'run': str(folder), 'prompt_file': str(folder / 'prompt.txt'),
            'inputs': [{**ref, 'path': str((folder / ref['path']).resolve())} for ref in run['inputs']],
            'state': 'prepared', 'image_generated': bool(run.get('original')), **extra}


def dispatch(folder, key, evidence, handoff=False):
    required_text({'evidence': evidence}, ['evidence'])
    root = Path(folder).resolve()
    with locked(root):
        root, data, plan = _load(root)
        item, entry = _item(plan, key), data['items'][key]
        if _state(root, data, item) != 'prepared':
            raise ValueError('仅 prepared 可提交；此前提交结果未知时先核对，不自动重发。')
        target, run = _run(root, entry)
        if not handoff:
            specs.plan_for_run(target, run)
        run['submission'] = {'at': now(), 'handoff': handoff, 'evidence': evidence}
        write(target / 'run.json', run)
        entry['state'] = 'handoff' if handoff else 'running'
        _event(entry, entry['state'], evidence)
        write(root / 'batch.json', data)
    return {'id': key, 'state': entry['state'], 'note': '这是提交/交接记录，不是图像工具调用或成功证明。'}


def recover(folder, key, evidence, not_submitted=False):
    """Adopt a complete orphan after a local interrupted write; never discard a partial run."""
    required_text({'evidence': evidence}, ['evidence'])
    root = Path(folder).resolve()
    with locked(root):
        root, data, plan = _load(root)
        item, entry = _item(plan, key), data['items'][key]
        if _state(root, data, item) != 'orphaned':
            raise ValueError('没有需要恢复的孤立轮次。')
        number = len(entry['attempts']) + 1
        relative = f'候审图/批次/{key}-a{number:04d}'
        entry['attempts'].append({'path': relative, 'number': number})
        _, run = _run(root, entry)
        if run.get('batch_id') != data['id'] or run.get('item_id') != key or run.get('attempt') != number:
            raise ValueError('孤立记录与本任务不符，不接管。')
        entry['state'] = 'prepared' if not_submitted else 'unknown'
        _event(entry, 'recovered-' + entry['state'], evidence)
        write(root / 'batch.json', data)
    return {'id': key, 'state': _state(root, data, item)}


def record(folder, key, source, metadata):
    root = Path(folder).resolve()
    with locked(root):
        root, data, plan = _load(root)
        item, entry = _item(plan, key), data['items'][key]
        if _state(root, data, item) not in {'running', 'unknown', 'handoff'}:
            raise ValueError('仅已提交或已交接的任务能回填结果。')
        target, run = _run(root, entry)
        if run['inputs'] and metadata.get('reference_delivery', {}).get('verified') is not True:
            raise ValueError('固定角色/场景必须有真实传图证据；不要将文字路径或未传图结果记作完成。')
        if metadata.get('request_count') != 1 or metadata.get('success_count') != 1:
            raise ValueError('本队列每个 attempt 对应一次调用的一张图；额外调用须先记录失败并获准重试。')
        result = runs.record(target, source, metadata)
        entry['state'] = 'generated'; _event(entry, 'recorded', metadata['tool'])
        write(root / 'batch.json', data)
    return result


def outcome(folder, key, state, evidence, request_count=None):
    if state not in {'failed', 'unknown', 'resolved_no_output'}:
        raise ValueError('outcome 为 failed、unknown 或 resolved_no_output。')
    required_text({'evidence': evidence}, ['evidence'])
    if request_count is not None and (type(request_count) is not int or request_count not in {0, 1}):
        raise ValueError('本轮真实调用数只能为 0/1；不清楚时省略，不能猜测。')
    root = Path(folder).resolve()
    with locked(root):
        root, data, plan = _load(root)
        item, entry = _item(plan, key), data['items'][key]
        current = _state(root, data, item)
        if current not in {'running', 'handoff', 'unknown'}:
            raise ValueError('只有未收到结果的已提交任务能记录调用结果。')
        if current == 'unknown' and state != 'resolved_no_output':
            raise ValueError('结果未知时需先核实无输出，再使用 resolved_no_output；有图则 record。')
        entry['state'] = 'failed' if state == 'resolved_no_output' else state
        target, run = _run(root, entry)
        run['failure_receipt'] = {'outcome': state, 'evidence': evidence, 'request_count': request_count, 'at': now()}
        write(target / 'run.json', run)
        _event(entry, state, evidence)
        write(root / 'batch.json', data)
    return {'id': key, 'state': entry['state']}


def _check_item(value):
    if not isinstance(value, dict) or value.get('status') not in {'通过', '待修', '无法判断'}:
        raise ValueError('检查项须含 status=通过/待修/无法判断。')
    required_text(value, ['note'])
    if value['note'].strip() in {'尚未实际检查', '尚未检查'}:
        raise ValueError('请实际检查并填写观察，不得直接提交空白检查模板。')


def review(folder, key, checks):
    root = Path(folder).resolve()
    with locked(root):
        root, data, plan = _load(root)
        item, entry = _item(plan, key), data['items'][key]
        if _state(root, data, item) not in {'generated', 'reviewed', 'needs_repair', 'approved'}:
            raise ValueError('当前任务尚未有可审核结果。')
        target, run = _run(root, entry)
        if not run.get('original'):
            raise ValueError('尚未回填原图，不能审核。')
        if set(checks.get('global', {})) != set(runs.CHECKS):
            raise ValueError('global 需要六项通用检查。')
        if set(checks.get('characters', {})) != {m['character'] for m in item['cast']}:
            raise ValueError('必须逐一检查本图全部角色，不接受总体“看起来正常”。')
        all_checks = list(checks['global'].values()) + [checks.get('continuity')]
        mandatory = [checks['global']['identity'], checks['global']['request']]
        for member in item['cast']:
            values = checks['characters'][member['character']]
            if set(values) != {'identity', 'anchors', 'placement'}:
                raise ValueError('每个角色需要 identity、anchors、placement 三项。')
            all_checks += list(values.values())
            mandatory += [values['identity'], values['placement']]
            if member.get('required_anchors'):
                mandatory += [values['anchors']]
        if data.get('scene'):
            mandatory += [checks['continuity']]
        for value in all_checks:
            _check_item(value)
        needs_repair = any(x['status'] == '待修' for x in all_checks) or any(x['status'] != '通过' for x in mandatory)
        needs_repair = needs_repair or specs.acceptance_needed(run)
        runs.review(target, checks['global'])
        run = read(target / 'run.json')
        run['qa'] = {'at': now(), 'checks': checks, 'needs_repair': needs_repair}
        run.setdefault('qa_history', []).append(deepcopy(run['qa']))
        # Changed QA invalidates old acceptance; the historical statement remains auditable.
        run['approval_status'] = '待审核'; run.pop('continuation_approval', None); run.pop('spec_acceptance', None)
        write(target / 'run.json', run)
        entry['state'] = 'needs_repair' if needs_repair else 'reviewed'
        write(root / 'batch.json', data)
    return {'id': key, 'state': entry['state'], 'user_approved': False}


def approve(folder, key, statement, purpose='output', accept_issues=False):
    required_text({'approval': statement}, ['approval'])
    if purpose not in {'output', 'continuation'}:
        raise ValueError('purpose 为 output 或 continuation。')
    root = Path(folder).resolve()
    with locked(root):
        root, data, plan = _load(root)
        item, entry = _item(plan, key), data['items'][key]
        if _state(root, data, item) not in {'reviewed', 'needs_repair', 'approved'}:
            raise ValueError('当前任务尚未完成 QA。')
        target, run = _run(root, entry)
        if not run.get('qa') or (run['qa']['needs_repair'] and not accept_issues):
            raise ValueError('先完成 QA；已知偏差只有用户明确接受时才加 accept_issues。')
        if purpose == 'continuation':
            run['continuation_approval'] = {'at': now(), 'statement': statement, 'accept_issues': accept_issues}
            write(target / 'run.json', run)
        else:
            runs.review(target, status='可用', approval=statement, accept_issues=accept_issues)
        for child in plan['items']:
            if key in child.get('depends_on', []):
                # An already released derivative retains its exact approved parent attempt.
                data['items'][child['id']].setdefault('dependency_attempts', {}).setdefault(key, len(entry['attempts']))
        _event(entry, 'approve-' + purpose, statement)
        write(root / 'batch.json', data)
    return {'id': key, 'purpose': purpose, 'formal_character_registered': False}


def retry(folder, key, approval, note, base='original', source_attempt=None):
    required_text({'approval': approval, 'note': note}, ['approval', 'note'])
    if base not in {'original', 'attempt'}:
        raise ValueError('base 只能为 original 或 attempt。')
    root = Path(folder).resolve()
    with locked(root):
        root, data, plan = _load(root)
        item, entry = _item(plan, key), data['items'][key]
        current = _state(root, data, item)
        if current not in {'failed', 'needs_repair', 'reviewed', 'approved', 'generated'}:
            raise ValueError('此状态不能重试；结果未知需先核对，已排队无需重复授权。')
        if base == 'attempt':
            if source_attempt is None:
                raise ValueError('编辑修复必须明确 source_attempt，不能默认沿用最后一次漂移图。')
            _, previous = _run(root, entry, source_attempt)
            if not previous.get('original'):
                raise ValueError('指定轮次没有原图。')
        entry['repair'] = {'base': base, 'source_attempt': source_attempt, 'note': note, 'approval': approval}
        entry['state'] = 'queued'
        _event(entry, 'retry-authorized', approval)
        write(root / 'batch.json', data)
    return {'id': key, 'state': 'queued', 'extra_calls_authorized': 1}


def archive(folder, key):
    root, data, plan = _load(folder)
    if _state(root, data, _item(plan, key)) != 'approved':
        raise ValueError('当前轮次尚未获得用户认可。')
    target, _ = _run(root, data['items'][key])
    return pack.archive(target, key)


def report(folder):
    root, data, plan = _load(folder)
    summary = status(root)
    lines = [f'# 批次 {data["id"]}', '', f'计划 {summary["total"]} 张；状态：{summary["counts"]}', '',
             f'已记录的真实调用：{summary["calls"]["confirmed_requests"]}；已记录成功调用：{summary["calls"]["confirmed_successes"]}；没有最终回执的准备/调用轮次：{summary["calls"]["attempts_without_final_receipt"]}。未收到回执不等于调用失败。', '',
             '准备提示词、已提交、已生图、AI检查通过、用户认可分别统计。', '',
             '| 任务 | 角色 | 状态 | 轮次 | 原图 |', '|---|---|---|---:|---|']
    for item in summary['items']:
        entry = data['items'][item['id']]
        link = ''
        try:
            if entry['attempts']:
                target, run = _run(root, entry)
                if run.get('original'):
                    link = f'[查看](<{(target / run["original"]["path"]).relative_to(root).as_posix()}>)'
        except (ValueError, OSError, KeyError):
            pass
        lines.append(f'| {item["id"]} | {", ".join(item["cast"])} | {item["state"]} | {item["attempts"]} | {link} |')
    lines += ['', '## 集中处理', '']
    for item in summary['items']:
        if item['state'] in {'needs_repair', 'failed', 'unknown', 'blocked', 'handoff', 'waiting_dependency', 'orphaned', 'reviewed'}:
            lines += [f'- {item["id"]}：{item["state"]}。{item["reason"] or "查看该任务记录后决定；不会自动补调用。"}']
            entry = data['items'][item['id']]
            if entry['attempts']:
                try:
                    _, run = _run(root, entry)
                    if run.get('spec_verification'):
                        verification = run['spec_verification']
                        lines += [f'  - 输出规格：{verification["status"]}；{verification.get("note", "")}']
                        lines += [f'    - {k}：{v["status"]}，{v["note"]}' for k, v in verification.get('checks', {}).items() if v['status'] != 'PASS']
                    if run.get('qa'):
                        qa = run['qa']['checks']
                        observations = [('整体/' + k, v) for k, v in qa['global'].items()]
                        observations += [(owner + '/' + k, v) for owner, values in qa['characters'].items() for k, v in values.items()]
                        observations += [('场景连续性', qa['continuity'])]
                        lines += [f'  - {name}：{value["status"]}，{value["note"]}' for name, value in observations if value['status'] != '通过']
                except (ValueError, OSError, KeyError):
                    pass
    # A report is a replaceable view, never the authoritative state.
    (root / '批量报告.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'report': str(root / '批量报告.md'), **summary}
