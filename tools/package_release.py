"""Build and audit a self-contained Windows x64 portable ZIP.

No save discovery, game access, or user-data directory is used by this script.
Official corresponding Qt/PySide source archives are cached under build/ and
published as a companion ZIP rather than relying on a future written offer.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP = 'CrimsonMoonSaveEditor'
TEXT_SUFFIXES = {'.py', '.md', '.txt', '.json', '.ini', '.cfg', '.xml', '.yaml', '.yml', '.csv'}
PRIVATE_PATH = re.compile(rb'(?:[a-zA-Z]:[\\/]+Users[\\/]+[^\\/\r\n"<>]+|'
                          + rb'/' + rb'Users/[^/\r\n"<>]+|' + rb'/' + rb'home/[^/\r\n"<>]+)')
FORBIDDEN_PARTS = {'.venv', '.git', '__pycache__', 'savegames', 'backups', 'originais', 'proposto'}
SOURCE_FILES = ('LICENSE', 'CREDITS.md', 'THIRD_PARTY_NOTICES.md', 'public-resources.json', 'requirements-dev.txt', 'docs/DISTRIBUTION.md', 'docs/PRIVATE_RESOURCES.md', 'crimson_editor.py', 'requirements.txt', 'README.md', 'docs/NEXUS_DESCRIPTION.md', 'docs/SAVE_ANALYSIS.md')
SOURCE_TREES = ('crimson', 'tools', 'tests')


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def release_version() -> str:
    namespace = {}
    exec((ROOT/'crimson'/'__init__.py').read_text(encoding='utf-8'), namespace)
    value = namespace['__version__']
    if not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise RuntimeError('Invalid release version.')
    return value


def audit_file(name: str, raw: bytes) -> None:
    """Reject user data and path traversal; inspect shipped text for dev paths."""
    path = PurePosixPath(name.replace('\\', '/'))
    if path.is_absolute() or '..' in path.parts or ':' in name:
        raise RuntimeError('Unsafe release member: ' + name)
    if any(p.casefold() in FORBIDDEN_PARTS for p in path.parts):
        raise RuntimeError('Private/build directory in release: ' + name)
    if path.suffix.lower() in {'.sav', '.pyc', '.pyo', '.log', '.pdb', '.spec'}:
        raise RuntimeError('Private/build file in release: ' + name)
    if path.suffix.lower() in TEXT_SUFFIXES and PRIVATE_PATH.search(raw):
        raise RuntimeError('Personal absolute path in release text: ' + name)


def manifest_for(folder: Path, source_companion: dict | None = None) -> dict:
    rows = []
    for path in sorted(folder.rglob('*')):
        if not path.is_file() or path.name == 'release-manifest.json':
            continue
        if path.is_symlink():
            raise RuntimeError('No symlinks in release: ' + str(path))
        raw = path.read_bytes()
        name = path.relative_to(folder).as_posix()
        audit_file(name, raw)
        rows.append({'path': name, 'bytes': len(raw), 'sha256': sha256(raw)})
    return {'schema': 1, 'application': APP, 'version': release_version(),
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'platform': 'windows-x64', 'files': rows,
            'personal_saves_included': False, 'source_companion': source_companion,
            'game_load_tested_for_every_feature': False}


def verify_zip(path: Path) -> dict:
    """Fully hash-check the allowlisted release; does not extract the ZIP."""
    with zipfile.ZipFile(path) as archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) != len({i.filename for i in infos}):
            raise RuntimeError('Duplicate ZIP members.')
        roots = {PurePosixPath(i.filename).parts[0] for i in infos}
        if roots != {APP}:
            raise RuntimeError('ZIP must contain one ' + APP + ' folder.')
        actual = {}
        manifest = None
        for entry in infos:
            name = PurePosixPath(entry.filename).relative_to(APP).as_posix()
            raw = archive.read(entry)
            audit_file(name, raw)
            if name == 'release-manifest.json':
                manifest = json.loads(raw)
            else:
                actual[name] = (len(raw), sha256(raw))
        if not isinstance(manifest, dict) or manifest.get('schema') != 1:
            raise RuntimeError('Release manifest missing or unsupported.')
        rows = manifest.get('files', [])
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise RuntimeError('Malformed manifest files.')
        expected = {r['path']: (r['bytes'], r['sha256']) for r in rows}
        if len(expected) != len(rows) or actual != expected:
            raise RuntimeError('Release contents differ from the manifest.')
        required = {APP+'.exe', 'README.md', 'THIRD_PARTY_NOTICES.md', 'source/crimson_editor.py',
                    'source/tools/package_release.py', 'LICENSES/Python-LICENSE.txt'}
        if not required.issubset(actual):
            raise RuntimeError('Release is missing required files: ' + ', '.join(sorted(required-actual.keys())))
        companion = manifest.get('source_companion')
        if companion:
            if (not isinstance(companion, dict) or Path(companion.get('filename', '')).name != companion.get('filename')
                    or not re.fullmatch(r'[0-9a-f]{64}', companion.get('sha256', ''))):
                raise RuntimeError('Malformed source companion descriptor.')
            source_zip = path.parent/companion['filename']
            if not source_zip.is_file() or sha256(source_zip.read_bytes()) != companion['sha256']:
                raise RuntimeError('Corresponding library source companion missing or changed: ' + str(source_zip))
            with zipfile.ZipFile(source_zip) as sources:
                source_names = sources.namelist()
                for prefix in ('qtbase-', 'pyside-setup-'):
                    if not any(n.startswith(prefix) and n.endswith('.tar.xz') for n in source_names):
                        raise RuntimeError('Source companion missing library archive: ' + prefix)
        else:
            for prefix in ('SOURCES/qtbase-', 'SOURCES/pyside-setup-'):
                if not any(n.startswith(prefix) and n.endswith('.tar.xz') for n in actual):
                    raise RuntimeError('Corresponding library source missing: ' + prefix)
        if not any('LGPL-3.0' in n for n in actual):
            raise RuntimeError('LGPL license text missing.')
        if not any(n.startswith('_internal/data/') and n.endswith('.json') for n in actual):
            raise RuntimeError('Catalog data missing.')
        return {'verified': True, 'files': len(actual), 'bytes': sum(v[0] for v in actual.values()),
                'version': manifest.get('version'), 'sha256': sha256(path.read_bytes())}


def _download_checked(url: str, destination: Path) -> Path:
    """Qt publishes SHA-256 sidecars for its official source archives."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url+'.sha256', headers={'User-Agent': APP+' release builder'})
    with urllib.request.urlopen(request, timeout=60) as response:
        text = response.read(4096).decode('ascii')
    match = re.search(r'\b[a-fA-F0-9]{64}\b', text)
    if not match:
        raise RuntimeError('No valid SHA256 sidecar: ' + url)
    expected = match.group(0).lower()
    if destination.is_file() and sha256(destination.read_bytes()) == expected:
        return destination
    temporary = destination.with_suffix(destination.suffix+'.download')
    try:
        request = urllib.request.Request(url, headers={'User-Agent': APP+' release builder'})
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open('wb') as stream:
            shutil.copyfileobj(response, stream)
        if sha256(temporary.read_bytes()) != expected:
            raise RuntimeError('Source archive hash mismatch: ' + url)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def qt_source_urls(qt_version: str, pyside_version: str) -> list[str]:
    minor = '.'.join(qt_version.split('.')[:2])
    return [f'https://download.qt.io/official_releases/qt/{minor}/{qt_version}/submodules/qtbase-everywhere-src-{qt_version}.tar.xz',
            f'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{pyside_version}-src/pyside-setup-everywhere-src-{pyside_version}.tar.xz']


def _copy_licenses(archive: Path, destination: Path) -> None:
    """Copy license/notice files by reading members; never extract arbitrary paths."""
    with tarfile.open(archive, 'r:xz') as tar:
        for member in tar.getmembers():
            path = PurePosixPath(member.name)
            if not member.isfile() or path.is_absolute() or '..' in path.parts:
                continue
            name = path.name.casefold()
            is_license = any(p.casefold() in {'licenses', 'license'} for p in path.parts)
            if not (is_license or name.startswith(('copying', 'license', 'licence', 'notice')) or name == 'qt_attribution.json'):
                continue
            if member.size > 4*1024*1024:
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(handle.read())


def include_sources_and_notices(folder: Path) -> dict:
    from PySide6.QtCore import qVersion
    qt_version = qVersion()
    pyside_version = importlib.metadata.version('PySide6-Essentials')
    qt_dlls = {p.stem for p in folder.rglob('Qt6*.dll')}
    qtbase_dlls = {'Qt6Core', 'Qt6Gui', 'Qt6Widgets', 'Qt6OpenGL', 'Qt6OpenGLWidgets',
                   'Qt6Network', 'Qt6PrintSupport', 'Qt6Concurrent', 'Qt6Sql', 'Qt6DBus',
                   'Qt6Test', 'Qt6Xml'}
    unexpected = qt_dlls-qtbase_dlls
    if unexpected:
        raise RuntimeError('Add corresponding Qt source modules before shipping: ' + ', '.join(sorted(unexpected)))
    urls = qt_source_urls(qt_version, pyside_version)
    source_name = f'{APP}-{release_version()}-library-sources.zip'
    source_zip = folder.parent/source_name
    archives = []
    license_dir = folder/'LICENSES'
    license_dir.mkdir(exist_ok=True)
    for url in urls:
        archive = _download_checked(url, ROOT/'build'/'third_party_sources'/url.rsplit('/', 1)[-1])
        archives.append(archive)
        _copy_licenses(archive, license_dir)
    python_license = Path(sys.base_prefix)/'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('Python license not found: ' + str(python_license))
    shutil.copy2(python_license, license_dir/'Python-LICENSE.txt')
    for distribution in ('PyInstaller', 'shiboken6', 'PySide6-Essentials'):
        metadata = importlib.metadata.distribution(distribution)
        for file in metadata.files or []:
            if 'license' in str(file).casefold() or str(file).endswith('COPYING.txt'):
                source = Path(metadata.locate_file(file))
                if source.is_file():
                    target = license_dir/distribution/source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    with zipfile.ZipFile(source_zip, 'w', compression=zipfile.ZIP_STORED) as source_output:
        for archive in archives:
            source_output.write(archive, archive.name)
        source_output.writestr('README.txt',
            'Corresponding unmodified QtBase and PySide/Shiboken source archives.\n'
            'Distribute this ZIP next to the matching portable editor release.\n'
            'Library build scripts and license/copyright notices are in the archives.\n'
            + '\n'.join(urls)+'\n')
    companion = {'filename': source_name, 'sha256': sha256(source_zip.read_bytes())}
    notice = f'''# Third-party notices and corresponding sources

This portable application uses unmodified Qt {qt_version}, PySide6 {pyside_version}
and Shiboken6 shared libraries under the LGPL version 3 option. Copyright The Qt
Company Ltd. and other contributors. Full license texts, copyright notices and
third-party attributions are in LICENSES/ and inside the source archives.

The complete official corresponding QtBase and PySide/Shiboken source archives
are supplied in the companion download `{source_name}`. The distributor must
provide this companion at the same release download location as the editor.
Source access is free of charge and does not require obtaining the executable.
Companion SHA-256: {companion['sha256']}

The companion archives were downloaded from:

{chr(10).join('- '+url for url in urls)}

No Qt/PySide/Shiboken library source modifications were made by this project.
These source archives include the upstream build scripts. See their README and
build documentation for prerequisites. The application source and release build
script are in source/. Install the matching requirements and rebuild with
`python tools/package_release.py`; replace the PySide/Qt shared libraries in
_internal/ with compatible modified builds to run them. Keep their DLLs and Python
extension modules ABI compatible. No signing, activation or signature lock is
enforced by this editor. You may modify/replace the LGPL libraries and reverse
engineer the application for debugging those modifications. Those rights are
not restricted by any application terms.

Official library build instructions:
- https://doc.qt.io/qt-6/build-sources.html
- https://doc.qt.io/qtforpython-6/building_from_source/index.html
- https://www.qt.io/development/open-source-lgpl-obligations

Python {platform.python_version()} is included under the PSF license; see
LICENSES/Python-LICENSE.txt. The executable uses the PyInstaller bootloader;
its GPL license includes an exception for distributing bundled applications.
Its license and exception are in LICENSES/PyInstaller/.

Game artwork, names and localization text belong to their respective owners.
This project is an unofficial community editor and claims no ownership of them.
The packaged source archives and notices do not grant rights to game content.
'''
    (folder/'THIRD_PARTY_NOTICES.md').write_text(notice, encoding='utf-8')
    source_zip.with_suffix('.zip.sha256').write_text(companion['sha256']+'  '+source_name+'\n', encoding='ascii')
    return companion


def include_app_sources(folder: Path) -> None:
    source = folder/'source'
    source.mkdir(exist_ok=True)
    for name in SOURCE_FILES:
        (source/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/name, source/name)
    for name in SOURCE_TREES:
        for original in sorted((ROOT/name).rglob('*.py')):
            if '__pycache__' in original.parts:
                continue
            target = source/original.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
    # Data lives alongside the runtime; a rebuild can reuse it without doubling
    # every image in the portable archive.
    (source/'REBUILD.md').write_text(
        'Copy ../_internal/data/ into this source/ folder as data/.\n'
        'Copy ../_internal/assets/ into this source/ folder as assets/.\n'
        'Use Python 3.11 x64 on Windows in a virtual environment.\n'
        'pip install -r requirements.txt\n'
        'python tools/package_release.py\n', encoding='utf-8')


def slim_qt_plugins(folder: Path) -> None:
    """Keep raster-widget plugins only and verify every remaining PE import."""
    qt = folder/'_internal'/'PySide6'
    keep = {'platforms/qwindows.dll', 'platforms/qoffscreen.dll',
            'imageformats/qico.dll', 'imageformats/qjpeg.dll', 'imageformats/qgif.dll',
            'styles/qmodernwindowsstyle.dll'}
    plugins = qt/'plugins'
    for path in plugins.rglob('*.dll'):
        if path.relative_to(plugins).as_posix() not in keep:
            path.unlink()
    removed = set()
    for pattern in ('Qt6Pdf.dll', 'Qt6Qml*.dll', 'Qt6Quick*.dll', 'Qt6Svg*.dll', 'Qt6VirtualKeyboard.dll'):
        for path in qt.glob(pattern):
            removed.add(path.name.lower())
            path.unlink()
    import pefile
    # These Qt wheels target Windows' built-in ICU API (unversioned symbols).
    # PyInstaller can accidentally pick a third-party icuuc.dll from PATH; such
    # a DLL has version-suffixed symbols and breaks import before the UI opens.
    core = pefile.PE(str(qt/'Qt6Core.dll'))
    try:
        icu_imports = {item.name for entry in core.DIRECTORY_ENTRY_IMPORT
                       if entry.dll.lower() == b'icuuc.dll' for item in entry.imports if item.name}
    finally:
        core.close()
    if b'ucnv_open' in icu_imports:
        system_icu = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32'/'icuuc.dll'
        system = pefile.PE(str(system_icu))
        try:
            exported = {item.name for item in system.DIRECTORY_ENTRY_EXPORT.symbols if item.name}
        finally:
            system.close()
        if not icu_imports.issubset(exported):
            raise RuntimeError('This Qt build requires the built-in ICU API from a supported Windows 10/11 system.')
        wrong_icu = folder/'_internal'/'icuuc.dll'
        if wrong_icu.is_file():
            wrong_icu.unlink()
        for path in (folder/'_internal').glob('icudt*.dll'):
            if re.fullmatch(r'icudt\d+\.dll', path.name, re.IGNORECASE):
                removed.add(path.name.lower())
                path.unlink()
    for path in folder.rglob('*'):
        if not path.is_file() or path.suffix.lower() not in {'.exe', '.dll', '.pyd'}:
            continue
        pe = pefile.PE(str(path), fast_load=True)
        try:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
            imports = {row.dll.decode('ascii', errors='replace').lower()
                       for row in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', [])}
            if imports & removed:
                raise RuntimeError('Removed a required Qt dependency from '+str(path.relative_to(folder)))
        finally:
            pe.close()


def build() -> Path:
    from audit_public import audit
    audit()
    if sys.platform != 'win32' or platform.machine().lower() not in {'amd64', 'x86_64'}:
        raise RuntimeError('Build on Windows x64 using 64-bit Python.')
    if sys.maxsize <= 2**32:
        raise RuntimeError('64-bit Python is required.')
    importlib.metadata.version('PyInstaller')
    importlib.metadata.version('PySide6-Essentials')
    out = ROOT/'dist'
    work = ROOT/'build'/'pyinstaller'
    work.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
               '--name', APP, '--noupx', '--add-data', str(ROOT/'data')+os.pathsep+'data',
               '--add-data', str(ROOT/'assets')+os.pathsep+'assets',
               '--distpath', str(out), '--workpath', str(work), '--specpath', str(work)]
    for module in ('tkinter', '_tkinter', 'PyQt5', 'PyQt6', 'PySide2',
                   'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtWebEngineCore',
                   'PySide6.QtWebEngineWidgets', 'PySide6.QtDesigner', 'PySide6.QtHelp',
                   'PySide6.QtSql', 'PySide6.QtTest'):
        command.extend(['--exclude-module', module])
    icon = ROOT/'assets'/'ui'/'app.ico'
    if icon.is_file():
        command.extend(['--icon', str(icon)])
    command.append(str(ROOT/'crimson_editor.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    return package_existing(out/APP)


def package_existing(folder: Path) -> Path:
    """Reaudit/repack an already frozen application without recompiling it."""
    out = ROOT/'dist'
    if folder.resolve() != (out/APP).resolve() or not (folder/(APP+'.exe')).is_file():
        raise RuntimeError('Build the application in dist/ before repacking it.')
    from audit_public import audit
    audit()
    for resource in ('data', 'assets'):
        for path in (folder/'_internal'/resource).rglob('*'):
            if path.is_file():
                original = ROOT/resource/path.relative_to(folder/'_internal'/resource)
                if not original.is_file() or path.read_bytes() != original.read_bytes():
                    raise RuntimeError('Frozen private/unreviewed resource: '+str(path))
    shutil.copy2(ROOT/'LICENSE', folder/'LICENSE')
    shutil.copy2(ROOT/'CREDITS.md', folder/'CREDITS.md')
    slim_qt_plugins(folder)
    shutil.copy2(ROOT/'README.md', folder/'README.md')
    shutil.copy2(ROOT/'docs'/'NEXUS_DESCRIPTION.md', folder/'NEXUS_DESCRIPTION.md')
    shutil.copy2(ROOT/'docs'/'SAVE_ANALYSIS.md', folder/'SAVE_ANALYSIS.md')
    include_app_sources(folder)
    companion = include_sources_and_notices(folder)
    manifest = manifest_for(folder, companion)
    (folder/'release-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    archive_path = out/f'{APP}-{release_version()}-windows-x64.zip'
    temporary = archive_path.with_suffix('.zip.partial')
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(folder.rglob('*')):
                if path.is_file():
                    name = (Path(APP)/path.relative_to(folder)).as_posix()
                    method = zipfile.ZIP_STORED if path.suffix in {'.xz', '.png', '.jpg', '.webp'} else zipfile.ZIP_DEFLATED
                    archive.write(path, name, compress_type=method)
        verify_zip(temporary)
        os.replace(temporary, archive_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    checksum = sha256(archive_path.read_bytes())
    archive_path.with_suffix('.zip.sha256').write_text(checksum+'  '+archive_path.name+'\n', encoding='ascii')
    print(json.dumps(verify_zip(archive_path), indent=2))
    print(archive_path)
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', type=Path, metavar='ZIP', help='Audit an existing ZIP without extracting it.')
    parser.add_argument('--repack', action='store_true', help='Reaudit and repack the existing frozen dist/ folder.')
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_zip(args.verify), indent=2))
    elif args.repack:
        package_existing(ROOT/'dist'/APP)
    else:
        build()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
