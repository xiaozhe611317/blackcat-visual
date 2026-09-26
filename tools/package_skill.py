"""Allowlist-only distributable. Excludes all personal paths, images and runtime data."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'blackcat-visual'
FRAMEWORK_FILES = [
    'SKILL.md', 'agents/openai.yaml',
    'references/onboarding.md', 'references/production.md', 'references/storage.md', 'references/questionnaire.md',
    'templates/character.json', 'templates/style.json', 'templates/generation.json', 'templates/checks.json',
    'scripts/bc_store.py', 'scripts/bc_runs.py', 'scripts/blackcat.py',
    'scripts/folder_picker.py',
    'scripts/bc_pack.py', 'templates/character.md',
    'scripts/bc_batch.py', 'references/batch.md', 'references/environment.md', 'references/portable.md',
    'templates/batch.json', 'templates/scene.json', 'templates/batch-checks.json',
    'scripts/bc_specs.py', 'references/image-specs.md',
    'templates/image-specs.json', 'templates/tool-capabilities.json', 'templates/spec-presets.json',
]

def package(output):
    output = Path(output).resolve()
    files = FRAMEWORK_FILES
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            data = (SKILL / name).read_bytes()
            text = data.decode('utf-8')
            for private_prefix in [str(ROOT), str(Path.home()), 'Bearer sk-']:
                if private_prefix in text:
                    raise ValueError('Personal path or credential found in ' + name)
            manifest[name] = hashlib.sha256(data).hexdigest()
            archive.writestr('blackcat-visual/' + name, data)
    result = {'package': output.name, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'bytes': output.stat().st_size, 'files': manifest}
    output.with_suffix('.manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = package(args.out)
    print(json.dumps({key: value for key, value in result.items() if key != 'files'}, ensure_ascii=False))
