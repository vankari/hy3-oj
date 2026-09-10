"""Create/check/restore SHA-256 verified ZIP parts using only the Python standard library."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def pack(source, output, part_mib=8, name='Hy3-OJ-demo.zip'):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.is_relative_to(source):
        raise ValueError('Output must be outside source directory')
    if Path(name).name != name or not 0 < part_mib <= 20:
        raise ValueError('Use a basename and a part size in (0, 20] MiB')
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'manifest.json').exists() or list(output.glob(name + '.*')):
        raise FileExistsError('Choose an empty output; existing release parts will not be overwritten')
    files = sorted(p for p in source.rglob('*') if p.is_file())
    if not files or any(p.is_symlink() for p in source.rglob('*')):
        raise ValueError('Source must contain files and no symlinks')
    manifest = {'format': 1, 'archive': name, 'part_bytes': int(part_mib * 1024**2), 'files': [], 'parts': []}
    with tempfile.TemporaryDirectory(dir=output) as temp:
        archive = Path(temp) / name
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for path in files:
                relative = path.relative_to(source).as_posix()
                z.write(path, relative)
                manifest['files'].append({'path': relative, 'bytes': path.stat().st_size, 'sha256': digest(path)})
        manifest.update(archive_bytes=archive.stat().st_size, archive_sha256=digest(archive))
        with archive.open('rb') as f:
            index = 1
            while data := f.read(manifest['part_bytes']):
                part = output / f'{name}.{index:03}'
                part.write_bytes(data)
                manifest['parts'].append({'path': part.name, 'bytes': len(data), 'sha256': digest(part)})
                index += 1
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def restore(manifest_path, output, verify_only=False):
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('format') != 1 or not manifest.get('parts') or not manifest.get('files'):
        raise ValueError('Invalid manifest')
    if not verify_only and output.exists() and any(output.iterdir()):
        raise FileExistsError('Restore output must be absent or empty')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        archive = Path(temp) / 'joined.zip'
        with archive.open('wb') as joined:
            for part in manifest['parts']:
                if Path(part['path']).name != part['path']:
                    raise ValueError('Unsafe part path')
                path = manifest_path.parent / part['path']
                if path.stat().st_size != part['bytes'] or digest(path) != part['sha256']:
                    raise ValueError(f'Part checksum mismatch: {part["path"]}')
                with path.open('rb') as f:
                    shutil.copyfileobj(f, joined)
        if archive.stat().st_size != manifest['archive_bytes'] or digest(archive) != manifest['archive_sha256']:
            raise ValueError('Archive checksum mismatch')
        with zipfile.ZipFile(archive) as z:
            expected = {f['path']: f for f in manifest['files']}
            if len(expected) != len(manifest['files']) or sorted(z.namelist()) != sorted(expected):
                raise ValueError('Archive file list differs from manifest')
            for member in z.infolist():
                path = (output / member.filename).resolve()
                if (not path.is_relative_to(output) or ':' in member.filename or '\\' in member.filename
                        or member.filename.startswith('/') or member.is_dir()):
                    raise ValueError('Unsafe archive path')
                item = expected[member.filename]
                with z.open(member) as f:
                    checksum = hashlib.file_digest(f, 'sha256').hexdigest()
                if member.file_size != item['bytes'] or checksum != item['sha256']:
                    raise ValueError(f'File checksum mismatch: {member.filename}')
            if not verify_only:
                output.mkdir(parents=True, exist_ok=True)
                z.extractall(output)
    return {'verified_files': len(manifest['files']), 'parts': len(manifest['parts']), 'archive_sha256': manifest['archive_sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('pack')
    create.add_argument('source', type=Path); create.add_argument('output', type=Path)
    create.add_argument('--part-mib', type=float, default=8)
    read = commands.add_parser('restore')
    read.add_argument('manifest', type=Path); read.add_argument('output', type=Path)
    read.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    result = (pack(args.source, args.output, args.part_mib) if args.command == 'pack'
              else restore(args.manifest, args.output, args.verify_only))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
