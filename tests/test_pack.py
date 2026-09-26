"""V2 package contracts; synthetic pictures never certify visual likeness or quality."""
import copy
from pathlib import Path
import shutil
import sys

from PIL import Image
import pytest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'blackcat-visual' / 'scripts'))
import bc_pack as pack
import bc_runs as runs
import bc_store as store

DOCUMENT = '''# Lin 生图
## 角色身份
成年女性，圆脸，棕色眼睛。
## 固定锚点
右耳银色耳夹；本人左右，合理遮挡不强求露出。
## 默认外观
- 服装：白色衬衣
- 妆容：自然妆
- 发型：黑色短发
## 默认风格
- 画法：水彩，纸纹
- 当前风格限制：禁止摄影质感
- 通用限制：避免烟草和酒瓶
## 画幅
- 比例：2:3
- 尺寸：1024x1536
## 随机范围
- 场景：书店｜河岸
- 动作：阅读｜散步
- 时间：清晨｜傍晚
- 构图：半身｜全身
## 生图规则
- 画面约束：身份优先，锚点左右以人物自身为准。
先读文件后记录审核；这一句不是绘画内容。
## 视觉参考
[母版](视觉资产/master.png) 控制身份；[辅助](视觉资产/support.png)按需选择；[风格](视觉资产/style.png)。
'''


def ref(name, role, coverage=()):
    return {'id': name, 'path': f'视觉资产/{name}.png', 'role': role,
            'coverage': list(coverage), 'visually_checked': True}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv('BLACKCAT_CONFIG', str(tmp_path / 'no-global-config.json'))
    root = tmp_path / '角色 中文 space'
    pack.initialize_project(root)
    document = root / 'Lin生图.md'
    document.write_text(DOCUMENT, encoding='utf-8')
    for name, color in [('master', 'blue'), ('support', 'red'), ('style', 'green')]:
        Image.new('RGB', (30, 40), color).save(root / '视觉资产' / f'{name}.png')
    coverage = ([f'body:{x}' for x in store.BODY_VIEWS]
                + [f'face:{x}' for x in store.FACE_VIEWS]
                + [f'expression:{x}' for x in store.EXPRESSIONS] + ['anchor:details'])
    data = {'id': 'lin', 'name': 'Lin', 'anchors_mode': 'defined', 'primary_reference': 'master',
            'references': [ref('master', 'identity'), ref('support', 'identity_support', coverage),
                           ref('style', 'style'), {**ref('style', 'pair'), 'id': 'pair'}]}
    return root, document, data


def save(project):
    _, document, data = project
    return pack.save(document, data, 'SYNTHETIC CONTRACT APPROVAL')


def record(folder, source):
    return runs.record(folder, source, {
        'tool': 'fixture', 'actual_submitted_prompt': 'synthetic contract test only',
        'reference_delivery': {'verified': True, 'evidence': 'synthetic fixture, not a live tool'},
        'visible_parameters': {}, 'request_count': 1, 'success_count': 1})


def approve(folder):
    checks = {key: {'status': '通过', 'note': 'fixture states only, not a visual review'}
              for key in runs.CHECKS}
    runs.review(folder, checks, '可用', 'SYNTHETIC APPROVAL')


def test_save_load_hashes_and_explicit_update_preserve_snapshots(project):
    root, document, data = project
    saved = save(project)
    bundle = pack.load(document)
    assert bundle['manifest']['document_sha256'] == store.digest(document)
    assert bundle['manifest']['revision'] == 1
    assert bundle['manifest']['references'][0]['size'] == [30, 40]
    assert 'markdown' not in bundle['manifest'] and 'sections' not in bundle['manifest']
    history = root / '过程记录/角色登记/Lin生图/v0001.md'
    first = history.read_bytes()
    document.write_text(DOCUMENT.replace('自然妆', '淡妆'), encoding='utf-8')
    with pytest.raises(ValueError, match='MD 已修改'):
        pack.load(document)
    with pytest.raises(ValueError, match='update'):
        save(project)
    assert pack.save(document, data, 'APPROVED CHANGE', update=True)['revision'] == 2
    assert history.read_bytes() == first
    assert pack.check(document)['revision'] == 2
    assert store.read(saved['manifest'])['approval'] == 'APPROVED CHANGE'
    assert not Path(__import__('os').environ['BLACKCAT_CONFIG']).exists()


def test_check_describes_declarations_not_visual_certification(project):
    save(project)
    result = pack.check(project[1])
    assert result['status'] == 'PASS'
    assert '覆盖声明' in result['note'] and '不替代实际视觉审核' in result['note']


def test_document_links_must_match_actual_registered_inputs(project):
    root, document, data = project
    document.write_text(DOCUMENT.replace('[辅助](视觉资产/support.png)', '未同步的辅助参考'), encoding='utf-8')
    with pytest.raises(ValueError, match='视觉参考链接'):
        pack.save(document, data, 'TEST')


def test_workflow_instructions_not_sent_to_image_model(project):
    save(project)
    result = pack.prepare(project[1], '在书店')
    prompt = Path(result['prompt_file']).read_text(encoding='utf-8')
    assert '先读文件后记录审核' not in prompt
    assert '锚点左右以人物自身为准' in prompt
    assert '本次外观要求优先' in prompt


def test_edit_inputs_are_portable_and_returned_paths_are_actual(project, tmp_path):
    root, document, _ = project
    save(project)
    result = pack.prepare(document, '只更换背景')
    target = tmp_path / 'external.png'
    Image.new('RGB', (20, 30), 'yellow').save(target)
    edited = runs.add_edit_target(result['run'], target)
    assert all(Path(item['path']).is_absolute() and Path(item['path']).is_file() for item in edited['inputs'])
    run = Path(result['run'])
    saved = store.read(run / 'run.json')
    assert saved['inputs'][-1]['path'] == 'edit-target.png'
    moved = tmp_path / 'moved-project'
    shutil.move(root, moved)
    moved_run = moved / run.relative_to(root)
    for item in saved['inputs']:
        assert store.digest((moved_run / item['path']).resolve()) == item['sha256']


@pytest.mark.parametrize('change', ['missing-section', 'empty-section', 'duplicate', 'template'])
def test_incomplete_or_ambiguous_document_rejected(project, change):
    _, document, data = project
    text = DOCUMENT
    if change == 'missing-section': text = text.replace('## 固定锚点', '## 非规定章节')
    if change == 'empty-section': text = text.replace('右耳银色耳夹；本人左右，合理遮挡不强求露出。', '')
    if change == 'duplicate': text += '\n## 默认风格\n另一个值\n'
    if change == 'template': text = text.replace('白色衬衣', '{{默认服装}}')
    document.write_text(text, encoding='utf-8')
    with pytest.raises(ValueError):
        pack.save(document, data, 'TEST')


@pytest.mark.parametrize('change', ['body', 'face', 'expression', 'anchor', 'style', 'pair', 'unchecked', 'bad-hash', 'duplicate-id', 'multiple-identity', 'not-object'])
def test_reference_contract_gates(project, change):
    _, document, data = project
    data = copy.deepcopy(data)
    if change in {'body', 'face', 'expression', 'anchor'}:
        tags = data['references'][1]['coverage']
        tags.remove(next(tag for tag in tags if tag.startswith(change + ':')))
    elif change in {'style', 'pair'}:
        data['references'] = [item for item in data['references'] if item['role'] != change]
    elif change == 'unchecked': data['references'][0]['visually_checked'] = False
    elif change == 'bad-hash': data['references'][0]['sha256'] = 'bad'
    elif change == 'duplicate-id': data['references'][1]['id'] = 'master'
    elif change == 'multiple-identity': data['references'][1]['role'] = 'identity'
    elif change == 'not-object': data['references'][1] = 'bad'
    with pytest.raises(ValueError):
        pack.save(document, data, 'TEST')


def test_style_coverage_cannot_complete_missing_identity_views(project):
    _, document, data = project
    data['references'][2]['coverage'] = data['references'][1].pop('coverage')
    with pytest.raises(ValueError, match='覆盖缺项'):
        pack.save(document, data, 'TEST')


def test_no_anchors_waives_only_anchor_detail(project):
    _, document, data = project
    data['anchors_mode'] = 'none'
    data['references'][1]['coverage'].remove('anchor:details')
    document.write_text(DOCUMENT.replace('右耳银色耳夹；本人左右，合理遮挡不强求露出。', '无独立锚点'), encoding='utf-8')
    save(project)
    assert pack.check(document)['status'] == 'PASS'


@pytest.mark.parametrize('change', ['missing', 'changed', 'missing-hash'])
def test_reference_integrity_after_registration(project, change):
    root, document, _ = project
    saved = save(project)
    image = root / '视觉资产/master.png'
    if change == 'missing': image.unlink()
    elif change == 'changed': Image.new('RGB', (30, 40), 'black').save(image)
    else:
        data = store.read(saved['manifest'])
        data['references'][0].pop('sha256')
        store.write(saved['manifest'], data)
        store.write(root / '过程记录/角色登记/Lin生图/v0001.json', data)
    with pytest.raises(ValueError):
        pack.load(document)


@pytest.mark.parametrize('change', ['snapshot-md', 'snapshot-json', 'existing-next-version', 'changed-old-reference'])
def test_update_never_rewrites_old_history_or_assets(project, change):
    root, document, data = project
    saved = save(project)
    manifest_bytes = Path(saved['manifest']).read_bytes()
    history = root / '过程记录/角色登记/Lin生图'
    if change == 'snapshot-md': (history / 'v0001.md').write_text('tampered', encoding='utf-8')
    elif change == 'snapshot-json': store.write(history / 'v0001.json', {'modified': True})
    elif change == 'existing-next-version': (history / 'v0002.md').write_text('never overwrite', encoding='utf-8')
    else: Image.new('RGB', (30, 40), 'yellow').save(root / '视觉资产/master.png')
    document.write_text(DOCUMENT.replace('自然妆', '淡妆'), encoding='utf-8')
    with pytest.raises(ValueError):
        pack.save(document, data, 'TEST UPDATE', update=True)
    assert Path(saved['manifest']).read_bytes() == manifest_bytes
    if change == 'existing-next-version':
        assert (history / 'v0002.md').read_text(encoding='utf-8') == 'never overwrite'


def test_update_requires_previous_and_same_id_and_approval(project):
    _, document, data = project
    with pytest.raises(ValueError, match='未登记'):
        pack.save(document, data, 'TEST', update=True)
    with pytest.raises(ValueError, match='approval'):
        pack.save(document, data, '')
    save(project)
    data['id'] = 'other'
    with pytest.raises(ValueError, match='不匹配'):
        pack.save(document, data, 'TEST', update=True)


@pytest.mark.parametrize('location', ['../outside.png', '../../outside.png', 'D:/outside.png', '\\\\server\\share\\outside.png'])
def test_reference_cannot_escape_project_or_use_absolute_path(project, location):
    root, document, data = project
    Image.new('RGB', (3, 4), 'red').save(root.parent / 'outside.png')
    data['references'][0]['path'] = location
    with pytest.raises(ValueError, match='逃出|相对路径'):
        pack.save(document, data, 'TEST')


def test_formal_assets_stay_in_assets_but_candidate_can_use_pending_master(project):
    root, document, data = project
    pending = root / '候审图/master.png'
    shutil.copyfile(root / '视觉资产/master.png', pending)
    data['references'][0]['path'] = '候审图/master.png'
    with pytest.raises(ValueError, match='视觉资产'):
        pack.save(document, data, 'TEST')
    result = pack.prepare(document, '六视图', mode='candidate', references={'references': [data['references'][0]]})
    assert Path(result['inputs'][0]['path']) == pending


def test_initialize_rejects_skill_content_directory(tmp_path, monkeypatch):
    skill = tmp_path / 'skill'
    monkeypatch.setattr(pack, 'SKILL', skill)
    for root in [skill, skill / 'personal']:
        with pytest.raises(ValueError, match='技能发布目录'):
            pack.initialize_project(root)


def test_candidate_master_only_zero_reference_and_later_identity_required(project):
    _, document, data = project
    with pytest.raises(ValueError, match='尚未正式登记'):
        pack.prepare(document, '母版')
    first = pack.prepare(document, '母版', mode='candidate', asset_type='master')
    assert first['inputs'] == []
    for asset_type in [None, 'body', 'face', 'expressions', 'anchors', 'sample']:
        with pytest.raises(ValueError, match='仅首张母版'):
            pack.prepare(document, '下一张', mode='candidate', asset_type=asset_type)
    for role in ['identity_support', 'style', 'pair']:
        with pytest.raises(ValueError, match='identity|身份参考'):
            pack.prepare(document, '下一张', mode='candidate', references={'references': [ref('master', role)]})
    result = pack.prepare(document, '下一张', mode='candidate', references={'references': [data['references'][0]]})
    assert len(result['inputs']) == 1
    with pytest.raises(ValueError, match='primary_reference'):
        pack.prepare(document, '下一张', mode='candidate', references={'primary_reference': 'missing', 'references': [data['references'][0]]})


def test_random_has_four_concrete_choices_and_keeps_defaults(project):
    save(project)
    result = pack.prepare(project[1])
    choices = result['random_choices']
    assert set(choices) == {'场景', '动作', '时间', '构图'}
    assert choices['场景'] in {'书店', '河岸'} and choices['动作'] in {'阅读', '散步'}
    assert choices['时间'] in {'清晨', '傍晚'} and choices['构图'] in {'半身', '全身'}
    assert '｜' not in result['request']
    prompt = Path(result['prompt_file']).read_text(encoding='utf-8')
    assert all(value in prompt for value in ['白色衬衣', '自然妆', '黑色短发', '水彩', '右耳银色耳夹'])
    record_data = store.read(Path(result['run']) / 'run.json')
    assert record_data['random_choices'] == choices and record_data['request'] == result['request']


def test_missing_random_dimension_rejected(project):
    _, document, _ = project
    document.write_text(DOCUMENT.replace('时间：清晨｜傍晚', '时间：'), encoding='utf-8')
    with pytest.raises(ValueError, match='时间'):
        pack.prepare(document, mode='candidate', asset_type='master')


def test_outfit_and_style_override_preserve_identity_and_common_limits(project):
    save(project)
    result = pack.prepare(project[1], '在咖啡馆', style_override='真人摄影', outfit_override='黑色西装',
                          extra_refs=['pair', 'style', 'support'], aspect='1:1', size='1024x1024')
    prompt = Path(result['prompt_file']).read_text(encoding='utf-8')
    assert all(value in prompt for value in ['真人摄影', '黑色西装', '自然妆', '黑色短发', '右耳银色耳夹', '避免烟草和酒瓶', '1:1', '1024x1024'])
    assert all(value not in prompt for value in ['白色衬衣', '水彩', '纸纹', '禁止摄影质感'])
    assert {use['role'] for item in result['inputs'] for use in item['uses']} == {'identity', 'identity_support'}
    assert result['random_choices'] == {}
    assert project[1].read_text(encoding='utf-8') == DOCUMENT


def test_reference_selection_deduplication_and_invalid_id(project):
    save(project)
    result = pack.prepare(project[1], '阅读')
    assert len(result['inputs']) == 2
    assert [use['role'] for use in result['inputs'][1]['uses']] == ['style', 'pair']
    assert 'support' not in {item['id'] for item in result['inputs']}
    extra = pack.prepare(project[1], '侧脸', extra_refs=['support'])
    assert len(extra['inputs']) == 3
    with pytest.raises(ValueError, match='ID 不存在'):
        pack.prepare(project[1], '侧脸', extra_refs=['unknown'])


def test_moved_project_record_review_archive_and_independent_copy(project, tmp_path):
    root, document, data = project
    save(project)
    prepared = pack.prepare(document, '阅读')
    old_run = Path(prepared['run'])
    relative_run = old_run.relative_to(root)
    copied = tmp_path / '独立副本'
    shutil.copytree(root, copied)
    pack.save(copied / document.name, data, 'COPY UPDATE', update=True)
    assert pack.check(document)['revision'] == 1
    assert pack.check(copied / document.name)['revision'] == 2
    moved = tmp_path / '搬家 中文 space'
    shutil.move(str(root), moved)
    assert pack.check(moved / document.name)['status'] == 'PASS'
    next_run = pack.prepare(moved / document.name, '河岸散步')
    assert all(Path(item['path']).is_file() for item in next_run['inputs'])
    run = moved / relative_run
    run_data = store.read(run / 'run.json')
    assert (run / run_data['project_root']).resolve() == moved
    for item in run_data['inputs']:
        assert not Path(item['path']).is_absolute()
        assert store.digest((run / item['path']).resolve()) == item['sha256']
    record(run, moved / '视觉资产/master.png')
    approve(run)
    result = pack.archive(run)
    assert Path(result['path']).parent == moved / '定稿图'
    assert store.digest(result['path']) == store.digest(moved / '视觉资产/master.png')


def test_archive_approval_numbering_no_overwrite_and_idempotence(project):
    root, document, _ = project
    save(project)
    run = Path(pack.prepare(document, '阅读')['run'])
    source = root / '视觉资产/master.png'
    record(run, source)
    with pytest.raises(ValueError, match='明确审核通过'):
        pack.archive(run)
    approve(run)
    history = root / '定稿图/历史'
    history.mkdir()
    shutil.copyfile(source, history / '003-earlier.png')
    old_hash = store.digest(history / '003-earlier.png')
    first = pack.archive(run, 'lin-reading')
    assert Path(first['path']).name == '004-lin-reading.png'
    assert store.digest(first['path']) == store.digest(source)
    assert pack.archive(run, 'ignored-second-label')['already_archived'] is True
    assert store.digest(history / '003-earlier.png') == old_hash
    assert (run / 'original.png').exists() and source.exists()
    with pytest.raises(ValueError, match='不能覆盖'):
        record(run, source)


@pytest.mark.parametrize('change', ['source', 'target'])
def test_archive_detects_modified_bytes(project, change):
    root, document, _ = project
    save(project)
    run = Path(pack.prepare(document, '阅读')['run'])
    record(run, root / '视觉资产/master.png')
    approve(run)
    final = pack.archive(run)
    target = run / 'original.png' if change == 'source' else Path(final['path'])
    Image.new('RGB', (30, 40), 'black').save(target)
    with pytest.raises(ValueError, match='内容被修改|定稿文件被修改'):
        pack.archive(run)


@pytest.mark.parametrize('label', ['../escape', 'a/b', 'a\\b', 'trailing.', 'trailing ', 'bad:name'])
def test_archive_rejects_filename_escape(project, label):
    root, document, _ = project
    save(project)
    run = pack.prepare(document, '阅读')['run']
    record(run, root / '视觉资产/master.png')
    approve(run)
    with pytest.raises(ValueError, match='合法文件名'):
        pack.archive(run, label)


def test_archive_rejects_legacy_or_outside_run_folder(project, tmp_path):
    _, document, _ = project
    save(project)
    run = Path(pack.prepare(document, '阅读')['run'])
    data = store.read(run / 'run.json')
    data['schema_version'] = 1
    store.write(run / 'run.json', data)
    with pytest.raises(ValueError, match='v2 run'):
        pack.archive(run)
    data['schema_version'] = 2
    outside = tmp_path / 'elsewhere'
    store.write(outside / 'run.json', data)
    with pytest.raises(ValueError, match='v2 run'):
        pack.archive(outside)
