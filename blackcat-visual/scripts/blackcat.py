"""BlackCat records and validation. The host environment performs image generation."""
import argparse
import json
from pathlib import Path
import sys

import bc_store as store
import bc_runs as runs
import bc_pack as pack
import bc_batch as batch
import bc_specs as specs
from folder_picker import pick

def main():
    parser = argparse.ArgumentParser(description='BlackCat 黑猫／视觉工坊')
    parser.add_argument('--library', help='仅此次调用的资料库目录；默认读取本机绑定')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('init'); p.add_argument('--folder'); p.add_argument('--no-bind', action='store_true')
    p = sub.add_parser('bind'); p.add_argument('--folder', required=True)
    sub.add_parser('status'); sub.add_parser('list')
    p = sub.add_parser('template'); p.add_argument('kind', choices=['character', 'style', 'generation', 'checks', 'document', 'batch', 'scene', 'batch-checks', 'image-specs', 'tool-capabilities', 'spec-presets']); p.add_argument('--out', required=True)
    p = sub.add_parser('spec-adapt'); p.add_argument('--run', required=True); p.add_argument('--capabilities', required=True); p.add_argument('--decision'); p.add_argument('--commit', action='store_true')
    p = sub.add_parser('spec-preset-save'); p.add_argument('--folder', required=True); p.add_argument('--name', required=True); p.add_argument('--file', required=True)
    p = sub.add_parser('project-init'); p.add_argument('--folder', required=True)
    p = sub.add_parser('project-save'); p.add_argument('--document', required=True); p.add_argument('--references', required=True); p.add_argument('--approval', required=True); p.add_argument('--update', action='store_true')
    p = sub.add_parser('project-check'); p.add_argument('--document', required=True)
    p = sub.add_parser('archive'); p.add_argument('--run', required=True); p.add_argument('--label')
    for kind in ['character', 'style']:
        p = sub.add_parser('save-' + kind); p.add_argument('--file', required=True); p.add_argument('--approval', required=True); p.add_argument('--update', action='store_true')
        if kind == 'style': p.add_argument('--folder')
    p = sub.add_parser('show'); p.add_argument('kind', choices=['character', 'style']); p.add_argument('name')
    p = sub.add_parser('save-pair'); p.add_argument('--character', required=True); p.add_argument('--style', required=True); p.add_argument('--image', required=True); p.add_argument('--notes', required=True); p.add_argument('--approval', required=True)
    p = sub.add_parser('select'); p.add_argument('--character', required=True); p.add_argument('--style', required=True); p.add_argument('--mode', choices=['production', 'sample'], default='production')
    p = sub.add_parser('prepare'); p.add_argument('--document'); p.add_argument('--character'); p.add_argument('--style'); p.add_argument('--request-file'); p.add_argument('--mode', choices=['production', 'sample', 'candidate'], default='production'); p.add_argument('--reference', action='append'); p.add_argument('--aspect'); p.add_argument('--size'); p.add_argument('--edit-target'); p.add_argument('--style-override'); p.add_argument('--outfit-override'); p.add_argument('--references'); p.add_argument('--asset-type', choices=['master', 'body', 'face', 'expressions', 'anchors', 'style'])
    p.add_argument('--specs', help='本次已确认的规格卡 JSON；新生图流程必填，旧命令仅兼容')
    p = sub.add_parser('record'); p.add_argument('--run', required=True); p.add_argument('--source', required=True); p.add_argument('--metadata', required=True)
    p = sub.add_parser('review'); p.add_argument('--run', required=True); p.add_argument('--checks'); p.add_argument('--status'); p.add_argument('--approval')
    p.add_argument('--accept-issues', action='store_true')
    p = sub.add_parser('rebind'); p.add_argument('kind', choices=['character', 'style']); p.add_argument('name'); p.add_argument('--folder', required=True); p.add_argument('--approval', required=True)
    p = sub.add_parser('catalog'); p.add_argument('--document', action='append', required=True); p.add_argument('--out', required=True)
    p = sub.add_parser('scene-check'); p.add_argument('--file', required=True)
    p = sub.add_parser('batch-init'); p.add_argument('--plan', required=True); p.add_argument('--folder', required=True)
    for command in ['batch-status', 'batch-report']:
        p = sub.add_parser(command); p.add_argument('--batch', required=True)
    for command in ['batch-prepare', 'batch-dispatch', 'batch-record', 'batch-outcome', 'batch-review', 'batch-approve', 'batch-retry', 'batch-archive', 'batch-recover']:
        p = sub.add_parser(command); p.add_argument('--batch', required=True); p.add_argument('--item', required=True)
        if command == 'batch-dispatch':
            p.add_argument('--evidence', required=True); p.add_argument('--handoff', action='store_true')
        if command == 'batch-record':
            p.add_argument('--source', required=True); p.add_argument('--metadata', required=True)
        if command == 'batch-outcome':
            p.add_argument('--state', choices=['failed', 'unknown', 'resolved_no_output'], required=True); p.add_argument('--evidence', required=True)
            p.add_argument('--request-count', type=int, choices=[0, 1])
        if command == 'batch-review': p.add_argument('--checks', required=True)
        if command == 'batch-approve':
            p.add_argument('--approval', required=True); p.add_argument('--purpose', choices=['output', 'continuation'], default='output'); p.add_argument('--accept-issues', action='store_true')
        if command == 'batch-retry':
            p.add_argument('--approval', required=True); p.add_argument('--note', required=True); p.add_argument('--base', choices=['original', 'attempt'], default='original'); p.add_argument('--source-attempt', type=int)
        if command == 'batch-recover':
            p.add_argument('--evidence', required=True); p.add_argument('--not-submitted', action='store_true')
    args = parser.parse_args()
    if args.command == 'spec-adapt': return specs.adapt_run(args.run, store.read(args.capabilities), store.read(args.decision) if args.decision else None, args.commit)
    if args.command == 'spec-preset-save': return specs.preset_save(args.folder, args.name, store.read(args.file))
    if args.command == 'catalog': return batch.catalog(args.document, args.out)
    if args.command == 'scene-check': return batch.scene_check(args.file)
    if args.command == 'batch-init': return batch.initialize(args.plan, args.folder)
    if args.command == 'batch-status': return batch.status(args.batch)
    if args.command == 'batch-report': return batch.report(args.batch)
    if args.command == 'batch-prepare': return batch.prepare(args.batch, args.item)
    if args.command == 'batch-dispatch': return batch.dispatch(args.batch, args.item, args.evidence, args.handoff)
    if args.command == 'batch-record': return batch.record(args.batch, args.item, args.source, store.read(args.metadata))
    if args.command == 'batch-outcome': return batch.outcome(args.batch, args.item, args.state, args.evidence, args.request_count)
    if args.command == 'batch-review': return batch.review(args.batch, args.item, store.read(args.checks))
    if args.command == 'batch-approve': return batch.approve(args.batch, args.item, args.approval, args.purpose, args.accept_issues)
    if args.command == 'batch-retry': return batch.retry(args.batch, args.item, args.approval, args.note, args.base, args.source_attempt)
    if args.command == 'batch-archive': return batch.archive(args.batch, args.item)
    if args.command == 'batch-recover': return batch.recover(args.batch, args.item, args.evidence, args.not_submitted)
    if args.command in {'record', 'review', 'archive'} and store.read(Path(args.run) / 'run.json').get('batch_format'):
        raise ValueError('批次轮次请用 batch-record/batch-review/batch-approve/batch-archive，以保留逐人 QA 和队列状态。')
    if args.command == 'template':
        path = Path(args.out).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as out:
            name = 'character.md' if args.kind == 'document' else f'{args.kind}.json'
            out.write((store.SKILL / 'templates' / name).read_text(encoding='utf-8'))
        return {'template': str(path)}
    if args.command == 'project-init': return pack.initialize_project(args.folder)
    if args.command == 'project-save': return pack.save(args.document, store.read(args.references), args.approval, args.update)
    if args.command == 'project-check': return pack.check(args.document)
    if args.command == 'archive': return pack.archive(args.run, args.label)
    if args.command == 'prepare' and args.document:
        if args.character or args.style:
            raise ValueError('文档模式不与旧版 --character/--style 混用；临时画风使用 --style-override。')
        request = Path(args.request_file).read_text(encoding='utf-8-sig') if args.request_file else ''
        result = pack.prepare(args.document, request, mode=args.mode, extra_refs=args.reference, style_override=args.style_override, outfit_override=args.outfit_override, aspect=args.aspect, size=args.size, references=args.references, asset_type=args.asset_type, image_specs=store.read(args.specs) if args.specs else None)
        if args.edit_target: result = runs.add_edit_target(result['run'], args.edit_target)
        return result
    if args.command == 'init':
        folder = args.folder
        if not folder:
            result = pick('BlackCat：选择个人资料库文件夹')
            if result['status'] != 'selected': return result
            folder = result['path']
        return store.initialize(folder, bind=not args.no_bind)
    if args.command == 'bind':
        root = store.root_path(args.folder)
        store.library(root)
        store.write(store.config_path(), {'schema_version': 1, 'library': str(root)})
        return {'library': str(root), 'bound': True}
    if args.command == 'record': return runs.record(args.run, args.source, store.read(args.metadata))
    if args.command == 'review': return runs.review(args.run, store.read(args.checks) if args.checks else None, args.status, args.approval, args.accept_issues)
    root = store.root_path(args.library)
    if args.command in ['list', 'status']:
        data = store.library(root)
        return {'library': str(root), 'characters': data['characters'], 'styles': data['styles'], 'ready_for_selection': bool(data['characters'] and data['styles'])}
    if args.command.startswith('save-') and args.command != 'save-pair':
        kind = args.command[5:]
        data = store.read(args.file)
        store.validate_profile(data, kind)
        folder = getattr(args, 'folder', None)
        if kind == 'style' and not args.update and not folder:
            result = pick(f'BlackCat：为「{data["name"]}」选择风格规则、参考和作品保存文件夹')
            if result['status'] != 'selected': return result
            folder = result['path']
        return store.save_profile(root, kind, data, args.approval, folder, args.update)
    if args.command == 'show': return store.load_profile(root, args.kind, args.name)[0]
    if args.command == 'save-pair': return store.save_pair(root, args.character, args.style, args.image, args.notes, args.approval)
    if args.command == 'select': return store.select(root, args.character, args.style, args.mode)
    if args.command == 'prepare':
        if args.specs:
            raise ValueError('规格卡使用 --document 模式，不与旧角色资料库模式混用。')
        if not args.character or not args.style or not args.request_file:
            raise ValueError('优先使用 --document 角色生图.md；旧版模式需 --character、--style 和 --request-file。')
        if args.mode == 'candidate' or args.style_override or args.outfit_override or args.references or args.asset_type:
            raise ValueError('候选、默认项覆盖和建档参数需使用 --document。')
        result = runs.prepare(root, args.character, args.style, Path(args.request_file).read_text(encoding='utf-8-sig'), args.mode, args.reference, args.aspect, args.size)
        if args.edit_target: result = runs.add_edit_target(result['run'], args.edit_target)
        return result
    if args.command == 'rebind': return store.rebind(root, args.kind, args.name, args.folder, args.approval)

if __name__ == '__main__':
    try:
        print(json.dumps(main(), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, ImportError) as error:
        print(json.dumps({'status': 'error', 'message': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
