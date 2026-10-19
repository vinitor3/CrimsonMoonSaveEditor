"""Release smoke in an extracted temporary copy; no writes to installed saves."""
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import json
import marshal
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import winreg
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crimson.storage import find_saves
from PyInstaller.archive.readers import CArchiveReader

spec = importlib.util.spec_from_file_location('package_release', ROOT/'tools/package_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def registry_snapshot():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\CrimsonMoonSaveEditor\Editor') as key:
            result = []
            index = 0
            while True:
                try:
                    result.append(winreg.EnumValue(key, index))
                    index += 1
                except OSError:
                    break
            return result
    except FileNotFoundError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--save', type=Path, help='Read-only character source; copied before the executable opens it.')
    args = parser.parse_args()
    version = release.release_version()
    archive_path = args.archive or ROOT/'dist'/f'{release.APP}-{version}-windows-x64.zip'
    report = release.verify_zip(archive_path)
    report.update(created_utc=datetime.now(timezone.utc).isoformat(), game_executed=False,
                  live_saves_written=False, frozen_smoke=False)
    source_paths = [args.save.resolve(strict=True)] if args.save else find_saves()
    assert source_paths, 'Need one installed source for read-only copy validation.'
    live = {path for source in source_paths for path in source.parent.glob('*.sav')}
    original = {path: digest(path.read_bytes()) for path in live}
    settings_before = registry_snapshot()
    with zipfile.ZipFile(archive_path) as archive:
        checks = []
        prefix = release.APP+'/'
        for name in archive.namelist():
            target = None
            if name.startswith(prefix+'source/') and name.endswith(('.py', '.md', '.txt')):
                target = ROOT/name[len(prefix+'source/'):]
            elif name.startswith((prefix+'_internal/data/', prefix+'_internal/assets/')):
                target = ROOT/name[len(prefix+'_internal/'):]
            if target is not None and target.is_file():
                assert archive.read(name) == target.read_bytes(), name+' differs from current source'
                checks.append(name)
        report['source_data_assets_match_workspace'] = len(checks)
        with tempfile.TemporaryDirectory(prefix='cm_frozen_smoke_') as temporary:
            work = Path(temporary)
            archive.extractall(work)
            executable = work/release.APP/(release.APP+'.exe')
            reader = CArchiveReader(str(executable))
            code = marshal.loads(reader.extract('crimson_editor'))
            expected = compile((ROOT/'crimson_editor.py').read_bytes(), code.co_filename, 'exec',
                               dont_inherit=True, optimize=0)
            assert code == expected, 'Frozen entry differs from current source.'
            pyz = reader.open_embedded_archive('PYZ.pyz')
            modules = []
            for module in sorted(pyz.toc):
                if module == 'crimson' or module.startswith('crimson.'):
                    path = ROOT/'crimson'/('__init__.py' if module == 'crimson' else module.rsplit('.', 1)[-1]+'.py')
                    code = pyz.extract(module)
                    assert compile(path.read_bytes(), code.co_filename, 'exec', dont_inherit=True, optimize=0) == code, module
                    modules.append(module)
            report['frozen_main_matches_source'] = True
            report['frozen_modules_match_source'] = modules
            copy = work/'temporary_saves'
            copy.mkdir()
            source = copy/source_paths[0].name
            raw = source_paths[0].read_bytes()
            source.write_bytes(raw)
            data_dir = work/'isolated_editor_data'
            screenshot = ROOT/'docs/screenshots'/f'frozen-release-{version}.png'
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            env['QT_QPA_PLATFORM'] = 'offscreen'
            process = subprocess.run([str(executable), '--save', str(source), '--data-dir', str(data_dir),
                                      '--smoke-test', '--screenshot', str(screenshot)], cwd=work,
                                     env=env, capture_output=True, timeout=45,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            assert process.returncode == 0, (process.returncode, process.stderr[-2000:])
            assert screenshot.is_file() and screenshot.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
            assert (data_dir/'settings.ini').is_file(), 'Isolated settings were not created.'
            assert source.read_bytes() == raw, 'Smoke changed its temporary input.'
            assert not (data_dir/'backups').exists(), 'Read-only smoke unexpectedly created backup transactions.'
            report.update(frozen_smoke=True, frozen_exit_code=process.returncode,
                          extracted_zip_smoke=True, temporary_source_unchanged=True,
                          isolated_settings=True, screenshot=f'docs/screenshots/frozen-release-{version}.png')
    after = {path: digest(path.read_bytes()) for path in live}
    assert after == original, 'Installed saves changed during smoke; this test never writes them.'
    assert registry_snapshot() == settings_before, 'Shared editor settings changed during isolated smoke.'
    report['shared_settings_unchanged'] = True
    report['live_save_hashes_unchanged'] = [{'filename': path.name, 'sha256': value}
                                            for path, value in sorted(original.items())]
    out = ROOT/'docs'/f'release-validation-{version}.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
