"""Check the reviewed public resource allowlist before publication or packaging."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]

def audit():
    if os.environ.get('CM_EDITOR_RESOURCES'): raise RuntimeError('Unset CM_EDITOR_RESOURCES before public builds.')
    manifest=json.loads((ROOT/'public-resources.json').read_text('utf-8'))
    actual={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ['data','assets'] for p in (ROOT/folder).rglob('*') if p.is_file()}
    # PNG/ICO files are generated from the original source. Verify they are byte
    # identical to fresh generated icons, rather than trusting arbitrary images.
    import tempfile
    import importlib.util
    spec=importlib.util.spec_from_file_location('public_icons',ROOT/'tools/bootstrap_public_assets.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    expected=dict(manifest['files'])
    with tempfile.TemporaryDirectory() as temporary:
        for name in actual.keys()-expected.keys():
            p=Path(name)
            if p.suffix not in {'.png','.ico'} or p.parent.as_posix() not in {'assets/public','assets/ui'}:
                raise RuntimeError('Unreviewed resource: '+name)
            target=Path(temporary)/p.name
            if p.suffix=='.ico':
                from PySide6.QtGui import QImage
                imagepath=Path(temporary)/'blessing.png';module.render(imagepath,'blessing')
                if not QImage(str(imagepath)).save(str(target)):raise RuntimeError('ICO encoding failed')
            else: module.render(target,p.stem)
            expected[name]=hashlib.sha256(target.read_bytes()).hexdigest()
    if actual!=expected: raise RuntimeError('Resources differ from the reviewed public edition. Do not publish private assets.')
    print('Public resource audit passed:',len(actual),'files; no imported artwork or game localization.')
    return True

if __name__=='__main__':audit()
