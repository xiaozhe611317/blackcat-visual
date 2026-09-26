"""Build the requested single-file chat edition from maintained source documents."""
import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def export(destination, skill=None, replace=False):
    skill = Path(skill or ROOT / 'blackcat-visual')
    parts = [
        (skill / 'references/portable.md').read_text(encoding='utf-8'),
        '\n\n---\n\n# 附录 A：创建角色时使用的固定问卷\n\n',
        (skill / 'references/questionnaire.md').read_text(encoding='utf-8'),
        '\n\n---\n\n# 附录 B：角色生图 MD 模板\n\n复制下列模板，填完后与真实图片一起交付。路径形式在普通聊天中可换成明确的附件名；不要保留不存在的图片引用。\n\n```markdown\n',
        (skill / 'templates/character.md').read_text(encoding='utf-8'),
        '\n```\n',
    ]
    path = Path(destination).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w' if replace else 'x', encoding='utf-8', newline='\n') as output:
        output.write(''.join(parts))
    return {'path': str(path), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--replace', action='store_true', help='Explicitly regenerate the named deliverable')
    args = parser.parse_args()
    print(json.dumps(export(args.out, replace=args.replace), ensure_ascii=False))
