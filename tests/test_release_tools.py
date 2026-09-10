"""Publish failures must be detected without relying on locally ignored assets."""
import json
import subprocess
import pytest

from scripts.audit_release import audit, document_links
from scripts.split_archive import pack, restore


def test_markdown_assets_and_code_examples():
    body = '''![inline](<images/a b.png>)
![ref][chart]

[chart]: images/c.png
<img src="images/d.png">
```
![not an asset](missing.png)
```
'''
    assert set(document_links(body)) == {'images/a%20b.png', 'images/c.png', 'images/d.png'}


def test_ignored_missing_case_and_large_files(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / '.gitignore').write_text('ignored.png\n')
    (tmp_path / 'ignored.png').write_bytes(b'image')
    (tmp_path / 'Present.png').write_bytes(b'image')
    (tmp_path / 'README.md').write_text('![x](ignored.png) ![y](missing.png) ![z](present.png)')
    (tmp_path / 'large.bin').write_bytes(b'x' * 2048)
    result = audit(tmp_path, max_file_mib=.001, history=False)
    assert not result['ok']
    reasons = [x['reason'] for x in result['errors']]
    assert any('excluded from checkout' in r for r in reasons)
    assert 'missing target' in reasons
    assert any('upload budget' in r for r in reasons)
    # On Linux a case mismatch is also a missing file; it must fail on either OS.
    assert any(e.get('link') == 'present.png' for e in result['errors'])


def test_split_restore_corrupt_and_missing_part(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    (source / 'README.md').write_text('demo')
    (source / 'nested').mkdir()
    (source / 'nested' / 'data.bin').write_bytes(bytes(range(256)) * 20)
    output = tmp_path / 'parts'
    manifest = pack(source, output, part_mib=.0002)
    assert len(manifest['parts']) > 1
    restored = tmp_path / 'restored'
    restore(output / 'manifest.json', restored)
    assert (restored / 'nested/data.bin').read_bytes() == (source / 'nested/data.bin').read_bytes()
    part = output / manifest['parts'][0]['path']
    original = part.read_bytes(); part.write_bytes(b'!' + original[1:])
    with pytest.raises(ValueError, match='checksum'):
        restore(output / 'manifest.json', tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()
    part.unlink()
    with pytest.raises(FileNotFoundError):
        restore(output / 'manifest.json', tmp_path / 'missing')


def test_manifest_cannot_escape_directory(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    (source / 'file').write_text('demo')
    output = tmp_path / 'parts'; manifest = pack(source, output)
    manifest['parts'][0]['path'] = '../outside'
    (output / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Unsafe part'):
        restore(output / 'manifest.json', tmp_path / 'restored')
