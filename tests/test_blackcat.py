"""Behavioral tests use synthetic fixtures; they do NOT certify character likeness."""
from pathlib import Path
import shutil
import sys

from PIL import Image
import pytest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'blackcat-visual/scripts'))
sys.path.insert(0, str(PROJECT / 'tools'))
import bc_store as s
import bc_runs as runs
import blackcat
import folder_picker
import package_skill

@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('BLACKCAT_CONFIG', str(tmp_path / '机器配置.json'))
    root = tmp_path / '资料库 中文 space'
    s.initialize(root)
    source = tmp_path / '参考 图片.png'
    Image.new('RGB', (512, 512), (120, 140, 160)).save(source)
    return root, source

def reference(source, role='identity'):
    return {'id': 'ref', 'path': str(source), 'role': role, 'allowed': 'synthetic test coverage only', 'forbidden': 'not a real identity or approval', 'visually_checked': True, 'coverage': [*(f'body:{x}' for x in s.BODY_VIEWS), *(f'face:{x}' for x in s.FACE_VIEWS), *(f'expression:{x}' for x in s.EXPRESSIONS)]}

def character(source, key='char-one'):
    return {'id': key, 'name': '测试主角 ' + key, 'aliases': [key + '-alias'], 'age_impression': 'adult', 'face_structure': 'test face', 'hair': 'test hair', 'body_proportions': 'adult test ratio', 'identity_constraints': 'keep identity', 'allowed_changes': 'clothing and scene', 'baseline_medium': 'original medium must not leak', 'primary_reference': 'ref', 'anchors': {'mode': 'none', 'description': '管理者明确无固定锚点（测试）'}, 'references': [reference(source)]}

def style(source, key='style-one'):
    return {'id': key, 'name': '测试风格 ' + key, 'aliases': [], 'type': 'photography' if key == 'photo' else 'comic', 'realism': 'natural', 'linework': 'soft', 'coloring': 'layered', 'lighting': 'scene-dependent', 'palette': 'neutral', 'materials': 'separate materials', 'detail_density': 'selective', 'preserve_textures': 'legitimate paper or skin', 'avoid': 'UNIQUE-' + key, 'default_aspect': '2:3', 'default_size': '1024x1536', 'references': [reference(source, 'style')]}

def populate(root, source):
    for key in ['char-one', 'char-two']:
        s.save_profile(root, 'character', character(source, key), 'SYNTHETIC TEST APPROVAL')
    for key in ['comic', 'photo']:
        s.save_profile(root, 'style', style(source, key), 'SYNTHETIC TEST APPROVAL', folder=root.parent / ('风格 ' + key))

def test_blank_install_and_missing_library(setup, tmp_path):
    root, _ = setup
    assert s.library(root)['characters'] == {}
    assert s.root_path() == root
    with pytest.raises(ValueError): s.root_path(tmp_path / 'missing')

def test_missing_view_prevents_registration(setup):
    root, source = setup
    data = character(source)
    data['references'][0]['coverage'].remove('body:back')
    with pytest.raises(ValueError, match='body:back'): s.save_profile(root, 'character', data, 'TEST')
    assert not s.library(root)['characters']

def test_unchecked_or_missing_anchors_rejected(setup):
    root, source = setup
    data = character(source)
    data['references'][0]['visually_checked'] = False
    with pytest.raises(ValueError): s.save_profile(root, 'character', data, 'TEST')
    data['references'][0]['visually_checked'] = True
    data['anchors'] = {'mode': 'defined', 'description': 'star', 'placement': 'neck', 'occlusion_rules': 'may hide'}
    with pytest.raises(ValueError, match='锚点'): s.save_profile(root, 'character', data, 'TEST')

def test_two_characters_styles_and_pair_gate(setup):
    root, source = setup; populate(root, source)
    for c in ['char-one', 'char-two']:
        for st in ['comic', 'photo']:
            with pytest.raises(ValueError, match='组合'): s.select(root, c, st)
            assert s.select(root, c, st, 'sample')['pair'] is None
            s.save_pair(root, c, st, source, 'test style adaptation', 'SYNTHETIC TEST')
            assert s.select(root, c, st)['pair']['character_id'] == c

def test_style_switch_clears_previous_constraints(setup):
    root, source = setup; populate(root, source)
    one = runs.prepare(root, 'char-one', 'comic', 'same scene', mode='sample')
    two = runs.prepare(root, 'char-one', 'photo', 'same scene', mode='sample')
    prompt = Path(two['prompt_file']).read_text(encoding='utf-8')
    assert 'UNIQUE-photo' in prompt and 'UNIQUE-comic' not in prompt
    assert 'original medium must not leak' not in prompt
    assert one['run'] != two['run']

def test_version_kept_and_pair_invalidated(setup):
    root, source = setup; populate(root, source)
    s.save_pair(root, 'char-one', 'comic', source, 'test', 'TEST')
    old, folder = s.load_profile(root, 'character', 'char-one')
    data = character(source); data['hair'] = 'changed with explicit approval'
    s.save_profile(root, 'character', data, 'TEST CHANGE', update=True)
    assert s.read(folder / 'profiles/v0001.json')['hair'] == old['hair']
    assert s.select(root, 'char-one', 'comic', 'sample')['pair'] is None

def test_reference_hash_change_is_detected(setup):
    root, source = setup
    s.save_profile(root, 'character', character(source), 'TEST')
    data, folder = s.load_profile(root, 'character', 'char-one')
    (folder / data['references'][0]['path']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='参考'): s.load_profile(root, 'character', 'char-one')

def test_style_relocation_and_cancel(setup, monkeypatch):
    root, source = setup; populate(root, source)
    _, old = s.load_profile(root, 'style', 'comic')
    new = old.parent / '新位置'
    shutil.move(str(old), str(new))
    with pytest.raises(ValueError, match='路径失效'): s.load_profile(root, 'style', 'comic')
    s.rebind(root, 'style', 'comic', new, 'TEST USER RELOCATION')
    assert s.load_profile(root, 'style', 'comic')[1] == new
    draft = root / 'new-style.json'; s.write(draft, style(source, 'cancelled'))
    monkeypatch.setattr(blackcat, 'pick', lambda *a: {'status': 'cancelled', 'path': None})
    monkeypatch.setattr(sys, 'argv', ['blackcat.py', 'save-style', '--file', str(draft), '--approval', 'TEST'])
    assert blackcat.main()['status'] == 'cancelled'
    assert 'cancelled' not in s.library(root)['styles']

def test_style_inside_library_keeps_materials_in_requested_project(setup):
    root, source = setup
    folder = root / '风格库' / '日系 治愈动漫'
    s.save_profile(root, 'style', style(source), 'SYNTHETIC TEST', folder=folder)
    profile, actual = s.load_profile(root, 'style', 'style-one')
    assert actual == folder
    assert s.digest(profile['references'][0]['actual_path']) == s.digest(source)
    with pytest.raises(ValueError, match='重叠'):
        s.save_profile(root, 'style', style(source, 'nested'), 'TEST', folder=folder / 'nested')
    with pytest.raises(ValueError, match='重叠'):
        s.save_profile(root, 'style', style(source, 'parent'), 'TEST', folder=folder.parent)

@pytest.mark.parametrize('location', ['.', '..', 'characters', 'characters/future-cat', 'drafts/style', 'runtime/style', 'cache/style', 'tmp/style'])
def test_style_rejects_library_and_reserved_locations(setup, location):
    root, source = setup
    with pytest.raises(ValueError, match='风格目录'):
        s.save_profile(root, 'style', style(source), 'TEST', folder=root / location)
    assert not s.library(root)['styles']

def test_archive_preserves_bytes_and_wont_overwrite(setup):
    root, source = setup; populate(root, source)
    run = runs.prepare(root, 'char-one', 'photo', 'same scene', 'sample')['run']
    metadata = {'tool': 'synthetic-test', 'actual_submitted_prompt': 'TEST ONLY', 'reference_delivery': {'verified': False, 'evidence': 'no image tool invoked'}, 'visible_parameters': '未暴露', 'request_count': 0, 'success_count': 0}
    result = runs.record(run, source, metadata)
    assert s.digest(result['original']) == s.digest(source)
    assert set(result) == {'run', 'original'}
    assert 'ripple' not in s.read(Path(run) / 'run.json')
    with pytest.raises(ValueError): runs.record(run, source, metadata)
    assert s.read(Path(run) / 'run.json')['approval_status'] == '待审核'

def test_edit_target_distinct_from_identity(setup):
    root, source = setup; populate(root, source)
    run = runs.prepare(root, 'char-one', 'photo', 'change clothing only', 'sample')['run']
    result = runs.add_edit_target(run, source)
    assert result['inputs'][-1]['uses'][0]['role'] == 'edit_target'
    assert '唯一编辑目标' in Path(result['prompt_file']).read_text(encoding='utf-8')

def test_no_numeric_pass_without_inspection(setup):
    root, source = setup; populate(root, source)
    run = runs.prepare(root, 'char-one', 'comic', 'scene', 'sample')['run']
    with pytest.raises(ValueError): runs.review(run, status='可用')
    assert runs.review(run)['approval_status'] == '待审核'

def test_macos_picker_selected_cancelled_and_unavailable(tmp_path, monkeypatch):
    class Reply:
        returncode = 0
        stdout = str(tmp_path) + '\n'
    monkeypatch.setattr(folder_picker.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(folder_picker.subprocess, 'run', lambda *a, **k: Reply())
    assert folder_picker.pick()['status'] == 'selected'
    Reply.stdout = '__BLACKCAT_CANCELLED__\n'
    assert folder_picker.pick()['status'] == 'cancelled'
    Reply.returncode = 1
    assert folder_picker.pick()['status'] == 'unavailable'

def test_package_is_clean_allowlist(tmp_path):
    import zipfile
    result = package_skill.package(tmp_path / 'blackcat.zip')
    with zipfile.ZipFile(tmp_path / 'blackcat.zip') as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert not any(x.endswith(('.png', '.jpg', '.pyc')) or '/.runtime/' in x or '/tests/' in x for x in names)
        assert not any('/vendor/' in x or x.endswith('ripple.py') for x in names)
        assert len(names) == len(result['files'])
        assert archive.read('blackcat-visual/LICENSE') == (PROJECT / 'LICENSE').read_bytes()


def test_package_rejects_divergent_authorization_notices(tmp_path, monkeypatch):
    skill = tmp_path / 'blackcat-visual'
    skill.mkdir()
    (tmp_path / 'LICENSE').write_text('Repository notice', encoding='utf-8')
    (skill / 'LICENSE').write_text('Different packaged notice', encoding='utf-8')
    monkeypatch.setattr(package_skill, 'ROOT', tmp_path)
    monkeypatch.setattr(package_skill, 'SKILL', skill)
    destination = tmp_path / 'dist' / 'blackcat.zip'
    with pytest.raises(ValueError, match='authorization notices must match'):
        package_skill.package(destination)
    assert not destination.exists()


def archived_run(root, source):
    populate(root, source)
    run = runs.prepare(root, 'char-one', 'comic', 'test request', 'sample')['run']
    metadata = {'tool': 'synthetic-test', 'actual_submitted_prompt': 'TEST ONLY',
                'reference_delivery': {'verified': False, 'evidence': 'no image tool invoked'},
                'visible_parameters': '未暴露', 'request_count': 0, 'success_count': 0}
    runs.record(run, source, metadata)
    return Path(run), metadata


def test_review_requires_original_even_with_approval(setup):
    root, source = setup; populate(root, source)
    run = Path(runs.prepare(root, 'char-one', 'comic', 'scene', 'sample')['run'])
    before = (run / 'run.json').read_bytes()
    with pytest.raises(ValueError, match='尚未归档'):
        runs.review(run, status='可用', approval='SYNTHETIC APPROVAL')
    assert (run / 'run.json').read_bytes() == before
    assert not (run / '.blackcat-write.lock').exists()


def test_review_preserves_checks_history_and_independent_approval(setup):
    root, source = setup
    run, _ = archived_run(root, source)
    first = {key: {'status': '待修', 'note': 'synthetic finding'} for key in runs.CHECKS}
    second = {key: {'status': '无法判断', 'note': 'synthetic occlusion'} for key in runs.CHECKS}
    runs.review(run, checks=first)
    runs.review(run, checks=second)
    runs.review(run, status='可用', approval='SYNTHETIC ACCEPTANCE WITH UNCERTAINTY')
    data = s.read(run / 'run.json')
    assert [row['checks'] for row in data['check_history']] == [first, second]
    assert data['checks'] == second and data['approval_status'] == '可用'
    before = (run / 'run.json').read_bytes()
    with pytest.raises(ValueError): runs.review(run, status='弃用', approval='   ')
    assert (run / 'run.json').read_bytes() == before


@pytest.mark.parametrize('damage', ['missing', 'modified'])
def test_review_blocks_damaged_original(setup, damage):
    root, source = setup
    run, _ = archived_run(root, source)
    original = run / s.read(run / 'run.json')['original']['path']
    if damage == 'missing': original.unlink()
    else: original.write_bytes(b'changed synthetic fixture')
    with pytest.raises(ValueError, match='原图缺失或内容被修改'):
        runs.review(run, status='可用', approval='SYNTHETIC TEST')
    assert s.read(run / 'run.json')['approval_status'] == '待审核'


def test_duplicate_edit_target_rejected_without_changing_manifest(setup):
    root, source = setup; populate(root, source)
    run = Path(runs.prepare(root, 'char-one', 'comic', 'edit', 'sample')['run'])
    runs.add_edit_target(run, source)
    before = {name: (run / name).read_bytes() for name in ['prompt.txt', 'run.json', 'inputs.json']}
    with pytest.raises(ValueError, match='唯一编辑目标'): runs.add_edit_target(run, source)
    assert all((run / name).read_bytes() == content for name, content in before.items())


def test_run_mutations_respect_existing_lock(setup):
    root, source = setup
    run, metadata = archived_run(root, source)
    lock = run / '.blackcat-write.lock'
    before = (run / 'run.json').read_bytes()
    with s.locked(run):
        for operation in [lambda: runs.record(run, source, metadata),
                          lambda: runs.add_edit_target(run, source),
                          lambda: runs.review(run, status='可用', approval='TEST')]:
            with pytest.raises(ValueError, match='正在写入'): operation()
            assert lock.exists()
    assert (run / 'run.json').read_bytes() == before
    assert not lock.exists()


@pytest.mark.parametrize('counts', [(-1, 0), (1, 2), (True, 1), (1, '1')])
def test_invalid_generation_counts_do_not_archive(setup, counts):
    root, source = setup; populate(root, source)
    run = Path(runs.prepare(root, 'char-one', 'comic', 'scene', 'sample')['run'])
    metadata = {'tool': 'synthetic-test', 'actual_submitted_prompt': 'TEST',
                'reference_delivery': {'verified': False, 'evidence': 'not generated'},
                'visible_parameters': '未暴露', 'request_count': counts[0], 'success_count': counts[1]}
    with pytest.raises(ValueError, match='次数'): runs.record(run, source, metadata)
    assert not list(run.glob('original*'))
    assert s.read(run / 'run.json')['original'] is None


def test_primary_identity_role_and_coverage_types(setup):
    root, source = setup
    data = character(source)
    data['references'][0]['role'] = 'identity_support'
    with pytest.raises(ValueError, match='身份主参考'): s.save_profile(root, 'character', data, 'TEST')
    data = character(source)
    data['references'][0]['coverage'] = 'body:front'
    with pytest.raises(ValueError, match='coverage'): s.save_profile(root, 'character', data, 'TEST')
    assert s.library(root)['characters'] == {}
