#!/usr/bin/env python3
"""Validate and archive this self-contained portable plugin (stdlib only)."""
import argparse
import json
import re
import stat
import zipfile
from pathlib import Path


def build(output):
    root = Path(__file__).resolve().parent
    output = output.resolve()
    if output == root or root in output.parents:
        raise ValueError('Keep build output outside the package directory')
    manifest = json.loads((root / 'plugin.json').read_text())
    name = manifest['name']
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
        raise ValueError('Invalid plugin name')
    if manifest.get('$schema') != 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json':
        raise ValueError('Expected the portable Agent Plugins schema')
    if manifest.get('author', {}).get('name') != 'studioigor':
        raise ValueError('Preserve upstream authorship')
    if not manifest.get('description') or not re.fullmatch(r'\d+\.\d+\.\d+', manifest.get('version', '')):
        raise ValueError('Missing description or semantic version')
    skill = root / 'skills' / name
    text = (skill / 'SKILL.md').read_text()
    if not text.startswith('---\n') or '\n---\n' not in text[4:]:
        raise ValueError('Missing YAML frontmatter')
    frontmatter = text.split('\n---\n', 1)[0]
    if not re.search(r'^name:\s*' + re.escape(name) + r'\s*$', frontmatter, re.M):
        raise ValueError('Skill and plugin names must match')
    description = re.search(r'^description: (.+)$', frontmatter, re.M)
    if not description or not isinstance(json.loads(description.group(1)), str):
        raise ValueError('Expected a quoted skill activation description')
    for directory in ('references', 'scripts'):
        if not (skill / directory).is_dir():
            raise ValueError('Missing bundled ' + directory)
    if manifest.get('license') and not (root / 'LICENSE').is_file():
        raise ValueError('A declared license needs the upstream license text')
    files = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlinks are not portable: ' + str(path))
        if path.is_file() and not any(p in ('.git', '__pycache__') for p in path.relative_to(root).parts) and path.suffix != '.pyc':
            files.append(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(root)
            info = zipfile.ZipInfo((Path(name) / relative).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if path.stat().st_mode & stat.S_IXUSR else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, path.read_bytes())
    print(json.dumps({'plugin': name, 'files': len(files), 'archive': str(output)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.output)
