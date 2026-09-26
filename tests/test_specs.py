"""Synthetic specs tests. These never certify a real provider or visual likeness."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

from tests.test_batch import cast, plan_for, start, checks, metadata, group_plan
from tests.test_pack import project, save
import bc_specs as specs
import bc_pack as pack
import bc_batch as batch
import bc_runs as runs
import bc_store as store


def card(scope='single', **changes):
    return {'common': {'purpose': 'synthetic', 'aspect': '2:3', 'pixels': [30, 45],
                       'quality': 'standard', 'format': 'png', 'background': 'scene',
                       'framing': '全身', 'safe_area': '保头脚', 'identity_control': 'off',
                       'extra_parameters': {}, **changes},
            'overrides': {}, 'confirmation': {'scope': scope, 'quality_confirmed': True,
                                               'statement': 'SYNTHETIC current-scope selection'}}


def caps():
    return {'tool': 'synthetic-fixture-NOT-LIVE', 'evidence': 'Synthetic schema, not live support',
            'parameters': {'aspect': {'type': 'string', 'enum': ['2:3', '1:1', '16:9']},
                           'width': {'type': 'integer', 'min': 1, 'max': 10000},
                           'height': {'type': 'integer', 'min': 1, 'max': 10000},
                           'quality': {'type': 'string', 'enum': ['low', 'medium', 'high']},
                           'format': {'type': 'string', 'enum': ['png', 'jpeg', 'webp']},
                           'background': {'type': 'string', 'enum': ['transparent']}},
            'mappings': {'aspect': {'values': {x: {'aspect': x} for x in ['2:3', '1:1', '16:9']}},
                         'pixels': {'values': {'30x45': {'width': 30, 'height': 45},
                                               '32x32': {'width': 32, 'height': 32}}},
                         'quality': {'values': {a: {'quality': b} for a, b in [('preview', 'low'), ('standard', 'medium'), ('fine', 'high')]}},
                         'format': {'values': {x: {'format': x} for x in ['png', 'jpeg', 'webp']}},
                         'background': {'values': {'transparent': {'background': 'transparent'}}}},
            'references': {'supported': True, 'max_images': 20},
            'identity_binding': {'mode': 'unknown'}}


def new_run(project, chosen=None):
    save(project)
    return Path(pack.prepare(project[1], '河岸', image_specs=chosen or card())['run'])


def actual(folder, params=None):
    result = metadata()
    if params is not None:
        result['applied_parameters'] = params
    return result


@pytest.mark.parametrize('change', [
    {'quality': ''}, {'quality': 'auto'}, {'pixels': [1024, 1024]}, {'pixels': '4K'},
    {'pixels': [True, 3]}, {'aspect': '0:3'}, {'pixels': [-1, 1]},
    {'format': 'jpeg', 'background': 'transparent'}, {'background': 'fake-alpha'}, {'oops': 1},
])
def test_invalid_spec_rejected(change):
    with pytest.raises(ValueError):
        specs.validate(card(**change)['common'])


def test_confirmation_is_scope_bound_and_not_preset():
    value = card(); value['confirmation']['quality_confirmed'] = False
    with pytest.raises(ValueError): specs.selection(value, 'single')
    with pytest.raises(ValueError): specs.selection(card(), 'batch')
    value = card('batch'); value['overrides']['missing'] = {'quality': 'fine'}
    with pytest.raises(ValueError): specs.selection(value, 'batch', ['one'])


def test_prompt_and_native_parameters_separate(project):
    folder = new_run(project)
    prompt = (folder / 'prompt.txt').read_text(encoding='utf-8')
    assert '尺寸：1024x1536' not in prompt and '保头脚' in prompt
    plan = specs.adapt_run(folder, caps(), commit=True)
    assert plan['parameters']['quality'] == 'medium' and plan['parameters']['width'] == 30
    assert 'medium' not in prompt
    assert store.read(folder / 'run.json')['image_specs']['scope_id'] == folder.name
    with pytest.raises(ValueError): specs.adapt_run(folder, caps(), commit=True)
    with pytest.raises(ValueError): runs.add_edit_target(folder, project[0] / '视觉资产/master.png')


def test_unsupported_quality_is_not_silent_downgrade(project):
    folder = new_run(project); capability = caps(); del capability['mappings']['quality']
    result = specs.adapt_run(folder, capability)
    assert result['uncontrolled'] == ['quality'] and not result['ready']
    assert not (folder / 'tool-plan.json').exists()
    with pytest.raises(ValueError): specs.adapt_run(folder, capability, commit=True)
    decision = {'accept_uncontrolled': ['quality'], 'statement': 'Synthetic accept uncertainty, NOT quality confirmation'}
    plan = specs.adapt_run(folder, capability, decision, True)
    source = folder / 'test.png'; Image.new('RGB', (30, 45)).save(source)
    result = runs.record(folder, source, actual(folder, plan['parameters']))
    assert result['spec_verification']['status'] == 'UNVERIFIED'
    assert store.read(folder / 'run.json')['image_specs']['requested']['quality'] == 'standard'
    with pytest.raises(ValueError): runs.review(folder, status='可用', approval='fixture')
    runs.review(folder, status='可用', approval='Synthetic acceptance of uncertainty', accept_issues=True)
    assert pack.archive(folder)['path']


@pytest.mark.parametrize('name,value,descriptor', [
    ('seed', -1, {'type': 'integer', 'min': 0}),
    ('steps', '30', {'type': 'integer'}),
    ('n', 2, {'type': 'integer'}),
    ('quality', 'invalid', {'type': 'string', 'enum': ['high']}),
    ('width', True, {'type': 'integer'}),
    ('command', 'run', {'type': 'string'}),
])
def test_parameter_whitelist_and_types(name, value, descriptor):
    with pytest.raises(ValueError): specs._parameter(name, value, descriptor)


def test_mapping_cannot_fabricate_parameter_or_conflict():
    capability = caps(); capability['mappings']['quality']['values']['standard'] = {'imaginary': 1}
    with pytest.raises(ValueError): specs.adapt(card()['common'], capability, [], ['a'])
    with pytest.raises(ValueError): specs.adapt(card(extra_parameters={'width': 31})['common'], caps(), [], ['a'])


@pytest.mark.parametrize('mode', ['unknown', 'single', 'global'])
def test_group_requires_real_multi_identity(mode):
    capability = caps(); capability['identity_binding'] = {'mode': mode}
    with pytest.raises(ValueError, match='独立身份'):
        specs.adapt(card(identity_control='required')['common'], capability, [], ['a', 'b'])
    result = specs.adapt(card(identity_control='optional')['common'], capability, [], ['a', 'b'])
    assert result['ready'] and any('未启用' in line for line in result['notices'])


def test_binding_rejects_cross_owner_and_scene_inputs():
    capability = caps(); capability['identity_binding'] = {'mode': 'multi', 'parameter': 'identities', 'evidence': 'fixture'}
    capability['parameters']['identities'] = {'type': 'array', 'identity_parameter': True}
    refs = [{'number': 1, 'owner': 'a', 'uses': [{'role': 'identity'}]},
            {'number': 2, 'owner': 'b', 'uses': [{'role': 'identity'}]},
            {'number': 3, 'owner': 'a', 'uses': [{'role': 'scene'}]}]
    decision = {'identity_bindings': {'a': {'reference_numbers': [1], 'value': .8},
                                       'b': {'reference_numbers': [2], 'value': .9}},
                'identity_native_value': [{'reference': 1, 'weight': .8}, {'reference': 2, 'weight': .9}]}
    assert specs.adapt(card(identity_control='required')['common'], capability, refs, ['a', 'b'], decision)['ready']
    for invalid in [2, 3]:
        decision['identity_bindings']['a']['reference_numbers'] = [invalid]
        with pytest.raises(ValueError): specs.adapt(card(identity_control='required')['common'], capability, refs, ['a', 'b'], decision)


def test_insufficient_reference_capacity_is_hard_block():
    capability = caps(); capability['references']['max_images'] = 0
    with pytest.raises(ValueError): specs.adapt(card()['common'], capability, [{}], ['a'])
    capability['references']['supported'] = None
    with pytest.raises(ValueError): specs.adapt(card()['common'], capability, [{}], ['a'])


@pytest.mark.parametrize('image_mode,alpha,expected', [('RGB', None, 'FAIL'), ('RGBA', 255, 'FAIL'), ('RGBA', 0, 'PASS')])
def test_real_transparency_not_mode_or_checkerboard(project, image_mode, alpha, expected):
    folder = new_run(project, card(background='transparent'))
    plan = specs.adapt_run(folder, caps(), commit=True)
    source = folder / 'test.png'
    Image.new(image_mode, (30, 45), (255, 255, 255) if alpha is None else (255, 255, 255, alpha)).save(source)
    result = runs.record(folder, source, actual(folder, plan['parameters']))['spec_verification']
    assert result['status'] == expected
    assert result['actual']['native_resolution_provenance'] == 'UNVERIFIED'


def test_mismatch_preserves_original_and_requires_acceptance(project):
    folder = new_run(project); plan = specs.adapt_run(folder, caps(), commit=True)
    source = folder / 'misnamed.png'; Image.new('RGB', (12, 12)).save(source, format='JPEG')
    receipt = actual(folder, {**plan['parameters'], 'quality': 'low'})
    receipt['tool'] = 'different-tool'
    result = runs.record(folder, source, receipt)['spec_verification']
    assert result['status'] == 'FAIL' and result['actual']['format'] == 'jpeg'
    assert all(result['checks'][key]['status'] == 'FAIL' for key in ['pixels', 'aspect', 'format', 'parameters', 'tool'])
    assert store.digest(source) == store.digest(folder / 'original.png')


def test_missing_receipt_is_unverified_not_plan_copy(project):
    folder = new_run(project); specs.adapt_run(folder, caps(), commit=True)
    source = folder / 'test.png'; Image.new('RGB', (30, 45)).save(source)
    assert runs.record(folder, source, metadata())['spec_verification']['checks']['parameters']['status'] == 'UNVERIFIED'


def test_record_before_adapt_rejected_and_no_extra_calls(project):
    folder = new_run(project)
    with pytest.raises(ValueError): runs.record(folder, project[0] / '视觉资产/master.png', metadata())
    assert not (folder / 'original.png').exists()
    specs.adapt_run(folder, caps(), commit=True)
    receipt = metadata(); receipt.update(request_count=2, success_count=2)
    with pytest.raises(ValueError): runs.record(folder, project[0] / '视觉资产/master.png', receipt)


def test_plan_tampering_rejected(project):
    folder = new_run(project); specs.adapt_run(folder, caps(), commit=True)
    plan = store.read(folder / 'tool-plan.json'); plan['parameters']['quality'] = 'low'; store.write(folder / 'tool-plan.json', plan)
    with pytest.raises(ValueError): runs.record(folder, project[0] / '视觉资产/master.png', metadata())


def test_preset_has_no_approval_and_no_overwrite(tmp_path):
    path = Path(specs.preset_save(tmp_path, 'single-v1', card()['common'])['preset'])
    value = store.read(path)
    assert value['quality_requires_confirmation'] and 'confirmation' not in value
    with pytest.raises(ValueError): specs.preset_save(tmp_path, 'single-v1', card()['common'])
    with pytest.raises(ValueError): specs.preset_save(store.SKILL, 'forbidden', card()['common'])


def test_twenty_four_common_confirmation_with_one_exception(cast, tmp_path):
    chosen = card('batch'); chosen['overrides'] = {'person-12-02': {'aspect': '1:1', 'pixels': [32, 32], 'quality': 'fine'}}
    root = start(tmp_path, plan_for(cast, image_specs=chosen))
    assert batch.status(root)['total'] == 24
    for item in store.read(root / 'plan.json')['items']:
        key = item['id']; folder = Path(batch.prepare(root, key)['run'])
        with pytest.raises(ValueError): batch.dispatch(root, key, 'not ready')
        plan = specs.adapt_run(folder, caps(), commit=True)
        run = store.read(folder / 'run.json')
        assert run['image_specs']['scope_id'] == 'fixture-batch'
        assert run['image_specs']['confirmation'] == chosen['confirmation']
        dims = run['image_specs']['requested']['pixels']
        assert dims == ([32, 32] if key == 'person-12-02' else [30, 45])
        image = folder / 'test.png'; Image.new('RGB', dims).save(image)
        batch.dispatch(root, key, 'SYNTHETIC no external invocation')
        with pytest.raises(ValueError): specs.adapt_run(folder, caps(), commit=True)
        batch.record(root, key, image, actual(folder, plan['parameters']))
        batch.review(root, key, checks([item['cast'][0]['character']]))
    result = batch.status(root)
    assert result['counts'] == {'reviewed': 24} and result['calls']['confirmed_requests'] == 24
    assert result['total'] == 24 and all(x['attempts'] == 1 for x in result['items'])


@pytest.mark.parametrize('count', [5, 8])
def test_group_specs_unified_with_identity_check(cast, tmp_path, count):
    plan = group_plan(cast, count); del plan['common']['aspect']; del plan['common']['size']
    plan['image_specs'] = card('batch', aspect='16:9', pixels='native', framing='同框分层')
    root = start(tmp_path, plan); folder = Path(batch.prepare(root, 'group')['run'])
    adapted = specs.adapt_run(folder, caps(), commit=True)
    assert adapted['parameters']['aspect'] == '16:9'
    assert len({ref['owner'] for ref in store.read(folder / 'run.json')['inputs']}) == count


def test_batch_deviation_enters_central_repair(cast, tmp_path):
    root = start(tmp_path, plan_for(cast[:1], 1, image_specs=card('batch')))
    folder = Path(batch.prepare(root, 'person-01-01')['run'])
    plan = specs.adapt_run(folder, caps(), commit=True); batch.dispatch(root, 'person-01-01', 'fixture')
    batch.record(root, 'person-01-01', cast[0].parent / '视觉资产/master.png', actual(folder, plan['parameters']))
    assert batch.review(root, 'person-01-01', checks(['person-01']))['state'] == 'needs_repair'
    with pytest.raises(ValueError): batch.approve(root, 'person-01-01', 'fixture')
    report = Path(batch.report(root)['report']).read_text(encoding='utf-8'); assert '输出规格：FAIL' in report
    batch.approve(root, 'person-01-01', 'Synthetic acceptance of dimension mismatch', accept_issues=True)
    assert batch.archive(root, 'person-01-01')['path']


def test_batch_handoff_without_tool_plan_is_not_false_pass(cast, tmp_path):
    root = start(tmp_path, plan_for(cast[:1], 1, image_specs=card('batch', aspect='3:4', pixels=[30, 40])))
    batch.prepare(root, 'person-01-01'); batch.dispatch(root, 'person-01-01', 'external fixture', handoff=True)
    result = batch.record(root, 'person-01-01', cast[0].parent / '视觉资产/master.png', metadata())
    assert result['spec_verification']['status'] == 'UNVERIFIED'


def test_old_runs_explicitly_unverified(project):
    save(project); folder = pack.prepare(project[1], '河岸')['run']
    result = runs.record(folder, project[0] / '视觉资产/master.png', metadata())
    assert result['spec_verification']['legacy'] is True


def test_conflicting_old_and_new_specs_rejected(project, cast, tmp_path):
    save(project)
    with pytest.raises(ValueError): pack.prepare(project[1], image_specs=card(), aspect='1:1')
    plan = plan_for(cast[:1], image_specs=card('batch'), common={'aspect': '1:1'})
    with pytest.raises(ValueError): start(tmp_path, plan)
