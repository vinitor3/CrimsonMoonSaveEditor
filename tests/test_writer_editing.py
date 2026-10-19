import copy
import struct
import unittest
from crimson.gvas import SaveDocument,SaveError
from crimson.writer import edit_fields,splice_payloads,pack_string
from crimson.editing import EditBuffer,ATTRIBUTES,MAX_ATTRIBUTE,equipment_entry,loadout_reference
from crimson.service import currency_field
from crimson.catalogue import QUALITY_LABELS,TYPE_SLOTS
from helpers import sample,catalogue,text,tn,prop,fixture,record

class WriterTests(unittest.TestCase):
    def doc(self,extra=b''):return SaveDocument.from_bytes(sample(extra=extra))
    def test_noop_is_identical(self):
        d=self.doc();self.assertEqual(edit_fields(d,{})[0],d.raw)
    def test_nested_resize_longer_and_shorter(self):
        d=self.doc();path='/SaveGameInventory/BackpackContents/2/ItemQuality'
        for val in ['EScalingQuality::Common','EScalingQuality::Legendary','EScalingQuality::Rare']:
            with self.subTest(value=val):
                raw,r=edit_fields(d,{path:val});new=SaveDocument.from_bytes(raw)
                self.assertEqual(new.properties[path].value,val)
                self.assertEqual(len(raw)-len(d.raw),len(val)-len(d.properties[path].value))
                self.assertTrue(r['reverse_matches_input']);self.assertEqual(new.values['UninterpretedName'],d.values['UninterpretedName'])
                for parent in ['/SaveGameInventory','/SaveGameInventory/BackpackContents']:
                    self.assertEqual(new.properties[parent].size-d.properties[parent].size,len(raw)-len(d.raw))
    def test_nested_resize_multiple_refs(self):
        d=self.doc();base='/SaveGameInventory/BackpackContents/2'
        raw,r=edit_fields(d,{base+'/AssetPath/PackageName':'/Game/Longer/Path/AAAAAAA',base+'/AssetPath/AssetName':'B',base+'/Item':'/Game/Longer/Path/AAAAAAA.B'})
        new=SaveDocument.from_bytes(raw)
        self.assertEqual(new.values['SaveGameInventory']['BackpackContents'][2]['AssetPath']['AssetName'],'B')
        self.assertEqual(len(r['semantic_changes']),3)
    def test_wide_string_encoding_preserved(self):
        d=self.doc();raw,_=edit_fields(d,{'/CharacterName':'Teste São João 🗡'});n=SaveDocument.from_bytes(raw)
        p=n.properties['/CharacterName'];self.assertLess(struct.unpack('<i',raw[p.payload_start:p.payload_start+4])[0],0)
        self.assertEqual(n.values['CharacterName'],'Teste São João 🗡')
    def test_empty_string_zero_encoding_noop(self):
        self.assertEqual(pack_string('',b'\0'*4),b'\0'*4)
    def test_bool_is_in_flags(self):
        d=self.doc();p='/SaveGameInventory/BackpackContents/2/bAutoEquip'
        raw,r=edit_fields(d,{p:False});self.assertEqual(len(raw),len(d.raw));self.assertFalse(SaveDocument.from_bytes(raw).properties[p].value)
        self.assertEqual(sum(x!=y for x,y in zip(raw,d.raw)),1)
    def test_bool_wrong_type(self):
        with self.assertRaises(SaveError):edit_fields(self.doc(),{'/SaveGameInventory/BackpackContents/2/bAutoEquip':1})
    def test_integer_invalid_types_and_bounds(self):
        for x in [True,1.1,'10',2**31,-2**31-1,None]:
            with self.subTest(value=x),self.assertRaises(SaveError):edit_fields(self.doc(),{'/NephilimAttributes/NephilimStrength':x})
    def test_integer_boundaries_codec(self):
        for x in [-2**31,0,2**31-1]:
            raw,_=edit_fields(self.doc(),{'/NephilimAttributes/NephilimStrength':x})
            self.assertEqual(SaveDocument.from_bytes(raw).values['NephilimAttributes']['NephilimStrength'],x)
    def test_string_invalid(self):
        for x in [12,None,'abc\0def']:
            with self.subTest(value=x),self.assertRaises(SaveError):edit_fields(self.doc(),{'/CharacterName':x})
    def test_unknown_property_refused(self):
        with self.assertRaises(SaveError):edit_fields(self.doc(),{'/NotHere':3})
    def test_opaque_edit_refused(self):
        with self.assertRaises(SaveError):edit_fields(self.doc(),{'/UninterpretedName':'oops'})
        with self.assertRaises(SaveError):splice_payloads(self.doc(),{'/UninterpretedName':b'changed'})
    def test_overlapping_patch_refused(self):
        d=self.doc()
        with self.assertRaises(SaveError):splice_payloads(d,{'/SaveGameInventory':b'changed','/SaveGameInventory/BackpackContents':b'another'})
    def test_soft_reference_encoding(self):
        path='/SaveGameInventory/BackpackContents/2/InstanceEquippedEffect'
        v={'PackageName':'/Game/Fake/Test','AssetName':'Test_C','SubPath':''}
        raw,_=edit_fields(self.doc(),{path:v});self.assertEqual(SaveDocument.from_bytes(raw).properties[path].value,v)
    def test_soft_reference_bad_keys(self):
        with self.assertRaises(SaveError):edit_fields(self.doc(),{'/SaveGameInventory/BackpackContents/2/InstanceEquippedEffect':{'PackageName':'bad'}})
    def test_array_reference_edit_same_count(self):
        extra=prop('Preset',tn('ArrayProperty',tn('ObjectProperty')),struct.pack('<i',3)+text('aaa')+text('bb')+text(''))
        d=self.doc(extra);raw,_=edit_fields(d,{'/Preset':['longer path','x','']})
        self.assertEqual(SaveDocument.from_bytes(raw).values['Preset'],['longer path','x',''])
        with self.assertRaises(SaveError):edit_fields(d,{'/Preset':['short']})
    def test_float_exact_and_nan_rejected(self):
        d=self.doc(prop('Float',tn('FloatProperty'),struct.pack('<f',1.0)))
        raw,_=edit_fields(d,{'/Float':1.5});self.assertEqual(SaveDocument.from_bytes(raw).values['Float'],1.5)
        for x in [float('nan'),float('inf'),1e80,True]:
            with self.subTest(value=x),self.assertRaises(SaveError):edit_fields(d,{'/Float':x})

class EditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=catalogue()
    def setUp(self):self.e=EditBuffer(SaveDocument.from_bytes(sample()),self.c)
    def test_currency_legacy_reused(self):
        self.e.set_currency('souls',20000);self.assertEqual(currency_field(self.e.document,'souls')[0],20000)
    def test_each_attribute(self):
        for name in ATTRIBUTES:
            with self.subTest(name=name):self.e.set_attribute(name,55);self.assertEqual(self.e.document.values['NephilimAttributes'][name],55)
    def test_attr_bounds_and_unknown(self):
        for v in [0,-1,MAX_ATTRIBUTE+1,True,1.5]:
            with self.subTest(value=v),self.assertRaises(SaveError):self.e.set_attribute('NephilimStrength',v)
        with self.assertRaises(SaveError):self.e.set_attribute('PlayerLevel_XPCurrency',5)
    def test_all_qualities(self):
        for q in QUALITY_LABELS:
            self.e.set_quality(2,q)
            self.assertEqual(self.e.document.values['SaveGameInventory']['BackpackContents'][2]['ItemQuality'],'EScalingQuality::'+q)
    def test_invalid_quality(self):
        for q in ['Magic','EScalingQuality::Epic',None]:
            with self.subTest(q=q),self.assertRaises(SaveError):self.e.set_quality(2,q)
    def test_replace_head(self):
        dest=self.c.by_asset['IIA_PhoenixPaladin_04_Head']
        before=copy.deepcopy(self.e.document.values['SaveGameInventory']['BackpackContents'][2])
        self.e.replace_equipment(2,dest['object_path'],'Legendary')
        after=self.e.document.values['SaveGameInventory']['BackpackContents'][2]
        for k in set(before)-{'Item','AssetPath','ItemQuality'}:self.assertEqual(before[k],after[k])
        self.assertEqual(after['Item'],dest['object_path'])
    def test_wrong_category_refused(self):
        with self.assertRaises(SaveError):self.e.replace_equipment(2,self.c.by_asset['IIA_PhoenixPaladin_04_Legs']['object_path'])
    def test_invalid_index(self):
        for i in [-1,999,'2',True]:
            with self.subTest(index=i),self.assertRaises(SaveError):self.e.set_quality(i,'Rare')
    def test_reference_not_in_catalog(self):
        with self.assertRaises(SaveError):self.e.replace_equipment(2,'/Game/Fake.Fake')
    def test_special_variants_blocked(self):
        for item in self.c.items:
            if set(item['review_flags']) & {'ftue_variant','angel_weapon_folder'}:
                self.assertIsNotNone(self.c.block_reason(item))
    def test_custom_effect_prevents_swap_but_not_quality(self):
        e=EditBuffer(SaveDocument.from_bytes(sample(effect={'PackageName':'/Game/Test','AssetName':'T','SubPath':''})),self.c)
        with self.assertRaises(SaveError):e.replace_equipment(2,self.c.by_asset['IIA_PhoenixPaladin_04_Head']['object_path'])
        self.assertTrue(e.set_quality(2,'Rare'))
    def test_runes_prevent_swap(self):
        e=EditBuffer(SaveDocument.from_bytes(sample(runes=True)),self.c)
        with self.assertRaises(SaveError):e.replace_equipment(2,self.c.by_asset['IIA_PhoenixPaladin_04_Head']['object_path'])
    def test_special_stability_prevents_swap(self):
        e=EditBuffer(SaveDocument.from_bytes(sample(stability='AlwaysPure')),self.c)
        with self.assertRaises(SaveError):e.replace_equipment(2,self.c.by_asset['IIA_PhoenixPaladin_04_Head']['object_path'])
    def test_inconsistent_item_ref(self):
        raw,_=edit_fields(self.e.document,{'/SaveGameInventory/BackpackContents/2/AssetPath/AssetName':'other'})
        e=EditBuffer(SaveDocument.from_bytes(raw),self.c)
        with self.assertRaises(SaveError):e.set_quality(2,'Rare')
    def test_same_value_does_not_dirty(self):
        self.assertFalse(self.e.set_quality(2,'Epic'));self.assertFalse(self.e.dirty)
    def test_undo_redo_all_restores_bytes(self):
        raw=self.e.document.raw
        self.e.set_currency('gold',1500);self.e.set_attribute('NephilimStrength',25)
        self.e.replace_equipment(2,self.c.by_asset['IIA_PhoenixPaladin_04_Head']['object_path'],'Legendary')
        edited=self.e.document.raw
        for _ in range(3):self.assertTrue(self.e.undo())
        self.assertFalse(self.e.undo());self.assertEqual(raw,self.e.document.raw)
        for _ in range(3):self.assertTrue(self.e.redo())
        self.assertFalse(self.e.redo());self.assertEqual(edited,self.e.document.raw)
    def test_new_change_discards_redo(self):
        self.e.set_quality(2,'Rare');self.e.undo();self.e.set_quality(2,'Common');self.assertFalse(self.e.redo())
    def test_discard(self):
        self.e.set_quality(2,'Rare');self.e.discard();self.assertFalse(self.e.dirty);self.assertFalse(self.e.undo())
    def test_same_slot_must_match_type(self):
        e=EditBuffer(SaveDocument.from_bytes(sample(slot='Legs')),self.c)
        with self.assertRaises(SaveError):e.set_quality(2,'Rare')
    def test_reserve_instance_editable(self):
        e=EditBuffer(SaveDocument.from_bytes(sample(slot='All',index=-1)),self.c)
        self.assertTrue(e.set_quality(2,'Rare'))
    def test_legacy_currency_after_resize_uses_new_offset(self):
        before=currency_field(self.e.document,'souls')[0]
        self.e.set_quality(2,'Legendary');self.e.set_currency('souls',before+10)
        self.assertEqual(currency_field(self.e.document,'souls')[0],before+10)
    def test_audit_marks_game_validation_pending(self):
        self.e.set_quality(2,'Rare');a=self.e.audit()
        self.assertTrue(a['experimental_operations']);self.assertFalse(a['validation']['game_load_tested_for_this_output'])
    def test_each_allowed_definition_roundtrip(self):
        checked=0
        templates={}
        for item in self.c.items:
            if not self.c.block_reason(item):templates.setdefault(item['type'],item)
        for item in self.c.items:
            if self.c.block_reason(item):continue
            with self.subTest(asset=item['asset_name']):
                d=SaveDocument.from_bytes(sample(templates[item['type']]))
                e=EditBuffer(d,self.c)
                e.replace_equipment(2,item['object_path'],'Legendary')
                self.assertEqual(e.document.values['SaveGameInventory']['BackpackContents'][2]['Item'],item['object_path'])
                self.assertTrue(e.audit()['validation']['every_step_reversible'])
                e.discard();self.assertEqual(e.document.raw,d.raw)
                checked+=1
        self.assertEqual(checked,275)

class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=catalogue()
    def test_catalog_count(self):self.assertEqual(len(self.c.items),311)
    def test_accent_search(self):
        from crimson.catalogue import folded
        self.assertEqual(folded('campeao'), folded('CAMPEÃO'))
        self.assertTrue(self.c.search('Champion'))
    def test_multi_word_search(self):self.assertTrue(self.c.search('PhoenixPaladin Legs'))
    def test_effect_search(self):self.assertTrue(self.c.search('GE_Boon_LastLight'))
    def test_missing_values_not_zero(self):
        item=self.c.by_asset['IIA_PhoenixPaladin_04_Legs']
        result=self.c.compare(None,item);self.assertTrue(result)
        self.assertTrue(all(r['before'] is None and r['delta'] is None for r in result))
    def test_explicit_zero_is_compared(self):
        a={'table_rows':{'ItemsAttributesRow':{'raw_row':{'Stats':{'Foo':0}}}}}
        b={'table_rows':{'ItemsAttributesRow':{'raw_row':{'Stats':{'Foo':8}}}}}
        self.assertEqual(self.c.compare(a,b)[0]['delta'],8)
    def test_factors_not_summed(self):
        i=self.c.by_asset['IIW_Champion_Sword_01'];base=self.c.compare(None,i);factor=self.c.compare(None,i,section='ItemFactorAttributesRow')
        self.assertEqual(next(r for r in base if r['key']=='OffensiveStats/BaseAttack')['after'],38)
        self.assertEqual(next(r for r in factor if r['key']=='OffensiveStats/BaseAttack')['after'],.6)
    def test_invalid_section(self):
        with self.assertRaises(SaveError):self.c.compare(None,None,section='FinalDamage')
    def test_same_item_zero_differences(self):
        i=self.c.items[0];self.assertTrue(all(x['delta']==0 for x in self.c.compare(i,i)))
    def test_loadout_missing_returns_none(self):
        d=SaveDocument.from_bytes(sample());self.assertIsNone(loadout_reference(d,{'EquipmentSlot':'EEquipmentSlot::Head'}))

if __name__=='__main__':unittest.main(verbosity=2)
