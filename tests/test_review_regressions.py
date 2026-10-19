"""Extra fail-closed regressions added during pre-delivery review."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from helpers import sample,catalogue
from crimson.gvas import SaveDocument,SaveError
from crimson.editing import equipment_entry,quality_value,loadout_reference
from crimson.storage import TransactionStore,EditorSession
from crimson.service import digest

class ReviewRegressions(unittest.TestCase):
    def test_quality_container_instead_of_text(self):
        for q in [[],{},1,True]:
            with self.subTest(value=q),self.assertRaises(SaveError):quality_value(q)
    def test_equipment_property_type_must_be_known(self):
        from dataclasses import replace
        d=SaveDocument.from_bytes(sample());p='/SaveGameInventory/BackpackContents/2/Item'
        d.properties[p]=replace(d.properties[p],type=replace(d.properties[p].type,name='StrProperty'))
        with self.assertRaises(SaveError):equipment_entry(d,catalogue(),2)
    def test_malformed_loadout_is_not_reported_as_equipped(self):
        d=SaveDocument.from_bytes(sample());d.values['SaveGameInventory']['SelectedCustomLoadout']='unknown future encoding'
        self.assertIsNone(loadout_reference(d,{'EquipmentSlot':'Head'}))
    def test_wrong_backup_json_types(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'saves';folder.mkdir();source=folder/'Player_Character_0.sav';source.write_bytes(sample())
            store=TransactionStore(root/'appdata',guard=lambda:None);session=EditorSession.open(source,catalogue())
            session.edits.set_currency('souls',100);report=store.apply(session)
            tx=Path(report['backup_directory']);original=source.read_bytes()
            for payload in [[],None,{'schema':2,'source':[]}, {'schema':2,'source':{'filename':source.name,'sha256':digest(original)},'created_utc':'now','audit':[]}]:
                (tx/'manifesto.json').write_text(json.dumps(payload),encoding='utf-8')
                self.assertEqual(store.history(source),[])
                with self.assertRaises(SaveError):store.restore(source,tx,expected_current_hash=digest(original))
                self.assertEqual(source.read_bytes(),original)
    def test_restore_via_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'saves';folder.mkdir();source=folder/'Player_Character_0.sav';source.write_bytes(sample())
            store=TransactionStore(root/'appdata',guard=lambda:None);session=EditorSession.open(source,catalogue())
            session.edits.set_currency('souls',100);report=store.apply(session)
            link=root/'alias.sav'
            try:link.symlink_to(source)
            except OSError:self.skipTest('Sem permissão para symlink')
            with self.assertRaises(SaveError):store.restore(link,report['backup_directory'],expected_current_hash=digest(source.read_bytes()))

if __name__=='__main__':unittest.main(verbosity=2)
