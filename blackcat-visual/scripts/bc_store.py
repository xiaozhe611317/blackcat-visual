"""Small persistent library. Personal data never lives inside the skill package."""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

SKILL = Path(__file__).resolve().parents[1]
BODY_VIEWS = ['front', 'left_three_quarter', 'right_three_quarter', 'left_side', 'right_side', 'back']
FACE_VIEWS = ['front', 'left_three_quarter', 'right_three_quarter', 'left_side', 'right_side']
EXPRESSIONS = ['neutral', 'smile', 'laugh', 'sad', 'surprised', 'angry']

def now():
    return datetime.now(timezone.utc).isoformat()

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.blackcat-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value) or len(value) > 64:
        raise ValueError('ID 必须是 1–64 个小写字母、数字和单个连接号，不使用显示名称作路径。')
    if value.upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError('ID 不能使用系统保留名称。')
    return value

def config_path():
    override = os.environ.get('BLACKCAT_CONFIG')
    if override:
        return Path(override).expanduser().resolve()
    return Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'blackcat-visual' / 'settings.json'

def root_path(explicit=None):
    if explicit:
        root = Path(explicit).expanduser().resolve()
    else:
        cfg = config_path()
        if not cfg.is_file():
            raise ValueError('尚未初始化：先选择个人资料库目录。')
        root = Path(read(cfg)['library'])
    if not (root / 'library.json').is_file():
        raise ValueError(f'资料库未初始化或路径失效，请重新定位：{root}')
    return root

@contextlib.contextmanager
def locked(root):
    lock = Path(root) / '.blackcat-write.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError('资料库正在写入；稍后再试。异常退出遗留的锁需检查进程后移除。')
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)

def initialize(root, bind=True):
    root = Path(root).expanduser().resolve()
    if root == SKILL or SKILL in root.parents:
        raise ValueError('个人资料库不能位于技能发布目录内。')
    if bind and config_path().exists() and Path(read(config_path())['library']).resolve() != root:
        raise ValueError('已有其他资料库绑定。使用 bind 明确切换，当前绑定未改变。')
    root.mkdir(parents=True, exist_ok=True)
    with locked(root):
        index = root / 'library.json'
        if index.exists():
            current = read(index)
            if current.get('format') != 'blackcat-library-v1':
                raise ValueError('目标目录中已有其他 library.json，请选择专用目录。')
        else:
            write(index, {'format': 'blackcat-library-v1', 'created': now(), 'characters': {}, 'styles': {}})
    if bind:
        cfg = config_path()
        if cfg.exists() and Path(read(cfg)['library']).resolve() != root:
            raise ValueError('已有其他资料库绑定。使用 bind 明确切换，当前绑定未改变。')
        write(cfg, {'schema_version': 1, 'library': str(root)})
    return {'library': str(root), 'initialized': True, 'characters': 0 if not index.exists() else len(read(index)['characters'])}

def library(root):
    result = read(Path(root) / 'library.json')
    if result.get('format') != 'blackcat-library-v1':
        raise ValueError('不支持的资料库格式。')
    return result

def resolve(root, kind, name):
    entries = library(root)[kind + 's']
    matches = [key for key, item in entries.items() if name == key or name == item['name'] or name in item.get('aliases', [])]
    if len(matches) != 1:
        raise ValueError(f'{kind} 选择不唯一或不存在：{name}；请先 list 后明确 ID。')
    return matches[0], entries[matches[0]]

def load_profile(root, kind, name):
    key, entry = resolve(root, kind, name)
    folder = Path(entry['root'])
    path = folder / 'profiles' / f'v{entry["revision"]:04d}.json'
    if not path.is_file():
        raise ValueError(f'档案路径失效，请 rebind：{folder}')
    data = read(path)
    if data['id'] != key or data['kind'] != kind or data['revision'] != entry['revision']:
        raise ValueError('档案与索引不匹配。')
    for ref in data['references']:
        actual = folder / ref['path']
        if not actual.is_file() or digest(actual) != ref['sha256']:
            raise ValueError(f'参考缺失或内容被修改：{actual}')
        ref['actual_path'] = str(actual)
    return data, folder

def required_text(data, fields):
    for field in fields:
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f'必须填写：{field}')

def image_info(path):
    from PIL import Image
    with Image.open(path) as im:
        im.load()
        return {'size': list(im.size), 'mode': im.mode, 'format': im.format}

def validate_profile(data, kind):
    identifier(data['id'])
    required_text(data, ['name'])
    if not isinstance(data.get('aliases', []), list) or any(not isinstance(x, str) or not x for x in data.get('aliases', [])):
        raise ValueError('aliases 必须是非空名称组成的列表。')
    refs = data.get('references', [])
    if not isinstance(refs, list) or not refs:
        raise ValueError('缺少经检查的参考图。')
    ref_ids = set()
    coverage = set()
    for ref in refs:
        if not isinstance(ref, dict):
            raise ValueError('每项参考必须是包含路径和用途的对象。')
        required_text(ref, ['id', 'path', 'role', 'allowed', 'forbidden'])
        identifier(ref['id'])
        if ref['id'] in ref_ids:
            raise ValueError('参考 ID 重复。')
        ref_ids.add(ref['id'])
        tags = ref.get('coverage', [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in tags):
            raise ValueError('coverage 必须为非空文本标签组成的列表，可以为空列表。')
        coverage.update(tags)
        if ref.get('visually_checked') is not True:
            raise ValueError(f'参考尚未实际查看：{ref["id"]}')
        if not Path(ref['path']).is_absolute() or not Path(ref['path']).is_file():
            raise ValueError(f'参考图需要存在的绝对路径：{ref["path"]}')
        image_info(ref['path'])
    if kind == 'character':
        if any(ref['role'] not in ['identity', 'identity_support'] for ref in refs):
            raise ValueError('主角参考角色必须为 identity 或 identity_support。')
        required_text(data, ['age_impression', 'face_structure', 'hair', 'body_proportions', 'identity_constraints', 'allowed_changes', 'baseline_medium'])
        if data.get('primary_reference') not in ref_ids:
            raise ValueError('必须指定唯一身份主参考 primary_reference。')
        if next(ref for ref in refs if ref['id'] == data['primary_reference'])['role'] != 'identity':
            raise ValueError('身份主参考的 role 必须为 identity。')
        missing = {f'body:{x}' for x in BODY_VIEWS} | {f'face:{x}' for x in FACE_VIEWS} | {f'expression:{x}' for x in EXPRESSIONS}
        missing -= coverage
        if missing:
            raise ValueError('标准视图包缺项：' + ', '.join(sorted(missing)))
        anchors = data.get('anchors')
        if not isinstance(anchors, dict) or anchors.get('mode') not in ['defined', 'none']:
            raise ValueError('anchors.mode 必须明确为 defined 或 none。')
        required_text(anchors, ['description'])
        if anchors['mode'] == 'defined':
            required_text(anchors, ['placement', 'occlusion_rules'])
            if 'anchor:details' not in coverage:
                raise ValueError('缺少锚点细节图；可由已有设定图覆盖。')
    elif kind == 'style':
        required_text(data, ['type', 'realism', 'linework', 'coloring', 'lighting', 'palette', 'materials', 'detail_density', 'preserve_textures', 'avoid', 'default_aspect', 'default_size'])
        if any(ref['role'] != 'style' for ref in refs):
            raise ValueError('风格档案中的图片只能登记为 style 参考。')

def copy_references(data, folder):
    result = []
    for ref in data['references']:
        source = Path(ref['path']).resolve()
        sha = digest(source)
        target = folder / 'references' / f'{ref["id"]}-{sha[:16]}{source.suffix.lower()}'
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
        if digest(target) != sha:
            raise ValueError('参考图复制校验失败。')
        item = {k: v for k, v in ref.items() if k not in ['actual_path', 'source_path']}
        item.update(path=target.relative_to(folder).as_posix(), source_path=str(source), sha256=sha, **image_info(target))
        result.append(item)
    return result

def save_profile(root, kind, data, approval, folder=None, update=False):
    if not approval or not approval.strip():
        raise ValueError('保存正式档案需要记录管理者本次明确认可的原话。')
    validate_profile(data, kind)
    root = Path(root).resolve()
    with locked(root):
        index = library(root)
        entries = index[kind + 's']
        key = data['id']
        previous = entries.get(key)
        if previous and not update:
            raise ValueError('同 ID 已存在。新增使用新 ID；修改需要 --update 和明确变更授权。')
        if update and not previous:
            raise ValueError('待修改的档案不存在。')
        names = {key, data['name'], *data.get('aliases', [])}
        if any(names & {other_id, row['name'], *row.get('aliases', [])} for other_id, row in entries.items() if other_id != key):
            raise ValueError('名称或别名与已有档案重复。')
        if previous:
            folder = Path(previous['root'])
            load_profile(root, kind, key)
        elif kind == 'character':
            folder = root / 'characters' / key
        elif folder is None:
            raise ValueError('新风格必须选择独立的保存文件夹。')
        folder = Path(folder).expanduser().resolve()
        if folder == SKILL or SKILL in folder.parents:
            raise ValueError('个人素材不能放入技能发布目录。')
        for group in ('characters', 'styles'):
            for other_id, row in index[group].items():
                if group == kind + 's' and other_id == key:
                    continue
                other = Path(row['root']).resolve()
                if folder == other or other in folder.parents or folder in other.parents:
                    raise ValueError('档案目录不能与其他主角或风格目录重叠。')
        if kind == 'style':
            if folder == root or folder in root.parents:
                raise ValueError('风格目录不能占用资料库根目录或其上级目录。')
            for reserved_name in ('characters', 'drafts', 'runtime', 'cache', 'tmp'):
                reserved = (root / reserved_name).resolve()
                if folder == reserved or reserved in folder.parents:
                    raise ValueError('风格目录不能占用主角、草稿或运行环境目录；请选独立子文件夹。')
        marker = folder / 'blackcat-profile.json'
        if marker.exists() and read(marker) != {'kind': kind, 'id': key}:
            raise ValueError('该目录属于其他档案。')
        revision = previous['revision'] + 1 if previous else 1
        target = folder / 'profiles' / f'v{revision:04d}.json'
        if target.exists():
            raise ValueError('目标版本已存在，未覆盖；请检查此前未完成的保存。')
        record = {k: v for k, v in data.items() if k not in ['revision', 'approved_at', 'approval', 'kind']}
        record.update(schema_version=1, kind=kind, revision=revision, approved_at=now(), approval=approval)
        record['references'] = copy_references(data, folder)
        write(marker, {'kind': kind, 'id': key})
        write(target, record)
        entries[key] = {'name': data['name'], 'aliases': data.get('aliases', []), 'root': str(folder), 'revision': revision}
        write(root / 'library.json', index)
    return {'id': key, 'revision': revision, 'path': str(target)}

def pair_path(style_folder, character_id):
    return Path(style_folder) / 'combinations' / identifier(character_id)

def load_pair(character, style, style_folder):
    folder = pair_path(style_folder, character['id'])
    current = folder / 'current.json'
    if not current.exists():
        return None
    pair = read(folder / read(current)['file'])
    if pair['character_revision'] != character['revision'] or pair['style_revision'] != style['revision']:
        return None
    for ref in pair['references']:
        path = folder / ref['path']
        if not path.exists() or digest(path) != ref['sha256']:
            raise ValueError('组合参考缺失或内容改变。')
        ref['actual_path'] = str(path)
    return pair

def save_pair(root, character_name, style_name, source, notes, approval):
    required_text({'notes': notes, 'approval': approval}, ['notes', 'approval'])
    with locked(root):
        character, _ = load_profile(root, 'character', character_name)
        style, style_folder = load_profile(root, 'style', style_name)
        folder = pair_path(style_folder, character['id'])
        current = folder / 'current.json'
        revision = read(current)['revision'] + 1 if current.exists() else 1
        target = folder / f'v{revision:04d}.json'
        if target.exists():
            raise ValueError('组合版本已存在，未覆盖。')
        refs = copy_references({'references': [{'id': 'approved-sample', 'path': str(Path(source).resolve()), 'role': 'pair', 'allowed': '仅对应主角在此风格下的表现', 'forbidden': '不得建立新身份或供其他主角使用', 'coverage': [], 'visually_checked': True}]}, folder)
        data = {'schema_version': 1, 'character_id': character['id'], 'style_id': style['id'], 'character_revision': character['revision'], 'style_revision': style['revision'], 'revision': revision, 'adaptation_notes': notes, 'approval': approval, 'approved_at': now(), 'references': refs}
        write(target, data)
        write(current, {'revision': revision, 'file': target.name})
    return {'path': str(target), 'revision': revision}

def select(root, character_name, style_name, mode='production'):
    character, _ = load_profile(root, 'character', character_name)
    style, folder = load_profile(root, 'style', style_name)
    pair = load_pair(character, style, folder)
    if mode == 'production' and pair is None:
        raise ValueError('此组合尚无当前版本的定稿参考。先用 --mode sample 生成适配样张，经认可后 save-pair。')
    primary = character['primary_reference']
    character['references'].sort(key=lambda r: r['id'] != primary)
    return {'character': character, 'style': style, 'pair': pair, 'mode': mode, 'output_root': str(folder / 'works' / character['id'])}

def rebind(root, kind, name, folder, approval):
    if not approval:
        raise ValueError('重新定位需要明确指定新目录。')
    folder = Path(folder).resolve()
    with locked(root):
        index = library(root)
        key, _ = resolve(root, kind, name)
        entry = index[kind + 's'][key]
        marker = folder / 'blackcat-profile.json'
        profile = folder / 'profiles' / f'v{entry["revision"]:04d}.json'
        if not marker.exists() or read(marker) != {'kind': kind, 'id': key} or not profile.exists():
            raise ValueError('新目录不包含原档案，请先定位完整的既有档案文件夹。')
        record = read(profile)
        if record.get('id') != key or record.get('kind') != kind or record.get('revision') != entry['revision']:
            raise ValueError('新目录的档案身份或版本不匹配。')
        for ref in record['references']:
            if not (folder / ref['path']).is_file() or digest(folder / ref['path']) != ref['sha256']:
                raise ValueError('新目录的参考不完整。')
        entry['root'] = str(folder)
        write(Path(root) / 'library.json', index)
    return {'id': key, 'root': str(folder)}
