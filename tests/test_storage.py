from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from crimson.gvas import SaveDocument,SaveError
from crimson.storage import (EditorSession,TransactionStore,folder_lock,folder_key,find_saves,
                             parse_tasklist,game_processes,no_links)
from crimson.service import digest,currency_field
from helpers import sample,catalogue,fixture

class ProcessTests(unittest.TestCase):
    def test_windows_csv_english_or_portuguese_memory(self):
        s='"System","4","Services","0","1.000 K"\n"CrimsonMoonNG-Win64-Shipping.exe","1552","Console","1","333 K"\n'
        self.assertEqual(game_processes(parse_tasklist(s)),['CrimsonMoonNG-Win64-Shipping.exe'])
    def test_editor_not_the_game(self):self.assertEqual(game_processes(['CrimsonMoonSaveEditor.exe','python.exe','FModel.exe']),[])
    def test_case_insensitive(self):self.assertEqual(game_processes(['CRIMSONMOONNG.EXE']),['CRIMSONMOONNG.EXE'])
    def test_empty_or_invalid_output_fails_closed(self):
        for s in ['', 'ERRO: Acesso negado', '{}']:
            with self.subTest(s=s),self.assertRaises(SaveError):parse_tasklist(s)
    def test_launcher_process(self):self.assertEqual(game_processes(['CrimsonMoon.exe']),['CrimsonMoon.exe'])
    def test_steam_shipping_process_matches_actual_game(self):
        name='CrimsonMoonNGSteam-Win64-Shipping.exe'
        self.assertEqual(game_processes([name]),[name])
    def test_steam_game_case_path_and_executable(self):
        for name in ['CRIMSONMOONNGSTEAM-WIN64-SHIPPING.EXE','CrimsonMoonNGSteam.exe',r'D:\Games\CrimsonMoonNGSteam-Win64-Shipping.exe']:
            with self.subTest(name=name):
                self.assertEqual(game_processes([name]),[name.rsplit('\\',1)[-1]])
    def test_similarly_named_editor_and_tools_are_not_game(self):
        self.assertEqual(game_processes(['CrimsonMoonNGSteamEditor.exe','CrimsonMoonSaveEditor.exe','CrimsonMoonNGSteamTools.exe']),[])

class StorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=catalogue()
    def setUp(self):
        # The application resolves Windows 8.3 aliases; mocks must use the same path.
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.folder=self.root/'saves';self.folder.mkdir();self.src=self.folder/'Player_Character_0.sav'
        self.raw=sample();self.src.write_bytes(self.raw)
        self.gamebak=self.folder/'Player_Character_0.backup.sav';self.gamebak.write_bytes(self.raw)
        self.companion=self.folder/'Player.sav';self.companion.write_bytes(b'PLAYER METADATA')
        self.other=self.folder/'Player_Character_1.sav';self.other.write_bytes(fixture(name='Another slot'))
        self.store=TransactionStore(self.root/'appdata',guard=lambda:None)
        self.session=EditorSession.open(self.src,self.c);self.session.edits.set_currency('souls',20000)
    def tearDown(self):self.tmp.cleanup()
    def test_direct_apply_and_all_original_sav_backups(self):
        r=self.store.apply(self.session)
        self.assertEqual(r['status'],'applied');self.assertTrue(r['verified_in_place'])
        self.assertEqual(currency_field(SaveDocument.load(self.src),'souls')[0],20000)
        b=Path(r['backup_directory'])
        for name,data in self.session.original.snapshot.items():
            self.assertEqual((b/'originais'/name).read_bytes(),data)
            if name!=self.src.name:self.assertEqual((self.folder/name).read_bytes(),data)
        self.assertEqual((b/'proposto'/self.src.name).read_bytes(),self.src.read_bytes())
        self.assertEqual(json.loads((b/'manifesto.json').read_text(encoding='utf-8'))['status'],'applied')
    def test_restore_recovers_exactly_and_backs_up_current(self):
        r=self.store.apply(self.session);edited=self.src.read_bytes()
        rr=self.store.restore(self.src,r['backup_directory'],expected_current_hash=digest(edited))
        self.assertEqual(self.src.read_bytes(),self.raw)
        self.assertEqual((Path(rr['backup_directory'])/'originais'/self.src.name).read_bytes(),edited)
        self.assertEqual(len(self.store.history(self.src)),2)
    def test_restore_does_not_restore_unrelated_slots(self):
        r=self.store.apply(self.session)
        self.other.write_bytes(fixture(name='new other progress'))
        self.store.restore(self.src,r['backup_directory'],expected_current_hash=digest(self.src.read_bytes()))
        self.assertEqual(self.other.read_bytes(),fixture(name='new other progress'))
    def test_source_stale(self):
        self.src.write_bytes(sample(extra=b'' )+b'X')
        with self.assertRaises(SaveError):self.store.apply(self.session)
        self.assertEqual(self.src.read_bytes(),self.raw+b'X')
    def test_sibling_stale(self):
        self.companion.write_bytes(b'updated')
        with self.assertRaises(SaveError):self.store.apply(self.session)
        self.assertEqual(self.src.read_bytes(),self.raw)
    def test_new_or_removed_sibling(self):
        extra=self.folder/'new.sav';extra.write_bytes(b'new')
        with self.assertRaises(SaveError):self.store.apply(self.session)
        extra.unlink();self.companion.unlink()
        with self.assertRaises(SaveError):self.store.apply(self.session)
    def test_game_running_blocks_before_backup(self):
        self.store.guard=lambda:(_ for _ in ()).throw(SaveError('Jogo aberto'))
        with self.assertRaises(SaveError):self.store.apply(self.session)
        self.assertEqual(self.src.read_bytes(),self.raw);self.assertFalse((self.store.base/'backups').exists())
    def test_game_starts_during_preparation(self):
        counter=[0]
        def guard():
            counter[0]+=1
            if counter[0]==2:raise SaveError('Jogo aberto agora')
        self.store.guard=guard
        with self.assertRaises(SaveError):self.store.apply(self.session)
        self.assertEqual(self.src.read_bytes(),self.raw)
        self.assertEqual(self.store.history(self.src)[0]['status'],'aborted_before_replace')
    def test_source_changes_during_preparation(self):
        counter=[0]
        def guard():
            counter[0]+=1
            if counter[0]==2:self.src.write_bytes(fixture(name='game modified'))
        self.store.guard=guard
        with self.assertRaises(SaveError):self.store.apply(self.session)
        self.assertEqual(self.src.read_bytes(),fixture(name='game modified'))
    def test_no_change_not_applied(self):
        self.session.edits.discard()
        with self.assertRaises(SaveError):self.store.apply(self.session)
    def test_repeated_apply_is_stale(self):
        self.store.apply(self.session)
        with self.assertRaises(SaveError):self.store.apply(self.session)
    def test_backup_path_in_save_folder_rejected(self):
        self.store.base=self.folder/'backups'
        with self.assertRaises(SaveError):self.store.apply(self.session)
    def test_renamed_upload_not_written_directly(self):
        path=self.folder/'Player_Character_0(3).sav';path.write_bytes(self.raw)
        s=EditorSession.open(path,self.c);s.edits.set_currency('gold',2000)
        with self.assertRaises(SaveError):self.store.apply(s)
    def test_backup_file_not_opened_as_main(self):
        with self.assertRaises(SaveError):EditorSession.open(self.gamebak,self.c)
    def test_symlink_source_rejected(self):
        p=self.folder/'Player_Character_5.sav'
        try:p.symlink_to(self.src)
        except OSError:self.skipTest('No symlink privilege')
        with self.assertRaises(SaveError):EditorSession.open(p,self.c)
    def test_symlink_parent_rejected(self):
        link=self.root/'linked'
        try:link.symlink_to(self.folder,target_is_directory=True)
        except OSError:self.skipTest('No symlink privilege')
        with self.assertRaises(SaveError):EditorSession.open(link/self.src.name,self.c)
    def test_disk_full_before_write(self):
        with patch('crimson.storage.shutil.disk_usage',return_value=type('Disk',(),{'free':0})()):
            with self.assertRaises(SaveError):self.store.apply(self.session)
        self.assertEqual(self.src.read_bytes(),self.raw)
    def test_fsync_failure_preserves_original(self):
        with patch('crimson.storage.os.fsync',side_effect=OSError('disk fail')):
            with self.assertRaises(OSError):self.store.apply(self.session)
        self.assertEqual(self.src.read_bytes(),self.raw)
    def test_replace_permission_failure_preserves_original(self):
        replace=os.replace
        def fail(src,dst):
            if Path(dst)==self.src:raise PermissionError('locked by another process')
            return replace(src,dst)
        with patch('crimson.storage.os.replace',side_effect=fail):
            with self.assertRaises(PermissionError):self.store.apply(self.session)
        self.assertEqual(self.src.read_bytes(),self.raw)
        self.assertFalse(list(self.folder.glob('*.tmp')))
    def test_backup_write_failure_never_installs(self):
        from crimson.storage import _put_new
        def fail(path,data):
            if path.name=='Player.sav':raise OSError('write backup failed')
            return _put_new(path,data)
        with patch('crimson.storage._put_new',side_effect=fail):
            with self.assertRaises(OSError):self.store.apply(self.session)
        self.assertEqual(self.src.read_bytes(),self.raw)
    def test_journal_final_failure_reports_applied_with_warning(self):
        from crimson.storage import _write_journal
        def fail(path,data):
            if data.get('status')=='applied':raise OSError('journal failure')
            return _write_journal(path,data)
        with patch('crimson.storage._write_journal',side_effect=fail):r=self.store.apply(self.session)
        self.assertEqual(r['status'],'applied');self.assertIn('warning',r)
        self.assertEqual(digest(self.src.read_bytes()),r['output']['sha256'])
        self.assertEqual(self.store.history(self.src)[0]['status'],'prepared')
    def test_post_replace_external_write_not_overwritten_by_rollback(self):
        replace=os.replace;external=fixture(name='later progress')
        def modify(src,dst):
            result=replace(src,dst)
            if Path(dst)==self.src:self.src.write_bytes(external)
            return result
        with patch('crimson.storage.os.replace',side_effect=modify):
            with self.assertRaises(SaveError):self.store.apply(self.session)
        self.assertEqual(self.src.read_bytes(),external)
        self.assertEqual(self.store.history(self.src)[0]['status'],'uncertain_after_replace')
    def test_restore_tampered_backup_refused(self):
        r=self.store.apply(self.session);before=self.src.read_bytes()
        (Path(r['backup_directory'])/'originais'/self.src.name).write_bytes(fixture())
        with self.assertRaises(SaveError):self.store.restore(self.src,r['backup_directory'],expected_current_hash=digest(before))
        self.assertEqual(self.src.read_bytes(),before)
    def test_restore_wrong_folder_refused(self):
        r=self.store.apply(self.session)
        with self.assertRaises(SaveError):self.store.restore(self.src,self.root,expected_current_hash=digest(self.src.read_bytes()))
    def test_restore_changed_confirmation_hash(self):
        r=self.store.apply(self.session)
        with self.assertRaises(SaveError):self.store.restore(self.src,r['backup_directory'],expected_current_hash='0'*64)
    def test_restore_corrupt_current_file(self):
        r=self.store.apply(self.session);self.src.write_bytes(b'CORRUPT')
        self.store.restore(self.src,r['backup_directory'],expected_current_hash=digest(b'CORRUPT'))
        self.assertEqual(self.src.read_bytes(),self.raw)
    def test_same_folder_os_lock(self):
        with folder_lock(self.store.base,folder_key(self.folder)):
            with self.assertRaises(SaveError):
                with folder_lock(self.store.base,folder_key(self.folder)):pass
    def test_lock_released_after_exception(self):
        try:
            with folder_lock(self.store.base,'test'):raise ValueError()
        except ValueError:pass
        with folder_lock(self.store.base,'test'):pass
    def test_history_filters_character(self):
        self.store.apply(self.session);self.assertEqual(self.store.history(self.other),[])
    def test_export_preserves_original(self):
        out=self.root/'export';report=self.store.export(self.session,out)
        self.assertTrue(report['complete']);self.assertEqual(self.src.read_bytes(),self.raw)
        self.assertEqual(currency_field(SaveDocument.load(out/'save_teste'/self.src.name),'souls')[0],20000)
        self.assertFalse((out/'INCOMPLETO.txt').exists())
    def test_export_existing_output_refused(self):
        with self.assertRaises(SaveError):self.store.export(self.session,self.folder)
    def test_export_in_source_folder_refused(self):
        with self.assertRaises(SaveError):self.store.export(self.session,self.folder/'export')
    def test_detect_ignores_backups_and_other_files(self):
        (self.folder/'backup_personal').mkdir();(self.folder/'backup_personal'/'Player_Character_9.sav').write_bytes(self.raw)
        self.assertEqual(set(find_saves(self.folder)),{self.src,self.other})
    def test_detect_user_subfolders(self):
        user=self.folder/'123456789';user.mkdir();p=user/'Player_Character_2.sav';p.write_bytes(self.raw)
        self.assertIn(p,find_saves(self.folder))
    def test_discovery_missing_root(self):self.assertEqual(find_saves(self.root/'nope'),[])

if __name__=='__main__':unittest.main(verbosity=2)
