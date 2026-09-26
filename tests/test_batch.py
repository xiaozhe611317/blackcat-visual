"""Synthetic contract tests, not evidence of character likeness or live model support."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

from PIL import Image
import pytest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'blackcat-visual/scripts'))
import bc_batch as batch
import bc_pack as pack
import bc_runs as runs
import bc_store as store
from tests.test_pack import DOCUMENT


@pytest.fixture
def cast(tmp_path):
    documents = []
    coverage = ([f'body:{x}' for x in store.BODY_VIEWS] + [f'face:{x}' for x in store.FACE_VIEWS]
                + [f'expression:{x}' for x in store.EXPRESSIONS] + ['anchor:details'])
    for number in range(12):
        key = f'person-{number + 1:02d}'
        root = tmp_path / 'characters' / key
        pack.initialize_project(root)
        document = root / '角色生图.md'
        document.write_text(DOCUMENT.replace('Lin', key), encoding='utf-8')
        for idx, name in enumerate(['master', 'support', 'style']):
            Image.new('RGB', (30, 40), (number * 17, idx * 70, 120)).save(root / '视觉资产' / f'{name}.png')
        refs = [{'id': name, 'path': f'视觉资产/{name}.png', 'role': role,
                 'visually_checked': True, 'coverage': coverage if name == 'support' else []}
                for name, role in [('master', 'identity'), ('support', 'identity_support'), ('style', 'style')]]
        refs.append({**refs[-1], 'id': 'pair', 'role': 'pair'})
        pack.save(document, {'id': key, 'name': key, 'primary_reference': 'master', 'anchors_mode': 'defined', 'references': refs},
                  'SYNTHETIC FIXTURE, NOT USER CHARACTER APPROVAL')
        documents.append(document)
    return documents


def plan_for(documents, count=2, **extra):
    characters = [{'id': f'person-{n + 1:02d}', 'document': str(doc)} for n, doc in enumerate(documents)]
    items = [{'id': f'{c["id"]}-{number + 1:02d}', 'cast': [{'character': c['id']}], 'request': '河岸散步'}
             for c in characters for number in range(count)]
    return {'id': 'fixture-batch', 'characters': characters, 'items': items, **extra}


def start(tmp_path, plan, name='batch'):
    path = tmp_path / (name + '-plan.json')
    store.write(path, plan)
    root = tmp_path / name
    batch.initialize(path, root)
    return root


def metadata():
    return {'tool': 'synthetic-fixture-NOT-LIVE', 'actual_submitted_prompt': 'Fixture only; no live image tool.',
            'reference_delivery': {'verified': True, 'evidence': 'Simulated receipt, not a real tool invocation'},
            'visible_parameters': {'model': 'unexposed'}, 'request_count': 1, 'success_count': 1}


def checks(ids):
    def checked():
        return {'status': '通过', 'note': 'SYNTHETIC assertion, not a visual judgment'}
    return {'global': {key: checked() for key in runs.CHECKS},
            'characters': {key: {name: checked() for name in ['identity', 'anchors', 'placement']} for key in ids},
            'continuity': checked()}


def complete(root, item, source, cast_ids=None):
    result = batch.prepare(root, item)
    batch.dispatch(root, item, 'SIMULATED submission')
    batch.record(root, item, source, metadata())
    batch.review(root, item, checks(cast_ids or ['person-01']))
    return result


def scene(tmp_path):
    data = {'id': 'cafe', 'revision': 1, 'name': '咖啡馆', 'location': '临河咖啡馆',
            'layout': '北墙窗，中央长桌，东门；方向是场景坐标而非屏幕左右。',
            'key_objects': ['中央橡木桌', '北窗左侧绿灯'], 'lighting': '下午，日光来自北窗',
            'continuity': '保留结构、物件位置及时间光照；只允许换机位。', 'references': []}
    store.write(tmp_path / 'scene.json', data)
    return tmp_path / 'scene.json'


def group_plan(cast, number, scene_file=None):
    plan = plan_for(cast[:number], 1, common={'style_override': '统一摄影，保留自然皮肤', 'aspect': '16:9', 'size': '环境默认'})
    plan['items'] = [{'id': 'group', 'cast': [{'character': c['id'], 'position': f'座位 {i + 1}',
                         'action': '交谈', 'visibility': '脸清晰可辨，中近景；非必见饰物允许遮挡'}
                        for i, c in enumerate(plan['characters'])],
                      'shot': {'camera': '南侧看向北窗', 'framing': '横向中景，所有人脸可辨'}, 'request': '聚会'}]
    if scene_file:
        plan['scene'] = str(scene_file)
    return plan


def test_twelve_characters_twenty_four_independent_tasks(cast, tmp_path):
    root = start(tmp_path, plan_for(cast))
    assert batch.status(root)['counts'] == {'ready': 24}
    for n, document in enumerate(cast):
        for image_number in [1, 2]:
            key = f'person-{n + 1:02d}-{image_number:02d}'
            complete(root, key, document.parent / '视觉资产/master.png', [f'person-{n + 1:02d}'])
    result = batch.status(root)
    assert result['total'] == 24 and result['counts'] == {'reviewed': 24}
    assert result['next'] is None
    assert not (root / '定稿图').exists()
    assert Path(batch.report(root)['report']).is_file()


@pytest.mark.parametrize('number', [2, 5, 8])
def test_group_owner_mapping_and_per_person_checks(cast, tmp_path, number):
    root = start(tmp_path, group_plan(cast, number, scene(tmp_path)))
    prepared = batch.prepare(root, 'group')
    assert len(prepared['inputs']) == number  # Old style/pair images are all excluded.
    assert len({ref['owner'] for ref in prepared['inputs']}) == number
    assert [ref['number'] for ref in prepared['inputs']] == list(range(1, number + 1))
    prompt = Path(prepared['prompt_file']).read_text(encoding='utf-8')
    assert '水彩' not in prompt and '禁止摄影质感' not in prompt
    assert '北墙窗' in prompt and '恰好 ' + str(number) in prompt
    ids = [f'person-{n + 1:02d}' for n in range(number)]
    batch.dispatch(root, 'group', 'SIMULATED'); batch.record(root, 'group', cast[0].parent / '视觉资产/master.png', metadata())
    with pytest.raises(ValueError, match='全部角色'):
        batch.review(root, 'group', checks(ids[:1]))
    assert batch.review(root, 'group', checks(ids))['state'] == 'reviewed'


def test_missing_character_blocks_only_its_tasks(cast, tmp_path):
    plan = plan_for(cast)
    plan['characters'][2]['document'] = str(tmp_path / 'missing.md')
    root = start(tmp_path, plan)
    assert batch.status(root)['counts'] == {'ready': 22, 'blocked': 2}
    batch.prepare(root, 'person-01-01')
    with pytest.raises(ValueError, match='blocked'):
        batch.prepare(root, 'person-03-01')


def test_frozen_inputs_survive_source_changes_and_batch_move(cast, tmp_path):
    root = start(tmp_path, plan_for(cast[:1]))
    original_sha = store.digest(cast[0].parent / '视觉资产/master.png')
    cast[0].write_text('the original project has changed', encoding='utf-8')
    Image.new('RGB', (50, 50), 'black').save(cast[0].parent / '视觉资产/master.png')
    prepared = batch.prepare(root, 'person-01-01')
    assert prepared['inputs'][0]['sha256'] == original_sha
    moved = tmp_path / 'moved 中文 space'
    assert root.is_relative_to(tmp_path) and moved.is_relative_to(tmp_path)
    shutil.move(str(root), moved)
    again = batch.prepare(moved, 'person-01-01')
    assert again['already_prepared'] and all(Path(ref['path']).is_file() for ref in again['inputs'])
    assert store.digest(again['inputs'][0]['path']) == original_sha


def test_shared_and_per_item_overrides_do_not_change_documents(cast, tmp_path):
    original = cast[0].read_bytes()
    plan = plan_for(cast[:1], common={'style_override': '版画', 'outfit_override': '红色外套', 'request': '雨天'})
    plan['items'][1]['style_override'] = '摄影'
    plan['items'][1]['cast'][0]['outfit_override'] = '黑色西装'
    root = start(tmp_path, plan)
    first = Path(batch.prepare(root, 'person-01-01')['prompt_file']).read_text(encoding='utf-8')
    second = Path(batch.prepare(root, 'person-01-02')['prompt_file']).read_text(encoding='utf-8')
    assert '红色外套' in first and '版画' in first
    assert '黑色西装' in second and '红色外套' not in second and '版画' not in second
    assert '雨天' in first and '河岸散步' in first
    assert cast[0].read_bytes() == original


def test_interruption_does_not_resubmit_and_other_tasks_continue(cast, tmp_path):
    root = start(tmp_path, plan_for(cast[:1]))
    batch.prepare(root, 'person-01-01'); batch.dispatch(root, 'person-01-01', 'SIMULATED invocation')
    with pytest.raises(ValueError, match='不可启动'):
        batch.prepare(root, 'person-01-01')
    assert batch.status(root)['next'] == 'person-01-02'
    batch.outcome(root, 'person-01-01', 'unknown', 'connection lost; tool may still finish')
    with pytest.raises(ValueError, match='未知需先核对'):
        batch.retry(root, 'person-01-01', 'TEST', 'repair')
    with pytest.raises(ValueError, match='先核实'):
        batch.outcome(root, 'person-01-01', 'failed', 'not enough evidence')
    batch.record(root, 'person-01-01', cast[0].parent / '视觉资产/master.png', metadata())
    assert batch.status(root)['counts'] == {'generated': 1, 'ready': 1}


def test_failure_requires_explicit_retry_and_preserves_attempts(cast, tmp_path):
    root = start(tmp_path, plan_for(cast[:1]))
    batch.prepare(root, 'person-01-01'); batch.dispatch(root, 'person-01-01', 'SIMULATED')
    batch.outcome(root, 'person-01-01', 'failed', 'explicit error; no output')
    with pytest.raises(ValueError): batch.prepare(root, 'person-01-01')
    with pytest.raises(ValueError): batch.retry(root, 'person-01-01', '', 'retry')
    batch.retry(root, 'person-01-01', 'USER AUTHORIZED ONE EXTRA ATTEMPT', 'same original requirements')
    prepared = batch.prepare(root, 'person-01-01')
    assert Path(prepared['run']).name.endswith('a0002')
    assert (root / '候审图/批次/person-01-01-a0001/run.json').is_file()


def test_handoff_is_not_generation(cast, tmp_path):
    root = start(tmp_path, plan_for(cast[:1]))
    batch.prepare(root, 'person-01-01'); batch.dispatch(root, 'person-01-01', 'environment lacks image tool', handoff=True)
    assert batch.status(root)['counts'] == {'handoff': 1, 'ready': 1}
    unverified = metadata(); unverified['reference_delivery']['verified'] = False
    with pytest.raises(ValueError, match='传图证据'):
        batch.record(root, 'person-01-01', cast[0].parent / '视觉资产/master.png', unverified)
    with pytest.raises(ValueError): batch.prepare(root, 'person-01-01')


@pytest.mark.parametrize('field', ['identity', 'placement', 'required_anchor', 'occluded_anchor', 'continuity'])
def test_context_sensitive_qa(cast, tmp_path, field):
    plan = group_plan(cast, 5, scene(tmp_path))
    if field == 'required_anchor': plan['items'][0]['cast'][0]['required_anchors'] = ['右耳夹']
    root = start(tmp_path, plan)
    complete(root, 'group', cast[0].parent / '视觉资产/master.png', [f'person-{i + 1:02d}' for i in range(5)])
    qa = checks([f'person-{i + 1:02d}' for i in range(5)])
    value = {'status': '无法判断', 'note': 'SYNTHETIC simulated occlusion/visibility limitation'}
    if field == 'continuity': qa['continuity'] = value
    else: qa['characters']['person-01']['anchors' if 'anchor' in field else field] = value
    result = batch.review(root, 'group', qa)
    assert (result['state'] == 'reviewed') == (field == 'occluded_anchor')


def test_repair_selects_explicit_earlier_output_and_keeps_original(cast, tmp_path):
    root = start(tmp_path, plan_for(cast[:1]))
    first = complete(root, 'person-01-01', cast[0].parent / '视觉资产/master.png')
    sha = store.digest(Path(first['run']) / 'original.png')
    with pytest.raises(ValueError, match='明确 source_attempt'):
        batch.retry(root, 'person-01-01', 'APPROVED', '修手', base='attempt')
    batch.retry(root, 'person-01-01', 'APPROVED', '只修手，保留人物身份', base='attempt', source_attempt=1)
    with pytest.raises(ValueError): batch.approve(root, 'person-01-01', 'cannot approve queued retry')
    second = batch.prepare(root, 'person-01-01')
    assert second['inputs'][-1]['uses'][0]['role'] == 'edit_target'
    assert store.digest(second['inputs'][-1]['path']) == sha
    assert store.digest(Path(first['run']) / 'original.png') == sha


def test_approval_gate_and_idempotent_archive(cast, tmp_path):
    root = start(tmp_path, plan_for(cast[:1]))
    complete(root, 'person-01-01', cast[0].parent / '视觉资产/master.png')
    with pytest.raises(ValueError): batch.archive(root, 'person-01-01')
    batch.approve(root, 'person-01-01', 'SYNTHETIC USER ACCEPTANCE')
    first = batch.archive(root, 'person-01-01')
    assert Path(first['path']).is_file()
    assert batch.archive(root, 'person-01-01')['already_archived']


def test_candidate_master_dependency_is_not_formal_registration(cast, tmp_path):
    plan = plan_for(cast[:1])
    plan['characters'][0]['mode'] = 'candidate'
    plan['items'][0].update(id='master', asset_type='master', request='清晰中性身份母版')
    plan['items'][1].update(id='body', asset_type='body', master_from='master', request='同一角色六角度全身图板')
    root = start(tmp_path, plan)
    assert batch.status(root)['counts'] == {'ready': 1, 'waiting_dependency': 1}
    first = complete(root, 'master', cast[0].parent / '视觉资产/master.png')
    assert first['inputs'] == []
    with pytest.raises(ValueError): batch.prepare(root, 'body')
    batch.approve(root, 'master', 'SYNTHETIC AUTHORIZATION TO CONTINUE; NOT CHARACTER APPROVAL', purpose='continuation')
    derived = batch.prepare(root, 'body')
    assert len(derived['inputs']) == 1
    assert store.digest(derived['inputs'][0]['path']) == store.digest(Path(first['run']) / 'original.png')
    assert store.read(Path(first['run']) / 'run.json')['approval_status'] == '待审核'
    assert not (root / '过程记录/角色登记').exists()


def test_preflight_failure_is_local_and_visible(cast, tmp_path):
    plan = plan_for(cast[:1])
    plan['items'][0]['cast'][0]['coverage'] = ['face:not-a-view']
    root = start(tmp_path, plan)
    with pytest.raises(ValueError, match='必要参考覆盖缺失'): batch.prepare(root, 'person-01-01')
    summary = batch.status(root)
    assert summary['counts'] == {'blocked': 1, 'ready': 1}
    assert summary['items'][0]['reason']
    assert summary['next'] == 'person-01-02'


def test_automatic_support_selection_is_minimal(cast, tmp_path):
    plan = plan_for(cast[:1])
    plan['items'][0]['cast'][0]['coverage'] = ['face:left_side', 'anchor:details']
    root = start(tmp_path, plan)
    prepared = batch.prepare(root, 'person-01-01')
    assert len(prepared['inputs']) == 3  # master + support + one shared style/pair file
    assert len(prepared['inputs'][-1]['uses']) == 2


@pytest.mark.parametrize('change', ['cycle', 'duplicate', 'foreign_master', 'missing_owner'])
def test_invalid_plan_rejected_before_creating_batch(cast, tmp_path, change):
    plan = plan_for(cast[:2], 1)
    if change == 'cycle':
        plan['items'][0]['depends_on'] = ['person-02-01']; plan['items'][1]['depends_on'] = ['person-01-01']
    if change == 'duplicate': plan['items'][1]['id'] = plan['items'][0]['id']
    if change == 'foreign_master':
        plan['items'][0]['asset_type'] = 'master'; plan['items'][1].update(asset_type='body', master_from=plan['items'][0]['id'])
    if change == 'missing_owner': plan['items'][0]['cast'][0]['character'] = 'missing'
    store.write(tmp_path / 'bad.json', plan)
    with pytest.raises(ValueError): batch.initialize(tmp_path / 'bad.json', tmp_path / 'bad-batch')
    assert not (tmp_path / 'bad-batch').exists()


def test_tampering_prevents_submission(cast, tmp_path):
    root = start(tmp_path, plan_for(cast[:1]))
    prepared = batch.prepare(root, 'person-01-01')
    Path(prepared['prompt_file']).write_text('changed prompt', encoding='utf-8')
    with pytest.raises(ValueError, match='提示词被修改'): batch.dispatch(root, 'person-01-01', 'SIMULATED')
    assert batch.status(root)['counts'] == {'blocked': 1, 'ready': 1}


def test_catalog_has_thumbnails_and_reports_missing(cast, tmp_path):
    result = batch.catalog([*cast[:2], tmp_path / 'missing.md'], tmp_path / 'catalog')
    assert [x['readiness'] for x in result['characters']] == ['可用', '可用', '缺项']
    assert Path(result['overview']).is_file()
    with Image.open(tmp_path / 'catalog/001.png') as image: assert image.size == (30, 40)


def test_scene_reference_cannot_escape_its_directory(tmp_path):
    scene_file = scene(tmp_path)
    data = store.read(scene_file)
    data['references'] = [{'id': 'bad', 'path': '../outside.png', 'allowed': 'layout', 'forbidden': 'people', 'visually_checked': True}]
    store.write(scene_file, data)
    with pytest.raises(ValueError, match='逃出'): batch.scene_check(scene_file)


def test_no_implicit_parent_version_change(cast, tmp_path):
    plan = plan_for(cast[:1])
    plan['characters'][0]['mode'] = 'candidate'
    plan['items'][0].update(id='master', asset_type='master')
    plan['items'][1].update(id='body', asset_type='body', master_from='master')
    root = start(tmp_path, plan)
    first = complete(root, 'master', cast[0].parent / '视觉资产/master.png')
    batch.approve(root, 'master', 'TEST CONTINUATION', purpose='continuation')
    batch.retry(root, 'master', 'TEST REGENERATE', 'new master trial')
    complete(root, 'master', cast[0].parent / '视觉资产/support.png')
    batch.approve(root, 'master', 'TEST CONTINUATION 2', purpose='continuation')
    derived = batch.prepare(root, 'body')
    assert store.digest(derived['inputs'][0]['path']) == store.digest(Path(first['run']) / 'original.png')


@pytest.mark.parametrize('not_submitted', [True, False])
def test_orphan_recovery_never_resubmits_without_evidence(cast, tmp_path, not_submitted):
    root = start(tmp_path, plan_for(cast[:1]))
    batch.prepare(root, 'person-01-01')
    data = store.read(root / 'batch.json')
    data['items']['person-01-01']['attempts'] = []
    data['items']['person-01-01']['state'] = 'queued'
    store.write(root / 'batch.json', data)  # Simulate interrupted index write, preserving the full run.
    assert batch.status(root)['counts'] == {'orphaned': 1, 'ready': 1}
    assert batch.status(root)['next'] == 'person-01-02'
    result = batch.recover(root, 'person-01-01', 'TEST verified local interruption', not_submitted)
    assert result['state'] == ('prepared' if not_submitted else 'unknown')


def test_successful_record_survives_stale_batch_index(cast, tmp_path):
    root = start(tmp_path, plan_for(cast[:1]))
    batch.prepare(root, 'person-01-01'); batch.dispatch(root, 'person-01-01', 'TEST')
    old_index = store.read(root / 'batch.json')
    batch.record(root, 'person-01-01', cast[0].parent / '视觉资产/master.png', metadata())
    store.write(root / 'batch.json', old_index)
    assert batch.status(root)['items'][0]['state'] == 'generated'
    with pytest.raises(ValueError): batch.dispatch(root, 'person-01-01', 'would duplicate')


def test_review_invalidates_previous_approval(cast, tmp_path):
    root = start(tmp_path, plan_for(cast[:1]))
    complete(root, 'person-01-01', cast[0].parent / '视觉资产/master.png')
    batch.approve(root, 'person-01-01', 'SYNTHETIC ACCEPTANCE')
    qa = checks(['person-01'])
    qa['characters']['person-01']['anchors'] = {'status': '待修', 'note': 'TEST newly noticed wrong side'}
    batch.review(root, 'person-01-01', qa)
    with pytest.raises(ValueError): batch.archive(root, 'person-01-01')
    with pytest.raises(ValueError): batch.approve(root, 'person-01-01', 'not explicit about issues')
    batch.approve(root, 'person-01-01', 'TEST user explicitly accepts the noted issue', accept_issues=True)
    assert batch.status(root)['items'][0]['state'] == 'approved'


def test_failure_call_counts_do_not_count_prepare_as_generation(cast, tmp_path):
    root = start(tmp_path, plan_for(cast[:1]))
    batch.prepare(root, 'person-01-01')
    assert batch.status(root)['calls']['confirmed_requests'] == 0
    batch.dispatch(root, 'person-01-01', 'SIMULATED submission plan')
    assert batch.status(root)['calls']['confirmed_requests'] == 0
    batch.outcome(root, 'person-01-01', 'failed', 'TEST API error confirms one call', request_count=1)
    assert batch.status(root)['calls']['confirmed_requests'] == 1
    assert batch.status(root)['calls']['confirmed_successes'] == 0


def test_group_without_unified_style_blocks_only_that_task(cast, tmp_path):
    plan = group_plan(cast, 5)
    plan.pop('common')
    root = start(tmp_path, plan)
    with pytest.raises(ValueError, match='统一'): batch.prepare(root, 'group')
    assert batch.status(root)['counts'] == {'blocked': 1}


def test_scene_ref_is_distinct_from_character_owner(cast, tmp_path):
    scene_file = scene(tmp_path)
    Image.new('RGB', (60, 40), 'yellow').save(tmp_path / 'scene.png')
    data = store.read(scene_file)
    data['references'] = [{'id': 'room', 'path': 'scene.png', 'allowed': '地点、布局与关键物件',
                           'forbidden': '不能引入参考中的人物', 'visually_checked': True}]
    store.write(scene_file, data)
    root = start(tmp_path, group_plan(cast, 5, scene_file))
    result = batch.prepare(root, 'group')
    assert len(result['inputs']) == 6
    assert result['inputs'][-1]['owner'] == 'scene:cafe'
    assert result['inputs'][-1]['uses'][0]['role'] == 'scene'
