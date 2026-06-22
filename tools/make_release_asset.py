#!/usr/bin/env python3
"""Pack a firmware release manifest + files into one GitHub Release JSON asset."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit('usage: make_release_asset.py <release-manifest> <files-root> <output-json>')
    manifest_path = Path(sys.argv[1])
    files_root = Path(sys.argv[2])
    out_path = Path(sys.argv[3])
    manifest = json.loads(manifest_path.read_text())
    packed_files = []
    for file in manifest['files']:
        path = file['path']
        data = (files_root / path).read_bytes()
        if len(data) != file['size']:
            raise SystemExit(f'size mismatch before packing: {path}')
        packed = dict(file)
        packed.pop('url', None)
        packed['data'] = base64.b64encode(data).decode('ascii')
        packed_files.append(packed)
    manifest['files'] = packed_files
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, separators=(',', ':')) + '\n')
    print(f'wrote {out_path} ({out_path.stat().st_size} bytes, {len(packed_files)} files)')


if __name__ == '__main__':
    main()
