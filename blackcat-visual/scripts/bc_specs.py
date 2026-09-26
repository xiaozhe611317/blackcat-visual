"""Image-spec contracts and declarative adapters; never calls a model or edits pixels."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re

from bc_store import SKILL, digest, identifier, locked, now, read, required_text, write

FIELDS = {'purpose', 'aspect', 'pixels', 'quality', 'format', 'background', 'framing',
          'safe_area', 'identity_control', 'extra_parameters'}
TECHNICAL = ('aspect', 'pixels', 'quality', 'format', 'background')
QUALITIES = {'preview', 'standard', 'fine'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def validate(spec):
    if not isinstance(spec, dict) or set(spec) - FIELDS:
        raise ValueError('规格含未知字段；不允许把任意指令混入参数。')
    required_text(spec, ['purpose', 'aspect', 'quality', 'format', 'background', 'framing', 'safe_area'])
    if not re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*', spec['aspect']):
        raise ValueError('比例用宽:高，例如 2:3。')
    pixels = spec.get('pixels')
    if pixels != 'native':
        if not isinstance(pixels, list) or len(pixels) != 2 or any(type(x) is not int or x <= 0 for x in pixels):
            raise ValueError('pixels 为 [宽,高] 正整数或 native；不能只写 2K/4K。')
        if Fraction(*pixels) != Fraction(spec['aspect'].replace(':', '/')):
            raise ValueError('像素尺寸与比例冲突；不得自动裁剪或变形。')
    if spec['quality'] not in QUALITIES:
        raise ValueError('本次需明确选择 preview/standard/fine 制作档位，无默认档位。')
    if spec['format'] not in {'native', 'png', 'jpeg', 'webp'}:
        raise ValueError('格式为 native/png/jpeg/webp。')
    if spec['background'] not in {'scene', 'solid', 'transparent'}:
        raise ValueError('背景为 scene/solid/transparent。')
    if spec['format'] == 'jpeg' and spec['background'] == 'transparent':
        raise ValueError('JPEG 不能承载透明背景，请明确选择可承载透明的格式。')
    if spec.get('identity_control', 'off') not in {'off', 'optional', 'required'}:
        raise ValueError('身份参数控制为 off/optional/required。')
    if not isinstance(spec.get('extra_parameters', {}), dict):
        raise ValueError('extra_parameters 必须为对象。')
    return deepcopy(spec)


def selection(value, scope, item_ids=None):
    """Freeze an explicit current-request decision, not a preset's stale approval."""
    if not isinstance(value, dict) or set(value) - {'common', 'overrides', 'confirmation'}:
        raise ValueError('规格选择需要 common、可选 overrides、confirmation。')
    confirmation = value.get('confirmation', {})
    required_text(confirmation, ['statement'])
    if confirmation.get('scope') != scope or confirmation.get('quality_confirmed') is not True:
        raise ValueError('需要本次单图/本批规格确认，预设不能代替本次制作档位选择。')
    common = validate(value['common'])
    overrides = value.get('overrides', {})
    if not isinstance(overrides, dict) or (scope == 'single' and overrides):
        raise ValueError('单图不使用逐图例外；批量 overrides 必须为对象。')
    if item_ids is not None and set(overrides) - set(item_ids):
        raise ValueError('逐图规格例外指向不存在的任务。')
    for changes in overrides.values():
        if not isinstance(changes, dict):
            raise ValueError('逐图例外必须为规格字段对象。')
        validate({**common, **changes})
    return deepcopy(value)


def resolve(value, item_id=None):
    return validate({**value['common'], **value.get('overrides', {}).get(item_id, {})})


def prompt_for(prompt, spec):
    # Replace obsolete dimensions from character defaults, not identity/scene content.
    lines = [line for line in prompt.splitlines()
             if not line.startswith(('画幅：', '画幅目标：', '尺寸目标：'))]
    lines += [f'本图构图：{spec["framing"]}；画面宽高比例目标 {spec["aspect"]}。',
              '边缘与留白：' + spec['safe_area'],
              '背景意图：' + {'scene': '遵循本次场景', 'solid': '纯色背景，颜色按本次画面要求',
                            'transparent': '独立主体、透明背景；不画棋盘格'}[spec['background']]]
    # API quality/seed/weights/dimensions are in tool-plan.json, never magic prompt syntax.
    return '\n'.join(lines)


def attach(run, value, item_id=None):
    spec = resolve(value, item_id)
    run['image_specs'] = {'requested': spec, 'confirmation': deepcopy(value['confirmation']),
                          'scope_id': run.get('batch_id', run['run_id']), 'item_id': item_id,
                          'selection_sha256': fingerprint(value), 'requested_sha256': fingerprint(spec)}
    return spec


def preset_save(root, name, spec):
    root = Path(root).resolve(); identifier(name)
    if root == SKILL or SKILL in root.parents:
        raise ValueError('用户预设保存到项目，不能写入 Skill 框架。')
    value = validate(spec)
    # Saved quality is only a prefill, not approval for any future run.
    target = root / '过程记录' / '规格预设' / (name + '.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    with locked(root):
        if target.exists():
            raise ValueError('同名预设已存在；用新名称保存版本，不覆盖。')
        write(target, {'name': name, 'spec': value, 'quality_requires_confirmation': True})
    return {'preset': str(target), 'confirmed_for_generation': False}


def _parameter(name, value, descriptor):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name):
        raise ValueError('工具参数名不合法。')
    # No batch-count, retry, credential, routing, or code injection through image specs.
    if name.lower() in {'n', 'count', 'batch_size', 'num_images', 'num_outputs', 'samples',
                        'retries', 'max_retries', 'api_key', 'token', 'url', 'endpoint', 'command', 'model'}:
        raise ValueError('数量/重试/凭证/路由不能通过规格参数改写：' + name)
    types = {'string': str, 'integer': int, 'number': (int, float), 'boolean': bool, 'object': dict, 'array': list}
    expected = types.get(descriptor.get('type'))
    if expected is None or not isinstance(value, expected) or (isinstance(value, bool) and descriptor['type'] != 'boolean'):
        raise ValueError('参数类型不符：' + name)
    if 'enum' in descriptor and value not in descriptor['enum']:
        raise ValueError('参数值不在当前工具支持范围：' + name)
    if descriptor['type'] in {'integer', 'number'}:
        if 'min' in descriptor and value < descriptor['min'] or 'max' in descriptor and value > descriptor['max']:
            raise ValueError('参数值超出当前工具范围：' + name)
    return value


def adapt(spec, capability, inputs, owners, decision=None):
    """Map only declared native fields. Evidence is supplied by host, not inferred by brand."""
    validate(spec); required_text(capability, ['tool', 'evidence'])
    descriptors = capability.get('parameters', {})
    parameters, unresolved, notices, mappings = {}, [], [], {}
    def put(name, value):
        if name not in descriptors:
            raise ValueError('参数未在真实工具能力白名单中声明：' + name)
        value = _parameter(name, value, descriptors[name])
        if name in parameters and parameters[name] != value:
            raise ValueError('参数映射冲突：' + name)
        parameters[name] = value
    for field in TECHNICAL:
        value = spec[field]
        if value == 'native' or field == 'background' and value in {'scene', 'solid'}:
            continue
        key = 'x'.join(map(str, value)) if isinstance(value, list) else value
        rule = capability.get('mappings', {}).get(field)
        if not isinstance(rule, dict) or key not in rule.get('values', {}):
            unresolved.append(field); continue
        mapped = rule['values'][key]
        if not isinstance(mapped, dict) or not mapped:
            raise ValueError('映射值必须为实际参数对象，例如 {"width":1024,"height":1536}。')
        for name, actual in mapped.items():
            put(name, actual)
        mappings[field] = mapped
    for name, value in spec.get('extra_parameters', {}).items():
        if descriptors.get(name, {}).get('identity_parameter'):
            raise ValueError('身份参数使用独立绑定，不放入全局 extra_parameters。')
        put(name, value)
    refs = capability.get('references', {})
    if inputs and refs.get('supported') is not True:
        raise ValueError('工具未确认支持必要参考图；不能降级为文字猜脸。')
    maximum = refs.get('max_images')
    if maximum is not None and (type(maximum) is not int or maximum < len(inputs)):
        raise ValueError('参考图容量不足，不能丢弃必要身份/场景图。')
    if inputs and maximum is None:
        notices.append('参考数量上限未暴露；提交前核对当前接口，失败不自动重试。')
    control = spec.get('identity_control', 'off')
    identity = capability.get('identity_binding', {})
    required_mode = 'multi' if len(owners) > 1 else 'single'
    bindings = (decision or {}).get('identity_bindings', {})
    usable = identity.get('mode') in ({'multi'} if required_mode == 'multi' else {'single', 'multi'})
    if control != 'off':
        if usable and bindings:
            required_text(identity, ['parameter', 'evidence'])
            if set(bindings) != set(owners):
                raise ValueError('身份控制需逐一绑定本图全部角色。')
            for owner, binding in bindings.items():
                numbers = binding.get('reference_numbers', [])
                own = {x['number'] for x in inputs if x.get('owner', owners[0] if len(owners) == 1 else None) == owner
                       and any(y['role'].startswith('identity') for y in x['uses'])}
                if not numbers or not set(numbers) <= own or 'value' not in binding:
                    raise ValueError('身份参数绑定了错误角色/非身份参考，或缺实际 value。')
            # Host constructs the exact native value; owner metadata is not passed as fake API syntax.
            native = (decision or {}).get('identity_native_value')
            if native is None:
                raise ValueError('需按实际工具说明填写 identity_native_value；不得猜测接口结构。')
            put(identity['parameter'], native)
        elif control == 'required':
            raise ValueError('缺本图所需的独立身份控制/绑定；单脸或全局权重不等于多人绑定。')
        else:
            notices.append('未启用独立身份参数增强；继续使用已确认的真实参考图，不声称逐人锁脸。')
    decision = deepcopy(decision or {})
    accepted = decision.get('accept_uncontrolled', [])
    if not isinstance(accepted, list) or set(accepted) - set(unresolved):
        raise ValueError('只可明确接受本次列出的不可控字段。')
    if accepted:
        required_text(decision, ['statement'])
    return {'tool': capability['tool'], 'evidence': capability['evidence'], 'parameters': parameters,
            'field_mappings': mappings, 'uncontrolled': unresolved, 'notices': notices,
            'decision': decision, 'ready': not (set(unresolved) - set(accepted)),
            'capability': deepcopy(capability), 'identity_bindings': bindings}


def adapt_run(folder, capability, decision=None, commit=False):
    folder = Path(folder).resolve()
    with locked(folder):
        run = read(folder / 'run.json')
        info = run.get('image_specs')
        if not info:
            raise ValueError('本轮没有已确认规格；使用 prepare --specs 或计划 image_specs。')
        if run.get('original') or run.get('submission'):
            raise ValueError('提交或产图后不能改写参数计划。')
        if commit and info.get('plan'):
            raise ValueError('参数计划已冻结；改要求请新建轮次/受影响项。')
        owners = [x['character'] for x in run.get('cast', [])] or [run.get('character_id') or 'candidate']
        result = adapt(info['requested'], capability, run['inputs'], owners, decision)
        result['requested_sha256'] = info['requested_sha256']
        if commit:
            if not result['ready']:
                raise ValueError('规格未能直接设置：' + ', '.join(result['uncontrolled']) + '；先告知用户并确认，不自动降规格。')
            write(folder / 'tool-plan.json', result)
            info['plan'] = {'path': 'tool-plan.json', 'sha256': digest(folder / 'tool-plan.json')}
            write(folder / 'run.json', run)
        return {'run': str(folder), 'committed': commit, **result}


def plan_for_run(folder, run):
    info = run.get('image_specs')
    if not info:
        return None
    if fingerprint(info['requested']) != info['requested_sha256']:
        raise ValueError('冻结规格被修改。')
    ref = info.get('plan')
    if not ref or ref['path'] != 'tool-plan.json':
        raise ValueError('需先 spec-adapt --commit 冻结本轮真实工具参数。')
    path = Path(folder) / ref['path']
    if digest(path) != ref['sha256']:
        raise ValueError('工具参数计划被修改。')
    plan = read(path)
    if not plan.get('ready') or plan.get('requested_sha256') != info['requested_sha256']:
        raise ValueError('工具参数计划与冻结规格不符。')
    return plan


def verify_output(folder, run, image, metadata):
    external_without_plan = bool(run.get('image_specs') and not run['image_specs'].get('plan')
                                 and run.get('submission', {}).get('handoff'))
    plan = ({'parameters': {}, 'tool': metadata['tool'], 'uncontrolled': ['quality']}
            if external_without_plan else plan_for_run(folder, run))
    if plan is None:
        return {'status': 'UNVERIFIED', 'legacy': True, 'note': '旧轮次未记录独立规格，不推断规格达标。'}
    from PIL import Image
    spec = run['image_specs']['requested']
    with Image.open(image) as source:
        source.load()
        width, height = source.size
        alpha = source.convert('RGBA').getchannel('A').getextrema()
        actual = {'width': width, 'height': height, 'format': source.format.lower(), 'mode': source.mode,
                  'has_transparent_pixels': alpha[0] < 255, 'alpha_extrema': list(alpha),
                  'native_resolution_provenance': 'UNVERIFIED', 'visual_sharpness': 'UNVERIFIED'}
    checks = {}
    def check(key, passed, note):
        checks[key] = {'status': 'PASS' if passed else 'FAIL', 'note': note}
    check('aspect', Fraction(width, height) == Fraction(spec['aspect'].replace(':', '/')), f'{width}:{height} vs {spec["aspect"]}')
    if spec['pixels'] != 'native':
        check('pixels', [width, height] == spec['pixels'], f'{[width, height]} vs {spec["pixels"]}')
    if spec['format'] != 'native':
        check('format', actual['format'] == spec['format'], actual['format'])
    if spec['background'] == 'transparent':
        check('transparency', actual['has_transparent_pixels'], '检查真实透明像素，不以棋盘格外观代替。')
    applied = metadata.get('applied_parameters')
    if not isinstance(applied, dict):
        checks['parameters'] = {'status': 'UNVERIFIED', 'note': '缺实际提交参数回执，不以计划冒充已提交。'}
    else:
        check('parameters', all(k in applied and applied[k] == v for k, v in plan['parameters'].items()),
              '比较计划与实际提交参数；这仍不证明模型遵循或视觉达标。')
    check('tool', metadata['tool'] == plan['tool'], '实际工具与已冻结工具比较。')
    if external_without_plan:
        checks['tool'] = {'status': 'UNVERIFIED', 'note': '外部交接未能预先冻结工具参数计划；只能核对回填文件，不能声称完整参数流程通过。'}
    if 'quality' in plan['uncontrolled']:
        checks['quality'] = {'status': 'UNVERIFIED', 'note': '制作档位为用户意图，工具没有可确认的档位映射。'}
    else:
        checks['quality'] = {'status': checks['parameters']['status'], 'note': '仅检查档位参数提交；细节与清晰度仍须看图。'}
    result = 'FAIL' if any(x['status'] == 'FAIL' for x in checks.values()) else 'UNVERIFIED' if any(x['status'] == 'UNVERIFIED' for x in checks.values()) else 'PASS'
    return {'status': result, 'requested': deepcopy(spec), 'submitted': deepcopy(applied),
            'actual': actual, 'checks': checks, 'acceptance_required': result != 'PASS',
            'note': '文件/参数检查，不证明身份、构图、背景内容、锐度或原生高清。'}


def acceptance_needed(run):
    return run.get('spec_verification', {}).get('acceptance_required', False)
