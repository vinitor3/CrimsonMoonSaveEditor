"""Offscreen Qt integration tests with synthetic saves and isolated settings."""
from __future__ import annotations

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from helpers import sample as gear_sample, catalogue, gear_record
from test_core import fixture, integer, prop, record, text, tn
from test_extended import sample as run_sample
from crimson.gvas import SaveDocument
from crimson.service import currency_field
from crimson.writer import edit_fields, splice_payloads
from crimson_editor import EditorWindow, STYLE


class MemorySettings:
    IniFormat = 1
    def __init__(self, *args):
        self.arguments = args
        self.values = {'language': 'pt'}
    def value(self, key, default=None):
        return self.values.get(key, default)
    def setValue(self, key, value):
        self.values[key] = value


def complete_sample():
    document = SaveDocument.from_bytes(run_sample(effects=[]))
    extra = b''.join(document.raw[document.properties[path].start:document.properties[path].end]
                     for path in ['/WorldRunState', '/PlayerGameplayEffects'])
    return gear_sample(extra=extra)


def feature_sample(*, mission=False, name='Teste', stack_count=3):
    catalog = catalogue()
    source = SaveDocument.from_bytes(complete_sample())
    extra = b''.join(source.raw[p.start:p.end] for p in source.properties.values()
                     if p.path.count('/') == 1 and p.name not in
                     {'CharacterName', 'SavedDataVersion', 'SaveGameInventory'})
    def utility(path, slot, count):
        package, asset = path.rsplit('.', 1)
        return gear_record({'object_path': path, 'package_name': package, 'asset_name': asset},
                           slot=slot, count=count)
    records = [record(), record('IC_Souls', 40),
               gear_record(catalog.by_asset['IIA_PhoenixPaladin_01_Head']),
               gear_record(catalog.by_asset['IIW_Apostate_Sword_01'], slot='RightHand', index=0),
               gear_record(catalog.by_asset['IIW_Polearm_01'], slot='RightHand', index=1),
               utility('/Game/Data/Inventory/Consumables/IICo_OathboundOil.IICo_OathboundOil', 'Consumable', stack_count),
               utility('/Game/Data/Inventory/Potions/Flasks/IIF_HealthFlask.IIF_HealthFlask', 'HealthFlask', 4)]
    raw = fixture(records, extra=extra, name=name)
    if mission:
        document = SaveDocument.from_bytes(raw)
        p = document.properties['/WorldRunState']
        payload = document.raw[p.payload_start:p.end]
        assert payload.endswith(text('None'))
        payload = payload[:-len(text('None'))]+integer('CurrentManualMission', 0)+prop(
            'bPlayerStartedMission', tn('BoolProperty'), b'', 16)+text('None')
        raw = splice_payloads(document, {'/WorldRunState': payload})
    return raw


class QtIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.app.setStyleSheet(STYLE)
        if not QFontDatabase.families():
            for name in ['segoeui.ttf', 'segoeuib.ttf', 'georgia.ttf']:
                path = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'/name
                if path.is_file():
                    QFontDatabase.addApplicationFont(str(path))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cm_qt_test_')
        self.root = Path(self.temp.name)
        self.saves = self.root/'saves'
        self.saves.mkdir()
        self.source = self.saves/'Player_Character_0.sav'
        self.raw = complete_sample()
        self.source.write_bytes(self.raw)
        self.game_backup = self.saves/'Player_Character_0.backup.sav'
        self.game_backup.write_bytes(self.raw)
        self.messages = []
        self.patches = [patch('crimson_editor.QSettings', MemorySettings),
                        patch('crimson_editor.find_saves', return_value=[]),
                        patch('crimson_editor.QMessageBox.warning', side_effect=lambda *a: self.messages.append(a)),
                        patch('crimson_editor.QMessageBox.information', return_value=QMessageBox.Ok),
                        patch('crimson_editor.QMessageBox.question', return_value=QMessageBox.Yes)]
        for value in self.patches:
            value.start()
        self.window = EditorWindow(self.source, self.root/'editor_data')
        self.window.store.guard = lambda: None
        self.window.show()
        self.app.processEvents()
        self.assertEqual(self.messages, [], 'Loading the synthetic save must not report an error.')

    def tearDown(self):
        self.window.session.edits.discard()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        for value in reversed(self.patches):
            value.stop()
        self.temp.cleanup()

    def choose_boon(self, identifier='LastLight'):
        boon = next(b for b in self.window.boons() if b['id'] == identifier)
        self.window.boon_search.setText(boon['names']['pt'])
        self.window.boon_list.setCurrentRow(0)
        self.window.boon_changed()
        return boon

    def load_scene(self, raw):
        self.raw = raw
        self.source.write_bytes(raw)
        self.game_backup.write_bytes(raw)
        self.window.open_path(self.source, False)
        self.app.processEvents()

    def test_load_is_read_only_and_values_are_displayed(self):
        self.assertIsNotNone(self.window.session)
        self.assertEqual(self.window.entry_index, 2)
        self.assertEqual(self.window.currencies['souls'].value(), 40)
        self.assertEqual(self.window.inventory.count(), 1)
        self.assertGreater(self.window.item_list.count(), 1)
        self.assertFalse(self.window.apply_button.isEnabled())
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertFalse((self.root/'editor_data'/'backups').exists())
        self.assertEqual(self.window.settings.arguments,
                         (str(self.root/'editor_data'/'settings.ini'), MemorySettings.IniFormat))

    def test_all_pages_render_to_nonempty_images(self):
        for page in range(5):
            with self.subTest(page=page):
                self.window.navigate(page)
                self.app.processEvents()
                pixmap = self.window.grab()
                self.assertFalse(pixmap.isNull())
                self.assertGreater(pixmap.width(), 1000)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_currency_prepare_undo_redo_stays_in_memory(self):
        self.window.currencies['gold'].setValue(5678)
        self.window.currencies['souls'].setValue(9876)
        self.window.prepare_currencies()
        self.assertEqual(self.messages, [])
        self.assertEqual(currency_field(self.window.session.edits.document, 'souls')[0], 9876)
        self.assertTrue(self.window.apply_button.isEnabled())
        self.window.history_action('undo')
        self.assertEqual(currency_field(self.window.session.edits.document, 'souls')[0], 40)
        self.window.history_action('redo')
        self.assertEqual(currency_field(self.window.session.edits.document, 'souls')[0], 9876)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_equipment_tooltip_and_comparison_have_real_content(self):
        current = self.window.item_list.currentItem()
        self.assertIsNotNone(current)
        self.assertFalse(current.icon().isNull())
        self.assertIn(self.window.name(self.window.candidate_path), current.toolTip())
        self.assertIn(self.window.rich['labels']['pt']['SlashingDefense'], current.toolTip())
        self.assertGreater(self.window.comparison.rowCount(), 0)
        self.window.item_search.setText('Apostate')
        self.assertGreater(self.window.item_list.count(), 0)
        self.window.item_list.setCurrentRow(0)
        self.window.candidate_changed()
        self.assertTrue(self.window.replace_button.isEnabled())
        self.assertIn('→', self.window.compare_names.text())

    def test_quality_and_replacement_preserve_instance_fields(self):
        self.window.gear_quality.setCurrentIndex(self.window.gear_quality.findData('Legendary'))
        self.window.quality_only()
        entry = self.window.session.edits.document.values['SaveGameInventory']['BackpackContents'][2]
        self.assertEqual(entry['ItemQuality'], 'EScalingQuality::Legendary')
        before = entry.copy()
        self.window.item_search.setText('Apostate')
        self.window.item_list.setCurrentRow(0)
        self.window.candidate_changed()
        chosen = self.window.candidate_path
        self.window.replace_item()
        self.assertEqual(self.messages, [])
        after = self.window.session.edits.document.values['SaveGameInventory']['BackpackContents'][2]
        self.assertEqual(after['Item'], chosen)
        for key in ['InstanceId', 'EquipmentSlot', 'EquipmentSlotIndex', 'SlottedRunes']:
            self.assertEqual(after[key], before[key])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_blessing_add_tooltip_remove_and_exact_undo(self):
        boon = self.choose_boon()
        self.assertTrue(self.window.add_boon_button.isEnabled())
        self.window.add_boon()
        self.assertEqual(self.messages, [])
        self.assertEqual(sum(bool(self.window.active_list.item(i).data(Qt.UserRole)) for i in range(self.window.active_list.count())), 1)
        item = self.window.active_list.item(0)
        self.assertIn(boon['names']['pt'], item.toolTip())
        self.window.active_list.setCurrentRow(0)
        self.window.active_changed()
        self.assertTrue(self.window.remove_boon_button.isEnabled())
        self.window.remove_boon()
        self.assertEqual(sum(bool(self.window.active_list.item(i).data(Qt.UserRole)) for i in range(self.window.active_list.count())), 0)
        self.assertEqual(self.window.session.edits.document.raw, self.raw)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_progression_prepare_uses_valid_stage_section(self):
        self.window.stage.setCurrentIndex(1)
        self.window.populate_sections()
        self.assertEqual(self.window.section.count(), 1)
        self.window.difficulty.setValue(21)
        self.window.prepare_progression()
        self.assertEqual(self.messages, [])
        state = self.window.session.edits.document.values['WorldRunState']
        self.assertEqual((state['CurrentManualStage'], state['CurrentManualSection'], state['UserChosenDifficulty']),
                         (1, 0, 21))
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_language_switch_preserves_pending_edits(self):
        self.window.currencies['gold'].setValue(1234)
        self.window.prepare_currencies()
        raw = self.window.session.edits.document.raw
        self.window.language.setCurrentIndex(self.window.language.findData('en'))
        self.app.processEvents()
        self.assertEqual(self.window.lang, 'en')
        self.assertEqual(self.window.session.edits.document.raw, raw)
        self.assertEqual(self.window.currencies['gold'].value(), 1234)
        self.assertEqual(self.window.language.count(), 8)
        self.assertTrue(self.window.apply_button.isEnabled())

    def test_apply_and_restore_with_verified_history_in_temporary_folder(self):
        self.window.currencies['souls'].setValue(54321)
        self.window.prepare_currencies()
        with patch('crimson_editor.QDialog.exec', return_value=QDialog.Accepted):
            self.window.apply()
        self.assertEqual(self.messages, [])
        self.assertEqual(currency_field(SaveDocument.load(self.source), 'souls')[0], 54321)
        self.assertEqual(self.game_backup.read_bytes(), self.raw)
        self.assertFalse(self.window.apply_button.isEnabled())
        self.assertEqual(self.window.backup_list.count(), 1)
        self.window.backup_list.setCurrentRow(0)
        self.window.restore()
        self.assertEqual(self.messages, [])
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(self.game_backup.read_bytes(), self.raw)

    def test_game_running_guard_rejection_keeps_source_unchanged(self):
        from crimson.gvas import SaveError
        self.window.currencies['souls'].setValue(2000)
        self.window.prepare_currencies()
        def reject():
            raise SaveError('Game is running')
        self.window.store.guard = reject
        with patch('crimson_editor.QDialog.exec', return_value=QDialog.Accepted):
            self.window.apply()
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertTrue(self.window.session.edits.dirty)

    def test_open_second_save_can_be_cancelled_without_losing_edits(self):
        self.window.currencies['souls'].setValue(2000)
        self.window.prepare_currencies()
        second = self.saves/'Player_Character_1.sav'
        second.write_bytes(self.raw)
        before = self.window.session.edits.document.raw
        with patch('crimson_editor.QMessageBox.question', return_value=QMessageBox.No):
            self.window.open_path(second)
        self.assertEqual(self.window.session.source, self.source)
        self.assertEqual(self.window.session.edits.document.raw, before)

    def test_batch_failure_at_history_limit_rolls_back_every_change(self):
        edits = self.window.session.edits
        for value in range(100, 149):
            edits.set_currency('gold', value)
        self.window.refresh()
        before = edits.document.raw
        self.window.currencies['gold'].setValue(500)
        self.window.currencies['souls'].setValue(600)
        self.window.prepare_currencies()
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(edits.document.raw, before)
        self.assertEqual(len(edits.operations), 49)
        self.assertEqual(self.window.currencies['gold'].value(), 148)
        self.assertEqual(self.window.currencies['souls'].value(), 40)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_existing_values_above_editor_limits_are_not_silently_reduced(self):
        from crimson.writer import edit_fields
        document = SaveDocument.from_bytes(self.raw)
        _, gold_path = currency_field(document, 'gold')
        changed, _ = edit_fields(document, {gold_path: 20_000_000,
            '/NephilimAttributes/NephilimStrength': 1500,
            '/WorldRunState/UserChosenDifficulty': 150})
        self.source.write_bytes(changed)
        self.window.open_path(self.source, False)
        self.assertEqual(self.window.currencies['gold'].value(), 20_000_000)
        self.assertEqual(self.window.attributes['NephilimStrength'].value(), 1500)
        self.assertEqual(self.window.difficulty.value(), 150)
        self.window.currencies['souls'].setValue(700)
        self.window.prepare_currencies()
        self.window.attributes['NephilimDexterity'].setValue(20)
        self.window.prepare_attributes()
        self.window.stage.setCurrentIndex(1)
        self.window.populate_sections()
        self.window.prepare_progression()
        self.assertEqual(self.messages, [])
        result = self.window.session.edits.document
        self.assertEqual(currency_field(result, 'gold')[0], 20_000_000)
        self.assertEqual(currency_field(result, 'souls')[0], 700)
        self.assertEqual(result.values['NephilimAttributes']['NephilimStrength'], 1500)
        self.assertEqual(result.values['NephilimAttributes']['NephilimDexterity'], 20)
        self.assertEqual(result.values['WorldRunState']['UserChosenDifficulty'], 150)
        self.assertEqual(result.values['WorldRunState']['CurrentManualStage'], 1)
        self.assertEqual(self.source.read_bytes(), changed)

    def test_five_skulls_use_exact_game_values_and_preserve_original_custom_value(self):
        document = SaveDocument.from_bytes(self.raw)
        raw, _ = edit_fields(document, {'/WorldRunState/UserChosenDifficulty': 25})
        self.load_scene(raw)
        self.assertEqual(self.window.difficulty.value(), 25)
        self.assertIn('25', self.window.difficulty.caption.text())
        self.assertEqual(len(self.window.difficulty.buttons), 5)
        self.window.prepare_progression()
        self.assertEqual(self.messages, [])
        self.assertEqual(self.window.session.edits.document.raw, raw)
        for button, expected in zip(self.window.difficulty.buttons, [0, 15, 30, 45, 60]):
            button.click()
            self.assertEqual(self.window.difficulty.value(), expected)
        self.window.prepare_progression()
        self.assertEqual(self.window.session.edits.document.values['WorldRunState']['UserChosenDifficulty'], 60)
        self.assertEqual(self.source.read_bytes(), raw)

    def test_fifth_path_card_maps_to_stage_one_section_zero_preserving_custom_difficulty(self):
        document = SaveDocument.from_bytes(self.raw)
        raw, _ = edit_fields(document, {'/WorldRunState/UserChosenDifficulty': 25})
        self.load_scene(raw)
        self.assertEqual(self.window.journey_pairs, [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0)])
        self.assertEqual(self.window.journey_select.count(), 5)
        self.window.path_buttons[4].click()
        self.assertEqual((self.window.stage.currentData(), self.window.section.currentData()), (1, 0))
        self.window.prepare_progression()
        self.assertEqual(self.messages, [])
        state = self.window.session.edits.document.values['WorldRunState']
        self.assertEqual((state['CurrentManualStage'], state['CurrentManualSection'], state['UserChosenDifficulty']), (1, 0, 25))
        self.assertEqual(self.source.read_bytes(), raw)

    def test_optional_mission_choice_edits_existing_index_without_changing_active_flag(self):
        self.load_scene(feature_sample(mission=True))
        self.window.path_buttons[0].click()
        self.assertTrue(self.window.mission_choice.isEnabled())
        self.assertEqual(self.window.mission_choice.count(), 2)
        self.window.mission_choice.setCurrentIndex(self.window.mission_choice.findData(1))
        self.window.prepare_progression()
        self.assertEqual(self.messages, [])
        state = self.window.session.edits.document.values['WorldRunState']
        self.assertEqual((state['CurrentManualStage'], state['CurrentManualSection'], state['CurrentManualMission']), (0, 0, 1))
        self.assertTrue(state['bPlayerStartedMission'])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_mission_choice_tracks_saved_index_after_undo_and_redo(self):
        self.load_scene(feature_sample(mission=True))
        self.window.mission_choice.setCurrentIndex(self.window.mission_choice.findData(1))
        self.window.prepare_progression()
        self.assertEqual(self.window.session.edits.document.values['WorldRunState']['CurrentManualMission'], 1)
        self.window.history_action('undo')
        self.assertEqual(self.window.session.edits.document.values['WorldRunState']['CurrentManualMission'], 0)
        self.assertEqual(self.window.mission_choice.currentData(), 0)
        self.window.history_action('redo')
        self.assertEqual(self.window.session.edits.document.values['WorldRunState']['CurrentManualMission'], 1)
        self.assertEqual(self.window.mission_choice.currentData(), 1)
        self.assertEqual(self.messages, [])

    def test_opening_another_save_resets_mission_choice_and_difficulty_edit_preserves_it(self):
        self.load_scene(feature_sample(mission=True))
        self.assertEqual(self.window.mission_choice.currentData(), 0)
        document = SaveDocument.from_bytes(self.raw)
        other_raw, _ = edit_fields(document, {'/WorldRunState/CurrentManualMission': 1})
        other = self.saves/'Player_Character_1.sav'
        other.write_bytes(other_raw)
        self.window.open_path(other, False)
        self.assertEqual(self.window.mission_choice.currentData(), 1)
        self.window.difficulty.buttons[2].click()
        self.window.prepare_progression()
        state = self.window.session.edits.document.values['WorldRunState']
        self.assertEqual(state['UserChosenDifficulty'], 30)
        self.assertEqual(state['CurrentManualMission'], 1)
        self.assertEqual(self.messages, [])
        self.assertEqual(other.read_bytes(), other_raw)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_secondary_two_handed_weapon_is_displayed_and_edited_independently(self):
        self.load_scene(feature_sample())
        secondary = next(b for b, *_ in self.window.board.slots
                         if b.title == self.window.t('two_handed') and b.isEnabled())
        self.assertIn(self.window.name(catalogue().by_asset['IIW_Polearm_01']['object_path']), secondary.toolTip())
        secondary.click()
        self.assertEqual(self.window.entry_index, 4)
        self.assertEqual(self.window.inventory.currentData(), 4)
        self.assertTrue(self.window.quality_button.isEnabled())
        self.window.gear_quality.setCurrentIndex(self.window.gear_quality.findData('Legendary'))
        self.window.quality_only()
        entries = self.window.session.edits.document.values['SaveGameInventory']['BackpackContents']
        self.assertEqual(entries[4]['EquipmentSlotIndex'], 1)
        self.assertEqual(entries[4]['ItemQuality'], 'EScalingQuality::Legendary')
        self.assertEqual(entries[3]['ItemQuality'], 'EScalingQuality::Epic')
        self.assertEqual(self.messages, [])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_rename_and_stack_undo_apply_restore_use_temporary_files_only(self):
        self.load_scene(feature_sample())
        self.window.character_name.setText('Cavaleiro São')
        self.window.prepare_name()
        self.assertEqual(self.window.session.edits.document.values['CharacterName'], 'Cavaleiro São')
        self.window.history_action('undo')
        self.assertEqual(self.window.session.edits.document.values['CharacterName'], 'Teste')
        self.window.history_action('redo')
        self.window.select_equipment(5)
        self.assertTrue(self.window.stack_editor.isVisible())
        self.assertTrue(self.window.stack_button.isEnabled())
        self.assertEqual(self.window.stack_count.value(), 3)
        self.window.stack_count.setValue(12)
        self.window.prepare_stack()
        self.assertEqual(self.window.session.edits.document.values['SaveGameInventory']['BackpackContents'][5]['Count'], 12)
        self.window.history_action('undo')
        self.assertEqual(self.window.session.edits.document.values['SaveGameInventory']['BackpackContents'][5]['Count'], 3)
        self.window.history_action('redo')
        self.assertEqual(self.source.read_bytes(), self.raw)
        with patch('crimson_editor.QDialog.exec', return_value=QDialog.Accepted):
            self.window.apply()
        parsed = SaveDocument.load(self.source)
        self.assertEqual(parsed.values['CharacterName'], 'Cavaleiro São')
        self.assertEqual(parsed.values['SaveGameInventory']['BackpackContents'][5]['Count'], 12)
        self.assertEqual(self.game_backup.read_bytes(), self.raw)
        self.window.restore()
        self.assertEqual(self.messages, [])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_flask_charge_quantity_is_visible_but_editing_is_disabled(self):
        self.load_scene(feature_sample())
        self.window.select_equipment(6)
        self.assertTrue(self.window.stack_editor.isVisible())
        self.assertEqual(self.window.stack_count.value(), 4)
        self.assertFalse(self.window.stack_button.isEnabled())
        self.assertFalse(self.window.quality_button.isVisible())
        self.assertFalse(self.window.replace_button.isVisible())
        self.window.stack_button.click()
        self.assertFalse(self.window.session.edits.dirty)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_existing_long_name_and_large_stack_are_not_truncated_by_new_controls(self):
        self.load_scene(feature_sample(name='A'*40, stack_count=500))
        self.assertEqual(self.window.character_name.text(), 'A'*40)
        self.window.prepare_name()
        self.window.select_equipment(5)
        self.assertEqual(self.window.stack_count.value(), 500)
        self.window.prepare_stack()
        self.assertEqual(self.messages, [])
        self.assertEqual(self.window.session.edits.document.raw, self.raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
