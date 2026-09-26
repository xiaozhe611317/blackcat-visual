"""Verify a clean extracted release independently from the working skill path."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--archive', type=Path, default=ROOT / 'dist' / 'blackcat-visual-v3.1.1.zip')
parser.add_argument('--report', type=Path, default=ROOT / '.test-results/release-smoke.json')
args = parser.parse_args()
archive = args.archive.resolve()
manifest = json.loads(archive.with_suffix('.manifest.json').read_text(encoding='utf-8'))
target = ROOT / '.test-results' / ('release-smoke-' + uuid.uuid4().hex[:8])
target.mkdir(parents=True)
assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['sha256']
with zipfile.ZipFile(archive) as package:
    assert package.testzip() is None
    assert len(package.namelist()) == len(manifest['files'])
    assert set(package.namelist()) == {'blackcat-visual/' + name for name in manifest['files']}
    for member in package.infolist():
        destination = (target / member.filename).resolve()
        assert target.resolve() in destination.parents
        relative = Path(member.filename).relative_to('blackcat-visual').as_posix()
        raw = package.read(member)
        assert hashlib.sha256(raw).hexdigest() == manifest['files'][relative]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
environment = os.environ.copy()
environment.update(BLACKCAT_CONFIG=str(target / 'isolated-config.json'), PYTHONUTF8='1',
                   PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
cli = target / 'blackcat-visual/scripts/blackcat.py'
calls = []
def invoke(*args):
    completed = subprocess.run([sys.executable, str(cli), *map(str, args)], env=environment,
                               capture_output=True, text=True, encoding='utf-8', timeout=30)
    calls.append({'command': args[0], 'returncode': completed.returncode})
    return completed

def ok(*args):
    completed = invoke(*args)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)

def blocked(expected, *args):
    completed = invoke(*args)
    assert completed.returncode == 1 and expected in completed.stderr, completed.stderr

blank = invoke('status')
assert blank.returncode == 1 and '尚未初始化' in blank.stderr
assert not (target / 'isolated-config.json').exists()

# V2 runs from its own project and must not require or create a global binding.
project = target / 'v2 角色项目'
document = project / '验收角色生图.md'
ok('project-init', '--folder', project)
assert all((project / name).is_dir() for name in ['视觉资产', '候审图', '定稿图', '过程记录'])
ok('template', 'document', '--out', document)
template_bytes = document.read_bytes()
assert b'{{' in template_bytes
blocked('模板字段', 'prepare', '--document', document, '--mode', 'candidate', '--asset-type', 'master')
assert document.read_bytes() == template_bytes
document.write_text('''# Synthetic smoke character
## 角色身份
仅为程序验收而设的成年虚构角色，无真实视觉质量主张。
## 固定锚点
无独立锚点。
## 默认外观
- 服装：蓝色夹克
- 妆容：自然
- 发型：短发
## 默认风格
- 画法：水彩纸纹
- 当前风格限制：不要摄影质感
- 通用限制：无无关文字
## 画幅
- 比例：2:3
- 尺寸：1024x1536
## 随机范围
- 场景：书店｜河岸
- 动作：站立｜散步
- 时间：清晨｜傍晚
- 构图：半身｜全身
## 生图规则
- 画面约束：保持身份；本文件仅供程序验收。
所有验收素材均为 synthetic，不是实际人物一致性验证。
## 视觉参考
[母版](视觉资产/master.png)；[样张](视觉资产/style.png)
''', encoding='utf-8')
request = project / '过程记录/request.txt'
request.write_text('程序验收：创建母版的准备记录，不调用生图工具。', encoding='utf-8')
master = ok('prepare', '--document', document, '--mode', 'candidate', '--asset-type', 'master', '--request-file', request)
assert master['inputs'] == [] and Path(master['prompt_file']).is_file()
assert json.loads((Path(master['run']) / 'run.json').read_text(encoding='utf-8'))['asset_type'] == 'master'
blocked('仅首张母版', 'prepare', '--document', document, '--mode', 'candidate', '--asset-type', 'body', '--request-file', request)
blocked('尚未正式登记', 'prepare', '--document', document)
assert not (target / 'isolated-config.json').exists()

# Synthetic, deliberately simple fixtures exercise CLI file contracts, not image generation.
from PIL import Image
for name, color in [('master', 'blue'), ('style', 'green')]:
    Image.new('RGB', (24, 32), color).save(project / '视觉资产' / f'{name}.png')
coverage = ([f'body:{x}' for x in ['front', 'left_three_quarter', 'right_three_quarter', 'left_side', 'right_side', 'back']]
            + [f'face:{x}' for x in ['front', 'left_three_quarter', 'right_three_quarter', 'left_side', 'right_side']]
            + [f'expression:{x}' for x in ['neutral', 'smile', 'laugh', 'sad', 'surprised', 'angry']])
references = project / '过程记录/references.json'
ref_data = {'id': 'smoke-character', 'name': '验收角色', 'anchors_mode': 'none', 'primary_reference': 'master',
            'references': [{'id': 'master', 'path': '视觉资产/master.png', 'role': 'identity', 'coverage': coverage, 'visually_checked': True},
                           {'id': 'style', 'path': '视觉资产/style.png', 'role': 'style', 'coverage': [], 'visually_checked': True},
                           {'id': 'pair', 'path': '视觉资产/style.png', 'role': 'pair', 'coverage': [], 'visually_checked': True}]}
references.write_text(json.dumps(ref_data, ensure_ascii=False), encoding='utf-8')
later = ok('prepare', '--document', document, '--mode', 'candidate', '--asset-type', 'body', '--references', references, '--request-file', request)
assert later['inputs'] and later['inputs'][0]['uses'][0]['role'] == 'identity'
saved = ok('project-save', '--document', document, '--references', references, '--approval', 'SYNTHETIC TEST APPROVAL')
assert saved['revision'] == 1
checked = ok('project-check', '--document', document)
assert checked['status'] == 'PASS' and '不替代实际视觉审核' in checked['note']
prepared = ok('prepare', '--document', document)
assert set(prepared['random_choices']) == {'场景', '动作', '时间', '构图'}
assert '｜' not in prepared['request'] and len(prepared['inputs']) == 2
switched = ok('prepare', '--document', document, '--request-file', request,
              '--style-override', '摄影', '--outfit-override', '黑色西装')
prompt = Path(switched['prompt_file']).read_text(encoding='utf-8')
assert '黑色西装' in prompt and '摄影' in prompt and '无无关文字' in prompt
assert '蓝色夹克' not in prompt and '水彩纸纹' not in prompt and '不要摄影质感' not in prompt
assert len(switched['inputs']) == 1 and switched['inputs'][0]['uses'][0]['role'] == 'identity'
edited = ok('prepare', '--document', document, '--request-file', request,
            '--edit-target', project / '视觉资产/master.png')
assert all(Path(item['path']).is_absolute() and Path(item['path']).is_file() for item in edited['inputs'])
assert not (target / 'isolated-config.json').exists()

# Move the complete project, then continue the already-prepared run through CLI.
run_relative = Path(edited['run']).relative_to(project)
moved = target / 'v2 搬家后'
shutil.move(str(project), moved)
document = moved / document.name
run = moved / run_relative
run_data = json.loads((run / 'run.json').read_text(encoding='utf-8'))
for item in run_data['inputs']:
    assert not Path(item['path']).is_absolute()
    assert hashlib.sha256((run / item['path']).resolve().read_bytes()).hexdigest() == item['sha256']
assert ok('project-check', '--document', document)['status'] == 'PASS'
after_move = ok('prepare', '--document', document)
assert all(Path(item['path']).is_file() for item in after_move['inputs'])
metadata = moved / '过程记录/generation.json'
metadata.write_text(json.dumps({'tool': 'synthetic-fixture', 'actual_submitted_prompt': 'CLI contract only, no image tool invoked',
    'reference_delivery': {'verified': False, 'evidence': 'Synthetic smoke test; no image tool call'},
    'visible_parameters': {}, 'request_count': 0, 'success_count': 0}), encoding='utf-8')
ok('record', '--run', run, '--source', moved / '视觉资产/master.png', '--metadata', metadata)
blocked('明确审核通过', 'archive', '--run', run)
ok('review', '--run', run, '--status', '可用', '--approval', 'SYNTHETIC FILE-CONTRACT APPROVAL')
archived = ok('archive', '--run', run, '--label', 'smoke')
assert Path(archived['path']).name == '001-smoke.png'
assert Path(archived['path']).read_bytes() == (moved / '视觉资产/master.png').read_bytes()
assert ok('archive', '--run', run)['already_archived'] is True
assert (run / 'original.png').is_file()

# V3: exercise the installed CLI only, with twelve synthetic characters and 26 target tasks.
characters = []
for number in range(12):
    key = f'smoke-{number + 1:02d}'
    char_root = target / 'v3-characters' / key
    ok('project-init', '--folder', char_root)
    char_document = char_root / '角色生图.md'
    char_document.write_bytes(document.read_bytes())
    for name in ['master', 'style']:
        shutil.copy2(moved / '视觉资产' / (name + '.png'), char_root / '视觉资产' / (name + '.png'))
    char_refs = {**ref_data, 'id': key, 'name': key}
    char_refs_path = char_root / 'references.json'
    char_refs_path.write_text(json.dumps(char_refs, ensure_ascii=False), encoding='utf-8')
    ok('project-save', '--document', char_document, '--references', char_refs_path, '--approval', 'SYNTHETIC TEST ONLY')
    characters.append({'id': key, 'document': str(char_document)})
items = [{'id': f'{char["id"]}-{n + 1:02d}', 'cast': [{'character': char['id']}], 'request': '程序验收，不调用生图工具'}
         for char in characters for n in range(2)]
for count in [5, 8]:
    items.append({'id': f'group-{count}', 'request': '同框协议验收',
                  'style_override': '摄影',
                  'shot': {'camera': '南向北', 'framing': '全部角色可辨认的中景'},
                  'cast': [{'character': char['id'], 'position': f'画面第 {i + 1} 位', 'action': '站立',
                            'visibility': '脸可见'} for i, char in enumerate(characters[:count])]})
plan_path = target / 'v3-plan.json'
spec_common = {'purpose': 'release fixture', 'aspect': '3:4', 'pixels': [24, 32], 'quality': 'standard',
               'format': 'png', 'background': 'scene', 'framing': '程序验收', 'safe_area': '留边',
               'identity_control': 'off', 'extra_parameters': {}}
spec_selection = {'common': spec_common,
                  'overrides': {'group-5': {'aspect': '16:9', 'pixels': 'native'},
                                'group-8': {'aspect': '16:9', 'pixels': 'native'},
                                'smoke-12-02': {'aspect': '1:1', 'pixels': [32, 32], 'quality': 'fine'}},
                  'confirmation': {'scope': 'batch', 'quality_confirmed': True, 'statement': 'SYNTHETIC current batch choice'}}
plan_path.write_text(json.dumps({'id': 'release-batch', 'characters': characters, 'items': items,
                                 'image_specs': spec_selection}, ensure_ascii=False), encoding='utf-8')
capability = {'tool': 'synthetic-NOT-LIVE', 'evidence': 'Synthetic release contract, not provider support',
              'parameters': {'aspect': {'type': 'string'}, 'size': {'type': 'string'},
                             'quality': {'type': 'string'}, 'format': {'type': 'string'}},
              'mappings': {'aspect': {'values': {a: {'aspect': a} for a in ['3:4', '16:9', '1:1']}},
                           'pixels': {'values': {a: {'size': a} for a in ['24x32', '32x32']}},
                           'quality': {'values': {'standard': {'quality': 'medium'}, 'fine': {'quality': 'high'}}},
                           'format': {'values': {'png': {'format': 'png'}}}},
              'references': {'supported': True, 'max_images': 30}}
cap_path = target / 'synthetic-capability.json'
cap_path.write_text(json.dumps(capability), encoding='utf-8')
single_selection = {'common': spec_common, 'confirmation': {'scope': 'single', 'quality_confirmed': True,
                                                         'statement': 'SYNTHETIC single request choice'}}
single_card = target / 'single-specs.json'; single_card.write_text(json.dumps(single_selection), encoding='utf-8')
single = ok('prepare', '--document', document, '--specs', single_card)
assert ok('spec-adapt', '--run', single['run'], '--capabilities', cap_path)['ready']
assert not (Path(single['run']) / 'tool-plan.json').exists()
ok('spec-adapt', '--run', single['run'], '--capabilities', cap_path, '--commit')
spec_only = target / 'spec-only.json'; spec_only.write_text(json.dumps(spec_common), encoding='utf-8')
assert not ok('spec-preset-save', '--folder', moved, '--name', 'release-spec', '--file', spec_only)['confirmed_for_generation']
batch_root = target / 'v3-batch'
assert ok('batch-init', '--plan', plan_path, '--folder', batch_root)['counts'] == {'ready': 26}
generation_path = target / 'synthetic-generation.json'
generation_path.write_text(json.dumps({'tool': 'synthetic-NOT-LIVE', 'actual_submitted_prompt': 'CLI contract fixture; no image tool invoked',
    'reference_delivery': {'verified': True, 'evidence': 'Simulated only; NOT real visual reference delivery'},
    'visible_parameters': {}, 'request_count': 1, 'success_count': 1}), encoding='utf-8')
for item in items:
    prepared_batch = ok('batch-prepare', '--batch', batch_root, '--item', item['id'])
    assert len({ref.get('owner') for ref in prepared_batch['inputs']}) == len(item['cast'])
    assert all(Path(ref['path']).is_file() for ref in prepared_batch['inputs'])
    if item['id'] == 'smoke-01-01':
        blocked('批次轮次', 'record', '--run', prepared_batch['run'], '--source', moved / '视觉资产/master.png', '--metadata', generation_path)
        blocked('spec-adapt', 'batch-dispatch', '--batch', batch_root, '--item', item['id'], '--evidence', 'must block before adaptation')
    adapted = ok('spec-adapt', '--run', prepared_batch['run'], '--capabilities', cap_path, '--commit')
    receipt = json.loads(generation_path.read_text(encoding='utf-8'))
    receipt['applied_parameters'] = adapted['parameters']
    generation_path.write_text(json.dumps(receipt), encoding='utf-8')
    dimensions = (160, 90) if len(item['cast']) > 1 else (32, 32) if item['id'] == 'smoke-12-02' else (24, 32)
    synthetic_output = target / 'synthetic-output.png'; Image.new('RGB', dimensions, 'blue').save(synthetic_output)
    ok('batch-dispatch', '--batch', batch_root, '--item', item['id'], '--evidence', 'SYNTHETIC simulated submission')
    recorded = ok('batch-record', '--batch', batch_root, '--item', item['id'], '--source', synthetic_output, '--metadata', generation_path)
    assert recorded['spec_verification']['status'] == 'PASS'
    observed = {'status': '通过', 'note': 'SYNTHETIC file contract, NOT a visual quality judgment'}
    qa = {'global': {name: observed for name in ['identity', 'anchors', 'style', 'anatomy', 'request', 'textures']},
          'characters': {member['character']: {name: observed for name in ['identity', 'anchors', 'placement']} for member in item['cast']},
          'continuity': {'status': '无法判断', 'note': 'No scene in this fixture'}}
    qa_path = target / 'synthetic-batch-checks.json'
    qa_path.write_text(json.dumps(qa, ensure_ascii=False), encoding='utf-8')
    ok('batch-review', '--batch', batch_root, '--item', item['id'], '--checks', qa_path)
assert ok('batch-status', '--batch', batch_root)['counts'] == {'reviewed': 26}
ok('batch-approve', '--batch', batch_root, '--item', 'smoke-01-01', '--approval', 'SYNTHETIC acceptance')
assert Path(ok('batch-archive', '--batch', batch_root, '--item', 'smoke-01-01')['path']).is_file()
assert ok('batch-archive', '--batch', batch_root, '--item', 'smoke-01-01')['already_archived']
assert Path(ok('batch-report', '--batch', batch_root)['report']).is_file()
assert not (target / 'isolated-config.json').exists()

# Retain the legacy blank-library compatibility smoke under an isolated binding.
ok('init', '--folder', target / '旧版个人资料库')
listed = ok('list')
assert listed['characters'] == {} and listed['styles'] == {}
ok('template', 'character', '--out', target / '旧版草稿.json')
invalid = invoke('save-character', '--file', target / '旧版草稿.json', '--approval', 'synthetic test only')
assert invalid.returncode == 1
result = {'status': 'passed', 'files_verified': len(manifest['files']), 'archive_sha256': manifest['sha256'],
          'empty_on_first_use': True, 'no_implicit_configuration': True, 'initialized_empty_library': True,
          'incomplete_character_blocked': True, 'v2_template_placeholders_blocked': True,
          'v2_candidate_master_and_identity_gate': True, 'v2_registration_check_prepare': True,
          'v2_default_random_and_style_outfit_overrides': True, 'v2_move_record_approve_archive': True,
          'v2_edit_target_remains_portable': True,
          'v3_twelve_characters_twenty_four_tasks': True, 'v3_five_and_eight_cast_mapping_and_qa': True,
          'v3_no_legacy_qa_bypass': True, 'v3_record_approve_archive_report': True,
          'v31_specs_current_scope_and_per_item_exception': True, 'v31_native_parameter_mapping': True,
          'v31_prompt_parameter_separation': True, 'v31_preset_not_future_confirmation': True,
          'v31_dispatch_gate_and_actual_output_verification': True,
          'legacy_cli_compatible': True, 'cli_calls': calls, 'image_generation_performed': False,
          'visual_quality_verified': False, 'external_processing_dependencies': False}
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
