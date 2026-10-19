"""Release integrity and integrated edits. All writes use temporary directories."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from helpers import catalogue
from test_extended import sample
from crimson.gvas import SaveDocument
from crimson.extended import write_blessing, write_progression
from crimson.service import currency_field, digest
from crimson.storage import EditorSession, TransactionStore, find_saves

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_release', ROOT/'tools'/'package_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)/release.APP
        self.folder.mkdir()

    def populate(self):
        files = {release.APP+'.exe': b'MZsynthetic executable',
                 'README.md': b'Portable editor', 'THIRD_PARTY_NOTICES.md': b'Qt shared libraries',
                 'source/crimson_editor.py': b'print("synthetic source")\n',
                 'source/tools/package_release.py': b'# synthetic build script\n',
                 'LICENSES/Python-LICENSE.txt': b'PSF license',
                 'LICENSES/LGPL-3.0-only.txt': b'Synthetic license fixture',
                 'SOURCES/qtbase-everywhere-src-test.tar.xz': b'synthetic source archive',
                 'SOURCES/pyside-setup-everywhere-src-test.tar.xz': b'synthetic source archive',
                 '_internal/data/game_data.json': b'{"schema":1}'}
        for name, raw in files.items():
            path = self.folder/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    def archive(self, *, extra=None):
        path = self.folder.parent/'release.zip'
        manifest = release.manifest_for(self.folder)
        (self.folder/'release-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        with zipfile.ZipFile(path, 'w') as archive:
            for file in self.folder.rglob('*'):
                if file.is_file():
                    archive.write(file, (Path(release.APP)/file.relative_to(self.folder)).as_posix())
            if extra:
                archive.writestr(*extra)
        return path

    def test_complete_archive_hashes_and_required_components(self):
        self.populate()
        result = release.verify_zip(self.archive())
        self.assertTrue(result['verified'])
        self.assertEqual(result['files'], 10)
        self.assertEqual(len(result['sha256']), 64)

    def test_user_data_and_unsafe_paths_refused(self):
        for name in ['Player_Character_0.sav', 'nested/player.BACKUP.sav', '../escape.txt',
                     '/root.txt', 'C:/app.txt', 'source/__pycache__/editor.pyc',
                     'SaveGames/file.txt', 'backups/manifest.json', 'debug.log', 'test.spec']:
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                release.audit_file(name, b'bytes')

    def test_private_absolute_paths_refused_in_text(self):
        values = [b'path=C:'+b'\\Users\\Someone\\Desktop\\file',
                  b'/'+b'Users/someone/file', b'/'+b'home/someone/file']
        for raw in values:
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                release.audit_file('data/config.json', raw)
        release.audit_file('README.md', b'%LOCALAPPDATA%\\CrimsonMoonSaveEditor')

    def test_same_length_tampering_detected(self):
        self.populate()
        path = self.archive()
        with zipfile.ZipFile(path) as archive:
            contents = {i.filename: archive.read(i) for i in archive.infolist()}
        contents[release.APP+'/README.md'] = b'Forged  editor'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, raw in contents.items():
                archive.writestr(name, raw)
        with self.assertRaises(RuntimeError):
            release.verify_zip(path)

    def test_unlisted_extra_file_detected(self):
        self.populate()
        with self.assertRaises(RuntimeError):
            release.verify_zip(self.archive(extra=(release.APP+'/extra.txt', b'unlisted')))

    def test_duplicate_members_detected(self):
        self.populate()
        with self.assertWarns(UserWarning):
            path = self.archive(extra=(release.APP+'/README.md', b'duplicate'))
        with self.assertRaises(RuntimeError):
            release.verify_zip(path)

    def test_corresponding_sources_required(self):
        self.populate()
        (self.folder/'SOURCES/qtbase-everywhere-src-test.tar.xz').unlink()
        with self.assertRaises(RuntimeError):
            release.verify_zip(self.archive())

    def test_source_text_has_no_personal_paths(self):
        for parent in ('crimson', 'data'):
            for path in (ROOT/parent).rglob('*'):
                if path.is_file() and path.suffix in release.TEXT_SUFFIXES:
                    with self.subTest(path=path.relative_to(ROOT)):
                        release.audit_file(path.relative_to(ROOT).as_posix(), path.read_bytes())


class CatalogReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT/'data/game_data.json').read_text(encoding='utf-8'))

    def test_catalogs_needed_by_frozen_application_exist(self):
        self.assertEqual(self.data['schema'], 1)
        self.assertGreaterEqual(len(self.data['items']), 300)
        self.assertGreaterEqual(len(self.data['blessings']), 90)
        progression = json.loads((ROOT/'data/progression.json').read_text(encoding='utf-8'))
        self.assertEqual(progression['schema'], 1)
        self.assertTrue(progression['stages'])

    def test_every_referenced_icon_is_a_relative_existing_file(self):
        records = list(self.data['items'].values())+self.data['blessings']
        for row in records:
            name = row.get('icon')
            if not name:
                continue
            with self.subTest(id=row['id']):
                path = Path(name)
                self.assertFalse(path.is_absolute())
                self.assertNotIn('..', path.parts)
                self.assertTrue((ROOT/path).is_file())
                self.assertEqual((ROOT/path).read_bytes()[:8], b'\x89PNG\r\n\x1a\n')

    def test_localized_names_and_blessing_references_are_usable(self):
        languages = {row['id'] for row in self.data['languages']}
        self.assertTrue({'pt', 'en'}.issubset(languages))
        self.assertGreaterEqual(len(languages), 8)
        for row in self.data['blessings']:
            with self.subTest(id=row['id']):
                self.assertIn('.Default__GE_Boon_', row['default_object_path'])
                self.assertTrue(row['names'].get('en') or row['names'].get('pt'))


class ExtendedTransactionIntegrationTests(unittest.TestCase):
    def exercise_copy(self, raw: bytes):
        """Apply several editing layers, restore exact bytes, preserve siblings."""
        with tempfile.TemporaryDirectory(prefix='cm_release_test_') as temporary:
            root = Path(temporary)
            saves = root/'saves'
            saves.mkdir()
            source = saves/'Player_Character_0.sav'
            source.write_bytes(raw)
            siblings = {'Player.sav': b'synthetic metadata', 'Player_Character_0.backup.sav': raw}
            for name, content in siblings.items():
                (saves/name).write_bytes(content)
            session = EditorSession.open(source, catalogue())
            amount = currency_field(session.edits.document, 'gold')[0]
            session.edits.set_currency('gold', amount-1 if amount > 0 else 1)
            data, report = write_progression(session.edits.document, {'difficulty': 17, 'stage': 0, 'section': 0})
            session.edits._record(data, {'kind': 'progression', 'label': 'Campaign'}, report)
            catalog = json.loads((ROOT/'data/game_data.json').read_text(encoding='utf-8'))
            boon = next(row for row in catalog['blessings'] if not row.get('experimental'))
            data, report = write_blessing(session.edits.document, boon['effect_path'], quality='Legendary')
            session.edits._record(data, {'kind': 'blessing', 'label': 'Blessing'}, report)
            proposed = session.edits.document.raw
            self.assertTrue(session.edits.audit()['validation']['every_step_reversible'])
            self.assertEqual(source.read_bytes(), raw)
            store = TransactionStore(root/'application_data', guard=lambda: None)
            applied = store.apply(session)
            self.assertEqual(source.read_bytes(), proposed)
            self.assertEqual(SaveDocument.load(source).rebuild(), proposed)
            tx = Path(applied['backup_directory'])
            self.assertEqual((tx/'originais'/source.name).read_bytes(), raw)
            self.assertEqual((tx/'proposto'/source.name).read_bytes(), proposed)
            for name, content in siblings.items():
                self.assertEqual((saves/name).read_bytes(), content)
                self.assertEqual((tx/'originais'/name).read_bytes(), content)
            store.restore(source, tx, expected_current_hash=digest(proposed))
            self.assertEqual(source.read_bytes(), raw)
            for name, content in siblings.items():
                self.assertEqual((saves/name).read_bytes(), content)

    def test_currency_campaign_blessing_apply_restore_in_temporary_copy(self):
        self.exercise_copy(sample(effects=[]))

    @unittest.skipUnless(os.environ.get('CM_VALIDATE_REAL_SAVES') == '1',
                         'Opt-in read-only installed-save validation; set CM_VALIDATE_REAL_SAVES=1.')
    def test_installed_sources_unchanged_after_temporary_copy_validation(self):
        paths = find_saves()
        self.assertTrue(paths, 'No character saves found in the standard local save folder.')
        before = {p: p.read_bytes() for p in paths}
        try:
            for path, raw in before.items():
                with self.subTest(source=path.name):
                    self.assertEqual(SaveDocument.from_bytes(raw).rebuild(), raw)
                    self.exercise_copy(raw)
        finally:
            self.assertEqual({p: digest(p.read_bytes()) for p in paths},
                             {p: digest(raw) for p, raw in before.items()},
                             'Installed saves changed externally during validation; test never writes to them.')


if __name__ == '__main__':
    unittest.main(verbosity=2)
