"""Testes sem saves pessoais. Fixtures sintéticas não são saves jogáveis."""
from __future__ import annotations
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from crimson.gvas import SaveDocument, SaveError
from crimson.service import Session, currency_field, currency_status, write_currency, MAX_AMOUNT


def text(s: str, wide: bool = False) -> bytes:
    if wide:
        b = s.encode('utf-16-le') + b'\0\0'
        return struct.pack('<i', -len(b)//2) + b
    b = s.encode('utf-8') + b'\0'
    return struct.pack('<i', len(b)) + b

def tn(name, *args) -> bytes:
    return text(name) + struct.pack('<I', len(args)) + b''.join(args)

def prop(name: str, t: bytes, payload: bytes, flags: int = 0) -> bytes:
    return text(name) + t + struct.pack('<I', len(payload)) + bytes([flags]) + payload

def struct_type(name: str) -> bytes:
    return tn('StructProperty', tn(name, tn('/Script/Inventory')))

def integer(name: str, n: int) -> bytes:
    return prop(name, tn('IntProperty'), struct.pack('<i', n))

def record(asset='IC_GoldCoins', n=1000, package=None, *, float_count=False) -> bytes:
    package = package or '/Game/Data/Inventory/Currency/' + asset
    ap = (prop('PackageName', tn('NameProperty'), text(package))
          + prop('AssetName', tn('NameProperty'), text(asset)) + text('None'))
    count = prop('Count', tn('FloatProperty'), struct.pack('<f', n)) if float_count else integer('Count',n)
    return (prop('AssetPath', struct_type('TopLevelAssetPath'), ap)
            + prop('Item', tn('ObjectProperty'), text(package + '.' + asset)) + count + text('None'))

def fixture(records=None, *, extra=b'', version=8, name='Teste') -> bytes:
    if records is None: records = [record(), record('IC_Souls', 40)]
    header = (b'GVAS' + struct.pack('<IIIHHHI',3,522,1017,5,6,1,167334)
              + text('++CM+release') + struct.pack('<II',3,0)
              + text('/Script/CrimsonMoonNG.SaveGameCharacter') + b'\0')
    inventory = prop('BackpackContents', tn('ArrayProperty',struct_type('InventoryInstanceData')),
                     struct.pack('<i',len(records)) + b''.join(records)) + text('None')
    return (header + prop('CharacterName',tn('StrProperty'),text(name,wide=True))
            + integer('SavedDataVersion',version)
            + prop('SaveGameInventory',struct_type('SaveGameInventory'),inventory)
            + extra + text('None') + b'\0\0\0\0')

class ParserTests(unittest.TestCase):
    def test_read_currency(self):
        d=SaveDocument.from_bytes(fixture())
        self.assertEqual(currency_field(d,'gold')[0],1000)
        self.assertEqual(currency_field(d,'souls')[0],40)
    def test_noop_roundtrip(self):
        b=fixture();self.assertEqual(SaveDocument.from_bytes(b).rebuild(),b)
    def test_unicode_name(self):
        b=fixture(name='Cavaleiro São João 🗡')
        d=SaveDocument.from_bytes(b);self.assertEqual(d.values['CharacterName'],'Cavaleiro São João 🗡')
        self.assertEqual(d.rebuild(),b)
    def test_empty_string_is_preserved(self):
        extra=prop('Empty',tn('StrProperty'),struct.pack('<i',0))
        b=fixture(extra=extra);d=SaveDocument.from_bytes(b)
        self.assertEqual(d.values['Empty'],'');self.assertEqual(d.rebuild(),b)
    def test_unknown_text_preserved(self):
        extra=prop('LoadoutDisplayName',tn('TextProperty'),b'\xff\x80\x01some\0opaque\0text')
        b=fixture(extra=extra);d=SaveDocument.from_bytes(b)
        self.assertEqual(len(d.opaque),1);self.assertEqual(d.rebuild(),b)
        changed,_=write_currency(d,'gold',1001)
        e=SaveDocument.from_bytes(changed)
        self.assertEqual(d.values['LoadoutDisplayName'],e.values['LoadoutDisplayName'])
    def test_unknown_noncritical_property_preserved(self):
        b=fixture(extra=prop('FutureData',tn('FutureProperty'),b'ABC\0\xff'))
        d=SaveDocument.from_bytes(b);new,_=write_currency(d,'gold',1001)
        self.assertEqual(d.values['FutureData'],SaveDocument.from_bytes(new).values['FutureData'])
    def test_every_truncation_is_rejected(self):
        b=fixture()
        for n in range(len(b)):
            with self.subTest(size=n),self.assertRaises(SaveError):SaveDocument.from_bytes(b[:n])
    def test_invalid_magic(self):
        b=bytearray(fixture());b[:4]=b'NOPE'
        with self.assertRaises(SaveError):SaveDocument.from_bytes(bytes(b))
    def test_bad_string_size(self):
        b=bytearray(fixture());b[26:30]=struct.pack('<i',2147483647)
        with self.assertRaises(SaveError):SaveDocument.from_bytes(bytes(b))
    def test_unsupported_engine(self):
        b=bytearray(fixture());b[18:20]=struct.pack('<H',7)
        with self.assertRaises(SaveError):SaveDocument.from_bytes(bytes(b))
    def test_nonzero_trailer(self):
        b=fixture()[:-1]+b'X'
        with self.assertRaises(SaveError):SaveDocument.from_bytes(b)
    def test_unknown_flags(self):
        with self.assertRaises(SaveError):
            SaveDocument.from_bytes(fixture(extra=prop('Flagged',tn('IntProperty'),struct.pack('<i',5),0x80)))
    def test_extensions_refused(self):
        with self.assertRaises(SaveError):
            SaveDocument.from_bytes(fixture(extra=prop('Flagged',tn('IntProperty'),struct.pack('<i',5),4)))
    def test_duplicate_property(self):
        with self.assertRaises(SaveError):SaveDocument.from_bytes(fixture(extra=integer('SavedDataVersion',8)))
    def test_bool_flags(self):
        d=SaveDocument.from_bytes(fixture(extra=prop('Enabled',tn('BoolProperty'),b'',16)))
        self.assertTrue(d.values['Enabled'])
    def test_integer_size_mismatch(self):
        with self.assertRaises(SaveError):SaveDocument.from_bytes(fixture(extra=prop('Bad',tn('IntProperty'),b'\0'*5)))
    def test_negative_array_count(self):
        extra=prop('BadArray',tn('ArrayProperty',tn('IntProperty')),struct.pack('<i',-1))
        with self.assertRaises(SaveError):SaveDocument.from_bytes(fixture(extra=extra))
    def test_native_guid_and_datetime(self):
        extra=prop('Guid',struct_type('Guid'),bytes(range(16)),8)+prop('Time',struct_type('DateTime'),struct.pack('<q',12345),8)
        b=fixture(extra=extra);d=SaveDocument.from_bytes(b)
        self.assertEqual(d.values['Time'],{'ticks':12345});self.assertEqual(d.rebuild(),b)
    def test_native_tag_container(self):
        extra=prop('Tags',struct_type('GameplayTagContainer'),struct.pack('<i',2)+text('A.B')+text('C.D'),8)
        d=SaveDocument.from_bytes(fixture(extra=extra));self.assertEqual(d.values['Tags'],['A.B','C.D'])

class CurrencyTests(unittest.TestCase):
    def setUp(self):self.doc=SaveDocument.from_bytes(fixture())
    def test_one_currency_only(self):
        b,r=write_currency(self.doc,'gold',1234);new=SaveDocument.from_bytes(b)
        self.assertEqual(currency_field(new,'gold')[0],1234)
        self.assertEqual(currency_field(new,'souls')[0],40)
        self.assertEqual(len(r['semantic_changes']),1)
        self.assertTrue(r['reverse_matches_input'])
    def test_souls(self):
        b,r=write_currency(self.doc,'souls',50);new=SaveDocument.from_bytes(b)
        self.assertEqual(currency_field(new,'gold')[0],1000);self.assertEqual(currency_field(new,'souls')[0],50)
    def test_same_value_is_noop(self):
        b,r=write_currency(self.doc,'gold',1000);self.assertEqual(b,self.doc.raw);self.assertEqual(r['changed_offsets'],[])
    def test_reverse_exactly(self):
        b,_=write_currency(self.doc,'gold',1001)
        a,_=write_currency(SaveDocument.from_bytes(b),'gold',1000)
        self.assertEqual(a,self.doc.raw)
    def test_range_rejections(self):
        for value in [-1,MAX_AMOUNT+1,True,12.5,'500',None]:
            with self.subTest(value=value),self.assertRaises(SaveError):write_currency(self.doc,'gold',value)
    def test_range_boundaries(self):
        for n in [0,1,255,256,65535,65536,MAX_AMOUNT]:
            b,_=write_currency(self.doc,'gold',n)
            self.assertEqual(currency_field(SaveDocument.from_bytes(b),'gold')[0],n)
    def test_missing_souls(self):
        d=SaveDocument.from_bytes(fixture([record()]))
        with self.assertRaises(SaveError):write_currency(d,'souls',50)
        self.assertFalse(currency_status(d)['souls']['editable'])
    def test_duplicate_currency(self):
        d=SaveDocument.from_bytes(fixture([record(),record()]))
        with self.assertRaises(SaveError):write_currency(d,'gold',50)
    def test_inconsistent_package(self):
        d=SaveDocument.from_bytes(fixture([record(package='/Game/Dummy/IC_GoldCoins')]))
        with self.assertRaises(SaveError):write_currency(d,'gold',50)
    def test_float_count_refused(self):
        d=SaveDocument.from_bytes(fixture([record(float_count=True)]))
        with self.assertRaises(SaveError):write_currency(d,'gold',50)
    def test_reordered_items_no_fixed_offsets(self):
        d=SaveDocument.from_bytes(fixture([record('Dummy',1),record('IC_Souls',40),record()],name='Nome bem maior'))
        b,r=write_currency(d,'gold',1010)
        self.assertEqual(r['property_path'],'/SaveGameInventory/BackpackContents/2/Count')
        self.assertNotEqual(r['payload_offset'],self.doc.properties[currency_field(self.doc,'gold')[1]].payload_start)
        self.assertEqual(currency_field(SaveDocument.from_bytes(b),'gold')[0],1010)
    def test_currency_name_in_text_is_not_a_record(self):
        extra=prop('Misleading',tn('StrProperty'),text('IC_Souls Count 9000'))
        d=SaveDocument.from_bytes(fixture([record()],extra=extra))
        with self.assertRaises(SaveError):write_currency(d,'souls',9)
    def test_saved_data_version(self):
        d=SaveDocument.from_bytes(fixture(version=9))
        with self.assertRaises(SaveError):write_currency(d,'gold',5)
    def test_unknown_currency(self):
        with self.assertRaises(SaveError):write_currency(self.doc,'xp',5)
    def test_resize_patch_refused(self):
        path=currency_field(self.doc,'gold')[1]
        with self.assertRaises(SaveError):self.doc.rebuild({path:b'\0'*8})

class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.srcdir=self.root/'originais';self.srcdir.mkdir()
        self.src=self.srcdir/'Player_Character_0.sav';self.src.write_bytes(fixture())
        self.bak=self.srcdir/'Player_Character_0.backup.sav';self.bak.write_bytes(fixture())
        self.player=self.srcdir/'Player.sav';self.player.write_bytes(b'COMPANION_NOT_CHANGED')
        self.session=Session.open(self.src);self.out=self.root/'saida_nova'
    def tearDown(self):self.tmp.cleanup()
    def test_export_control(self):
        report=self.session.export(self.out)
        self.assertTrue(report['complete']);self.assertFalse(report['game_load_tested'])
        self.assertEqual((self.out/'save_teste'/self.src.name).read_bytes(),self.src.read_bytes())
    def test_source_and_sibling_backups_unchanged(self):
        snap=dict(self.session.snapshot)
        self.session.export(self.out,currency='gold',amount=1100)
        for n,b in snap.items():
            self.assertEqual((self.srcdir/n).read_bytes(),b)
            self.assertEqual((self.out/'backup_originais'/n).read_bytes(),b)
        self.assertFalse((self.out/'save_teste'/'Player.sav').exists())
        self.assertFalse((self.out/'save_teste'/self.bak.name).exists())
    def test_output_already_exists(self):
        self.out.mkdir();s=self.out/'sentinel';s.write_text('keep')
        with self.assertRaises(SaveError):self.session.export(self.out)
        self.assertEqual(s.read_text(),'keep')
    def test_output_inside_originals(self):
        with self.assertRaises(SaveError):self.session.export(self.srcdir/'saida')
    def test_source_changed_after_open(self):
        self.src.write_bytes(fixture(name='Mudou'))
        with self.assertRaises(SaveError):self.session.export(self.out)
        self.assertFalse(self.out.exists())
    def test_companion_changed_after_open(self):
        self.player.write_bytes(b'CHANGED')
        with self.assertRaises(SaveError):self.session.export(self.out)
    def test_file_added_after_open(self):
        (self.srcdir/'New.sav').write_bytes(b'new')
        with self.assertRaises(SaveError):self.session.export(self.out)
    def test_file_removed_after_open(self):
        self.player.unlink()
        with self.assertRaises(SaveError):self.session.export(self.out)
    def test_backup_source_refused(self):
        with self.assertRaises(SaveError):Session.open(self.bak)
    def test_invalid_operation_produces_no_output(self):
        with self.assertRaises(SaveError):self.session.export(self.out,currency='gold')
        self.assertFalse(self.out.exists())
    def test_manifest_hashes(self):
        from crimson.service import digest
        report=self.session.export(self.out,currency='gold',amount=1001)
        self.assertEqual(report,json.loads((self.out/'manifesto.json').read_text()))
        self.assertEqual(report['source']['sha256'],digest(self.src.read_bytes()))
        self.assertEqual(report['output']['sha256'],digest((self.out/'save_teste'/self.src.name).read_bytes()))
    def test_disk_failure_cleans_only_new_outputs(self):
        sentinel=self.root/'sentinel';sentinel.write_bytes(b'KEEP')
        with patch('crimson.service.os.fsync',side_effect=OSError('simulated')):
            with self.assertRaises(OSError):self.session.export(self.out)
        self.assertEqual(sentinel.read_bytes(),b'KEEP');self.assertFalse(self.out.exists())
        self.assertEqual(self.src.read_bytes(),fixture())
    def test_export_path_symlink_to_originals_refused(self):
        try:(self.root/'link').symlink_to(self.srcdir,target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest('symlink unavailable')
        with self.assertRaises(SaveError):self.session.export(self.root/'link'/'saida')

if __name__=='__main__':unittest.main(verbosity=2)
