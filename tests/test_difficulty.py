"""Verified menu mapping and optional saved mission cursor regressions."""
from copy import deepcopy
import struct
import unittest

from crimson.difficulty import (difficulty_catalog, difficulty_status,
                                difficulty_updates, raw_for_skulls,
                                skulls_for_raw, write_difficulty)
from crimson.extended import progression_catalog, progression_status, write_progression
from crimson.gvas import SaveDocument, SaveError
from test_core import fixture, integer, prop, text, tn


def script_struct(name):
    return tn('StructProperty', tn(name, tn('/Script/CrimsonMoonNG')))


def sample(difficulty=25, *, mission=0, with_mission=True, mission_type='IntProperty',
           stage=0, section=3, started=True):
    raw_mission = (integer('CurrentManualMission', mission) if mission_type == 'IntProperty'
                   else prop('CurrentManualMission', tn('FloatProperty'), struct.pack('<f', float(mission))))
    run = (prop('WorldRunConfig', tn('ObjectProperty'), text(progression_catalog()['config_path']))
           + integer('UserChosenDifficulty', difficulty)
           + integer('CurrentManualStage', stage) + integer('CurrentManualSection', section)
           + (raw_mission if with_mission else b'')
           + prop('bIsFirstMissionComplete', tn('BoolProperty'), b'', 16)
           + prop('bPlayerStartedMission', tn('BoolProperty'), b'', 16 if started else 0)
           + text('None'))
    extra = (prop('WorldRunState', script_struct('SaveGameWorldRunData'), run)
             + integer('BestRunOverallDifficulty', 85)
             + prop('UnlockData', tn('TextProperty'), b'\xffKEEP_UNLOCKS_EXACT')
             + prop('ActiveRunScores', tn('TextProperty'), b'\xffKEEP_SCORES_EXACT'))
    return SaveDocument.from_bytes(fixture(extra=extra))


class DifficultyMappingTests(unittest.TestCase):
    def test_source_five_segments_and_zero_based_inclusive_mapping(self):
        catalog = difficulty_catalog()
        self.assertEqual(catalog['skull_slots'], 5)
        self.assertEqual([(m['skulls'], m['menu_index'], m['raw_value']) for m in catalog['modes']],
                         [(1, 0, 0), (2, 1, 15), (3, 2, 30), (4, 3, 45), (5, 4, 60)])
        self.assertIn('iconIndex <= InIndex', catalog['source']['visualizer_evidence'])
        self.assertEqual(catalog['max_world_difficulty'], 100)

    def test_complete_authored_titles_and_descriptions(self):
        for mode in difficulty_catalog()['modes']:
            self.assertEqual(set(mode['names']), {'pt', 'en', 'de', 'es', 'fr', 'it', 'ja', 'zh'})
            self.assertTrue(all(mode['names'].values()))
            self.assertTrue(all(mode['descriptions'].values()))
        self.assertEqual(difficulty_catalog()['modes'][1]['names']['pt'], 'Padrão')
        self.assertEqual(difficulty_catalog()['modes'][1]['names']['en'], 'Standard')

    def test_all_five_exact_roundtrips(self):
        for skulls, raw in [(1, 0), (2, 15), (3, 30), (4, 45), (5, 60)]:
            self.assertEqual(raw_for_skulls(skulls), raw)
            self.assertEqual(skulls_for_raw(raw), skulls)
            self.assertEqual(difficulty_updates(skulls), {'difficulty': raw})

    def test_sixth_parameter_is_preserved_without_a_fifth_skull_alias(self):
        extra = difficulty_catalog()['additional_defined_modes']
        self.assertEqual([(m['menu_index'], m['raw_value'], m['skulls']) for m in extra], [(5, 75, None)])
        status = difficulty_status(sample(75))
        self.assertTrue(status['canonical'])
        self.assertFalse(status['visualizer_supported'])
        self.assertIsNone(status['skulls'])

    def test_noncanonical_values_are_not_rounded_or_clamped_on_read(self):
        for raw in [-1, 1, 25, 50, 61, 100, 150]:
            d = sample(raw)
            status = difficulty_status(d)
            self.assertEqual(status['raw_value'], raw)
            self.assertIsNone(status['skulls'])
            self.assertFalse(status['canonical'])
            self.assertEqual(d.rebuild(), d.raw)

    def test_each_selection_changes_only_user_modifier(self):
        d = sample()
        for skulls in range(1, 6):
            raw, report = write_difficulty(d, skulls)
            new = SaveDocument.from_bytes(raw)
            expected = deepcopy(d.values)
            expected['WorldRunState']['UserChosenDifficulty'] = raw_for_skulls(skulls)
            self.assertEqual(new.values, expected)
            self.assertTrue(report['reverse_matches_input'])
            self.assertFalse(report['unlocks_modified'])
            self.assertEqual(difficulty_status(new)['skulls'], skulls)

    def test_same_mode_is_byte_identical(self):
        d = sample(15)
        self.assertEqual(write_difficulty(d, 2)[0], d.raw)

    def test_invalid_selection_rejected(self):
        for value in [0, 6, True, None, 1.0, '2']:
            with self.subTest(value=value), self.assertRaises(SaveError):
                write_difficulty(sample(), value)
        for value in [True, 15.0, '15', None]:
            with self.subTest(raw=value), self.assertRaises(SaveError):
                skulls_for_raw(value)

    def test_missing_saved_field_is_not_created(self):
        with self.assertRaises(SaveError):
            write_difficulty(SaveDocument.from_bytes(fixture()), 1)


class OptionalMissionTests(unittest.TestCase):
    def test_status_reads_typed_mission_and_active_state(self):
        status = progression_status(sample(mission=1))
        self.assertTrue(status['mission_supported'])
        self.assertEqual(status['mission_index'], 1)
        self.assertTrue(status['player_started_mission'])
        self.assertTrue(status['player_started_mission_supported'])

    def test_optional_absent_mission_stays_absent(self):
        d = sample(with_mission=False)
        status = progression_status(d)
        self.assertFalse(status['mission_supported'])
        self.assertIsNone(status['mission_index'])
        with self.assertRaises(SaveError):
            write_progression(d, {'mission_index': 0})
        raw, _ = write_progression(d, {'stage': 1, 'section': 0})
        self.assertNotIn('CurrentManualMission', SaveDocument.from_bytes(raw).values['WorldRunState'])

    def test_wrong_typed_optional_mission_is_never_overwritten(self):
        d = sample(mission_type='FloatProperty')
        self.assertFalse(progression_status(d)['mission_supported'])
        with self.assertRaises(SaveError):
            write_progression(d, {'mission_index': 1})
        raw, _ = write_progression(d, {'difficulty': 30})
        self.assertEqual(SaveDocument.from_bytes(raw).properties['/WorldRunState/CurrentManualMission'].type.name,
                         'FloatProperty')

    def test_existing_mission_changes_only_requested_index(self):
        d = sample()
        raw, report = write_progression(d, {'mission_index': 1})
        new = SaveDocument.from_bytes(raw)
        expected = deepcopy(d.values)
        expected['WorldRunState']['CurrentManualMission'] = 1
        self.assertEqual(new.values, expected)
        self.assertTrue(report['reverse_matches_input'])

    def test_index_must_belong_to_target_section(self):
        for updates in [{'mission_index': -1}, {'mission_index': 2}, {'mission_index': True},
                        {'mission_index': 1.0}, {'stage': 1, 'section': 0, 'mission_index': 1}]:
            with self.subTest(updates=updates), self.assertRaises(SaveError):
                write_progression(sample(), updates)

    def test_stage_change_requires_explicit_valid_choice_if_existing_no_longer_fits(self):
        d = sample(mission=1)
        with self.assertRaises(SaveError):
            write_progression(d, {'stage': 1, 'section': 0})
        raw, _ = write_progression(d, {'stage': 1, 'section': 0, 'mission_index': 0, **difficulty_updates(1)})
        status = progression_status(SaveDocument.from_bytes(raw))
        self.assertEqual((status['stage'], status['section'], status['mission_index'], status['difficulty']),
                         (1, 0, 0, 0))
        self.assertTrue(status['player_started_mission'])

    def test_started_flag_is_read_only(self):
        for started in [True, False]:
            d = sample(started=started)
            raw, _ = write_progression(d, {'mission_index': 1, 'difficulty': 60})
            self.assertEqual(SaveDocument.from_bytes(raw).values['WorldRunState']['bPlayerStartedMission'], started)
            with self.assertRaises(SaveError):
                write_progression(d, {'player_started_mission': not started})


if __name__ == '__main__':
    unittest.main()
