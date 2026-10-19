"""Names and existing stack counts: synthetic saves and temporary transactions."""
from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest

from helpers import catalogue, gear_record, sample as equipment_sample
from test_core import fixture, prop, record, text, tn
from crimson.extras import (MAX_NAME_UNITS, STACK_ITEMS, character_name_status,
                            stack_items, write_character_name, write_stack_count)
from crimson.gvas import SaveDocument, SaveError
from crimson.service import digest
from crimson.storage import EditorSession, TransactionStore, find_saves
from crimson.writer import edit_fields


def stack_fixture(path=None, *, count=3, slot=None, slot_index=0, extra=b''):
    path = path or next(iter(STACK_ITEMS))
    definition = STACK_ITEMS.get(path, {'slot': 'Consumable'})
    package, asset = path.rsplit('.', 1)
    item = {'package_name': package, 'asset_name': asset, 'object_path': path}
    block = gear_record(item, slot=slot or definition['slot'], index=slot_index,
                        count=count, runes=True)
    return fixture([record(), record('IC_Souls', 40), block], extra=extra)


class CharacterNameTests(unittest.TestCase):
    def doc(self, name='Original'):
        return SaveDocument.from_bytes(fixture(name=name,
            extra=prop('UnknownLabel', tn('TextProperty'), b'\xffopaque\0')))

    def test_status_reports_existing_typed_field(self):
        status = character_name_status(self.doc())
        self.assertEqual(status['value'], 'Original')
        self.assertEqual(status['max_units'], MAX_NAME_UNITS)
        self.assertTrue(status['editable'])

    def test_ascii_unicode_and_emoji_rename_changes_only_name(self):
        document = self.doc()
        for name in ['Knight', 'São João', '月の騎士', 'Nephilim 🗡', 'A'*32, '🗡'*16]:
            with self.subTest(name=name):
                raw, report = write_character_name(document, name)
                parsed = SaveDocument.from_bytes(raw)
                expected = deepcopy(document.values)
                expected['CharacterName'] = name
                self.assertEqual(parsed.values, expected)
                self.assertTrue(report['reverse_matches_input'])
                self.assertEqual(write_character_name(parsed, 'Original')[0], document.raw)

    def test_empty_whitespace_controls_invisibles_and_invalid_types_refused(self):
        document = self.doc()
        for name in ['', ' ', ' leading', 'trailing ', 'a\nb', 'a\tb', 'a\0b',
                     '\u200bhidden', '\ud800', None, 1, True, [], {}]:
            with self.subTest(name=repr(name)), self.assertRaises(SaveError):
                write_character_name(document, name)

    def test_length_counts_utf16_units(self):
        for name in ['A'*33, '🗡'*17, 'A'*31+'🗡']:
            with self.subTest(name=name), self.assertRaises(SaveError):
                write_character_name(self.doc(), name)

    def test_noop_keeps_original_encoding_and_bytes(self):
        document = self.doc('São João')
        raw, report = write_character_name(document, 'São João')
        self.assertEqual(raw, document.raw)
        self.assertEqual(report['semantic_changes'], [])

    def test_missing_wrong_type_flags_and_inconsistent_field_refused(self):
        for change in ['missing', 'kind', 'flags', 'inconsistent']:
            document = self.doc()
            original = document.properties['/CharacterName']
            if change == 'missing':
                del document.properties['/CharacterName']
            elif change == 'kind':
                document.properties['/CharacterName'] = replace(original, type=replace(original.type, name='NameProperty'))
            elif change == 'flags':
                document.properties['/CharacterName'] = replace(original, flags=16)
            else:
                document.values['CharacterName'] = 'Different'
            with self.subTest(change=change), self.assertRaises(SaveError):
                write_character_name(document, 'New name')

    def test_other_profile_version_is_not_editable(self):
        with self.assertRaises(SaveError):
            write_character_name(SaveDocument.from_bytes(fixture(version=9)), 'Name')


class StackCountTests(unittest.TestCase):
    def doc(self, **kwargs):
        return SaveDocument.from_bytes(stack_fixture(**kwargs))

    def test_all_three_observed_references_are_supported(self):
        for path in STACK_ITEMS:
            with self.subTest(path=path):
                rows = stack_items(self.doc(path=path))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['index'], 2)
                self.assertTrue(rows[0]['editable'])
                self.assertFalse(rows[0]['game_capacity_known'])

    def test_count_edit_preserves_entire_instance_and_other_trees(self):
        for path in STACK_ITEMS:
            document = self.doc(path=path)
            for count in [1, 7, 15]:
                with self.subTest(path=path, count=count):
                    raw, report = write_stack_count(document, 2, count)
                    parsed = SaveDocument.from_bytes(raw)
                    expected = deepcopy(document.values)
                    expected['SaveGameInventory']['BackpackContents'][2]['Count'] = count
                    self.assertEqual(parsed.values, expected)
                    self.assertTrue(report['reverse_matches_input'])
                    self.assertEqual(write_stack_count(parsed, 2, 3)[0], document.raw)

    def test_reserved_stack_is_supported_without_moving_it(self):
        document = self.doc(slot='All', slot_index=-1)
        raw, _ = write_stack_count(document, 2, 15)
        entry = SaveDocument.from_bytes(raw).values['SaveGameInventory']['BackpackContents'][2]
        self.assertEqual((entry['EquipmentSlot'], entry['EquipmentSlotIndex']), ('EEquipmentSlot::All', -1))

    def test_count_zero_negative_too_large_bool_float_and_text_refused(self):
        for count in [0, -1, 16, 2_147_483_647, True, 1.0, '15', None]:
            with self.subTest(count=count), self.assertRaises(SaveError):
                write_stack_count(self.doc(), 2, count)

    def test_equipment_currency_flasks_and_unknown_items_are_not_stacks(self):
        equipment = SaveDocument.from_bytes(equipment_sample())
        for index in [0, 1, 2]:
            with self.subTest(index=index), self.assertRaises(SaveError):
                write_stack_count(equipment, index, 2)
        for path in ['/Game/Data/Inventory/Potions/Flasks/IIF_HealthFlask.IIF_HealthFlask',
                     '/Game/Data/Inventory/Consumables/IICo_Unknown.IICo_Unknown']:
            with self.subTest(path=path), self.assertRaises(SaveError):
                write_stack_count(self.doc(path=path), 2, 2)

    def test_bad_indices_and_wrong_profile_rejected(self):
        for index in [-1, 3, True, 2.0, '2', None]:
            with self.subTest(index=index), self.assertRaises(SaveError):
                write_stack_count(self.doc(), index, 2)
        with self.assertRaises(SaveError):
            write_stack_count(SaveDocument.from_bytes(fixture(version=9)), 0, 2)

    def test_asset_mismatch_blocks_candidate_in_listing_and_writer(self):
        document = self.doc()
        raw, _ = edit_fields(document, {'/SaveGameInventory/BackpackContents/2/AssetPath/AssetName': 'IICo_Other'})
        changed = SaveDocument.from_bytes(raw)
        rows = stack_items(changed)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]['editable'])
        self.assertTrue(rows[0]['reason'])
        with self.assertRaises(SaveError):
            write_stack_count(changed, 2, 2)

    def test_wrong_slot_and_bad_slot_indices_refused(self):
        for slot, index in [('Head', 0), ('All', 0), ('Consumable', -1)]:
            with self.subTest(slot=slot, index=index), self.assertRaises(SaveError):
                write_stack_count(self.doc(slot=slot, slot_index=index), 2, 2)

    def test_wrong_tag_type_flags_and_enum_refused(self):
        for change in ['kind', 'flags', 'enum']:
            document = self.doc()
            path = '/SaveGameInventory/BackpackContents/2/'+('EquipmentSlot' if change == 'enum' else 'Count')
            prop = document.properties[path]
            if change == 'kind':
                document.properties[path] = replace(prop, type=replace(prop.type, name='FloatProperty'))
            elif change == 'flags':
                document.properties[path] = replace(prop, flags=16)
            else:
                document.properties[path] = replace(prop, type=replace(prop.type, inner=()))
            with self.subTest(change=change), self.assertRaises(SaveError):
                write_stack_count(document, 2, 2)

    def test_existing_count_above_guardrail_is_visible_and_preserved_on_no_edit(self):
        document = self.doc(count=500)
        rows = stack_items(document)
        self.assertEqual(rows[0]['count'], 500)
        self.assertTrue(rows[0]['editable'])
        self.assertEqual(document.rebuild(), document.raw)

    def test_noop_keeps_bytes(self):
        document = self.doc()
        raw, report = write_stack_count(document, 2, 3)
        self.assertEqual(raw, document.raw)
        self.assertEqual(report['semantic_changes'], [])


class ExtraTransactionTests(unittest.TestCase):
    def test_name_and_stack_apply_restore_only_in_temp_directory(self):
        raw = stack_fixture()
        with tempfile.TemporaryDirectory(prefix='cm_extras_') as temporary:
            root = Path(temporary)
            folder = root/'saves'; folder.mkdir()
            source = folder/'Player_Character_0.sav'; source.write_bytes(raw)
            player = folder/'Player.sav'; player.write_bytes(b'synthetic account metadata')
            session = EditorSession.open(source, catalogue())
            changed, check = write_character_name(session.edits.document, 'New Name')
            session.edits._record(changed, {'kind': 'character_name', 'label': 'Name'}, check)
            changed, check = write_stack_count(session.edits.document, 2, 15)
            session.edits._record(changed, {'kind': 'stack_count', 'label': 'Stack'}, check)
            self.assertEqual(source.read_bytes(), raw)
            store = TransactionStore(root/'editor_data', guard=lambda: None)
            applied = store.apply(session)
            self.assertEqual(source.read_bytes(), changed)
            self.assertEqual(player.read_bytes(), b'synthetic account metadata')
            store.restore(source, applied['backup_directory'], expected_current_hash=digest(changed))
            self.assertEqual(source.read_bytes(), raw)
            self.assertEqual(player.read_bytes(), b'synthetic account metadata')

    @unittest.skipUnless(os.environ.get('CM_VALIDATE_REAL_SAVES') == '1', 'Opt-in read-only installed-save validation.')
    def test_real_sources_only_edited_in_memory_and_original_hashes_preserved(self):
        paths = find_saves()
        self.assertTrue(paths)
        before = {path: path.read_bytes() for path in paths}
        for path, raw in before.items():
            with self.subTest(source=path.name):
                document = SaveDocument.from_bytes(raw)
                renamed, report = write_character_name(document, 'Validation Knight')
                self.assertTrue(report['reverse_matches_input'])
                self.assertEqual(SaveDocument.from_bytes(renamed).values['CharacterName'], 'Validation Knight')
                rows = [row for row in stack_items(document) if row['editable']]
                self.assertTrue(rows)
                for row in rows:
                    modified, report = write_stack_count(document, row['index'], 15)
                    self.assertTrue(report['reverse_matches_input'])
                    self.assertEqual(SaveDocument.from_bytes(modified).values['SaveGameInventory']['BackpackContents'][row['index']]['Count'], 15)
        self.assertEqual({path: path.read_bytes() for path in paths}, before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
