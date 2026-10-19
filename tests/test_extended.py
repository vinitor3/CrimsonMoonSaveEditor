"""Structural regressions for campaign and persistent effects; synthetic saves."""
from copy import deepcopy
import struct
import unittest
from unittest.mock import patch

from crimson.gvas import SaveDocument, SaveError
from crimson.extended import (QUALITY_LEVELS, blessing_status, progression_catalog,
                              progression_status, write_blessing, write_progression)
from test_core import fixture, integer, prop, text, tn


PACKAGE = '/Game/GameSystems/GAS/Effects/Boons/LastLight/GE_Boon_LastLight'
DEFAULT = PACKAGE + '.Default__GE_Boon_LastLight_C'
CLASS = PACKAGE + '.GE_Boon_LastLight_C'
OTHER = '/Game/GameSystems/GAS/Effects/Boons/CrimsonSmite/GE_Boon_CrimsonSmite.Default__GE_Boon_CrimsonSmite_C'
PATHS = {DEFAULT: DEFAULT, CLASS: DEFAULT, 'LastLight': DEFAULT, OTHER: OTHER}


def script_struct(name):
    return tn('StructProperty', tn(name, tn('/Script/CrimsonMoonNG')))


def effect_record(path=DEFAULT, level=4.0, stacks=1, extra=b''):
    return (prop('GameplayEffect', tn('ObjectProperty'), text(path))
            + prop('Level', tn('FloatProperty'), struct.pack('<f', level))
            + integer('Stacks', stacks) + extra + text('None'))


def sample(*, effects=None, stage=0, section=3, config=None, extra=b''):
    effects = [effect_record()] if effects is None else effects
    config = config or progression_catalog()['config_path']
    run = (prop('WorldRunConfig', tn('ObjectProperty'), text(config))
           + integer('UserChosenDifficulty', 60) + integer('CurrentManualStage', stage)
           + integer('CurrentManualSection', section)
           + prop('bIsFirstMissionComplete', tn('BoolProperty'), b'', 16) + text('None'))
    array = prop('PlayerGameplayEffects', tn('ArrayProperty', script_struct('SaveGameGameplayEffectData')),
                 struct.pack('<i', len(effects)) + b''.join(effects))
    return fixture(extra=prop('WorldRunState', script_struct('SaveGameWorldRunData'), run)
                   + array + prop('Opaque', tn('TextProperty'), b'\xff\0ORIGINAL') + extra)


class ProgressionTests(unittest.TestCase):
    def doc(self, **kwargs):
        return SaveDocument.from_bytes(sample(**kwargs))

    def test_source_maps_only_real_indices_and_options(self):
        catalog = progression_catalog()
        self.assertEqual([len(s['sections']) for s in catalog['stages']], [4, 1])
        self.assertEqual(catalog['stages'][0]['sections'][0]['missions'][0]['id'], 'W1_D1')
        self.assertEqual(catalog['stages'][1]['sections'][0]['missions'][0]['id'], 'W4_FB1')

    def test_status_identifies_current_section(self):
        s = progression_status(self.doc())
        self.assertEqual((s['stage'], s['section'], s['difficulty']), (0, 3, 60))
        self.assertTrue(s['manual_supported'])
        self.assertEqual(s['section_data']['missions'][0]['id'], 'W1_WB1')

    def test_set_difficulty_does_not_change_history_or_effects(self):
        d = self.doc(extra=integer('BestRunOverallDifficulty', 85))
        raw, report = write_progression(d, {'difficulty': 15})
        new = SaveDocument.from_bytes(raw)
        expected = deepcopy(d.values)
        expected['WorldRunState']['UserChosenDifficulty'] = 15
        self.assertEqual(new.values, expected)
        self.assertEqual(new.values['BestRunOverallDifficulty'], 85)
        self.assertTrue(report['reverse_matches_input'])

    def test_valid_stage_section_pairs(self):
        d = self.doc()
        for stage, section in [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0)]:
            with self.subTest(stage=stage, section=section):
                raw, report = write_progression(d, {'stage': stage, 'section': section})
                new = progression_status(SaveDocument.from_bytes(raw))
                self.assertEqual((new['stage'], new['section']), (stage, section))
                self.assertTrue(report['reverse_matches_input'])

    def test_invalid_pairs_refused_without_clamping(self):
        for update in [{'stage': 1}, {'stage': 2, 'section': 0}, {'section': 4},
                       {'stage': -1}, {'stage': True}, {'section': 1.0}]:
            with self.subTest(update=update), self.assertRaises(SaveError):
                write_progression(self.doc(), update)

    def test_difficulty_guardrail_and_types(self):
        d = self.doc()
        for value in [0, 100]:
            raw, _ = write_progression(d, {'difficulty': value})
            self.assertEqual(progression_status(SaveDocument.from_bytes(raw))['difficulty'], value)
        for value in [-1, 101, 1.0, True, '60', None]:
            with self.subTest(value=value), self.assertRaises(SaveError):
                write_progression(d, {'difficulty': value})

    def test_completion_bool_and_unknown_keys(self):
        d = self.doc()
        raw, _ = write_progression(d, {'first_mission_complete': False})
        self.assertFalse(progression_status(SaveDocument.from_bytes(raw))['first_mission_complete'])
        for update in [{'mission': 'W1_D1'}, {'first_mission_complete': 1}, []]:
            with self.subTest(update=update), self.assertRaises(SaveError):
                write_progression(d, update)

    def test_unsupported_config_has_no_guessed_stages(self):
        d = self.doc(config='/Game/Other.Other')
        self.assertFalse(progression_status(d)['manual_supported'])
        self.assertEqual(progression_status(d)['stages'], [])
        with self.assertRaises(SaveError):
            write_progression(d, {'stage': 0, 'section': 0})
        raw, _ = write_progression(d, {'difficulty': 50})
        self.assertEqual(progression_status(SaveDocument.from_bytes(raw))['difficulty'], 50)

    def test_noop_is_byte_identical(self):
        d = self.doc()
        self.assertEqual(write_progression(d, {})[0], d.raw)
        self.assertEqual(write_progression(d, {'difficulty': 60})[0], d.raw)


class BlessingTests(unittest.TestCase):
    def setUp(self):
        self.paths = patch('crimson.extended._boon_paths', return_value=PATHS)
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def doc(self, **kwargs):
        return SaveDocument.from_bytes(sample(**kwargs))

    def test_status_knows_quality_and_object_path(self):
        status = blessing_status(self.doc())
        self.assertEqual(status, [{'index': 0, 'effect_path': DEFAULT, 'level': 4.0,
                                   'stacks': 1, 'quality': 'Epic', 'known': True}])

    def test_add_empty_array_uses_observed_schema(self):
        d = self.doc(effects=[])
        raw, report = write_blessing(d, CLASS, quality='Legendary')
        n = SaveDocument.from_bytes(raw)
        self.assertEqual(n.values['PlayerGameplayEffects'],
                         [{'GameplayEffect': DEFAULT, 'Level': 5.0, 'Stacks': 1}])
        self.assertTrue(report['reverse_matches_input'])
        for field in ('GameplayEffect', 'Level', 'Stacks'):
            self.assertEqual(n.properties['/PlayerGameplayEffects/0/' + field].flags, 0)

    def test_add_remove_recovers_original_bytes(self):
        for effects in [[], [effect_record()], [effect_record(OTHER), effect_record()]]:
            d = self.doc(effects=effects)
            target = OTHER if all(OTHER.encode() not in e for e in effects) else '/Game/Extra.Default__GE_Boon_Extra_C'
            with patch('crimson.extended._boon_paths', return_value={**PATHS, target: target}):
                raw, _ = write_blessing(d, target)
                removed, report = write_blessing(SaveDocument.from_bytes(raw), target, remove=True)
                self.assertEqual(removed, d.raw)
                self.assertTrue(report['reverse_matches_input'])

    def test_quality_updates_existing_without_duplicating(self):
        d = self.doc(effects=[effect_record(extra=integer('FutureField', 77))])
        for quality, level in QUALITY_LEVELS.items():
            raw, report = write_blessing(d, 'LastLight', quality=quality)
            records = SaveDocument.from_bytes(raw).values['PlayerGameplayEffects']
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0], {'GameplayEffect': DEFAULT, 'Level': level,
                                          'Stacks': 1, 'FutureField': 77})
            self.assertEqual(report['action'], 'quality')

    def test_other_entries_preserved_byte_for_byte(self):
        d = self.doc(effects=[effect_record(OTHER, 2.0, extra=integer('FutureField', 22))])
        raw, _ = write_blessing(d, DEFAULT)
        n = SaveDocument.from_bytes(raw)
        old = d.properties['/PlayerGameplayEffects/0/GameplayEffect']
        new = n.properties['/PlayerGameplayEffects/0/GameplayEffect']
        end1 = d.properties['/PlayerGameplayEffects'].end
        end2 = n.properties['/PlayerGameplayEffects/1/GameplayEffect'].start
        self.assertEqual(d.raw[old.start:end1], n.raw[new.start:end2])
        self.assertEqual(n.values['Opaque'], d.values['Opaque'])

    def test_remove_one_preserves_other_entries(self):
        d = self.doc(effects=[effect_record(OTHER), effect_record(), effect_record(OTHER)])
        raw, report = write_blessing(d, DEFAULT, remove=True)
        self.assertEqual([r['GameplayEffect'] for r in SaveDocument.from_bytes(raw).values['PlayerGameplayEffects']], [OTHER, OTHER])
        self.assertEqual(report['removed_count'], 1)

    def test_equivalent_class_reference_does_not_duplicate_saved_effect(self):
        d = self.doc(effects=[effect_record(CLASS)])
        raw, _ = write_blessing(d, DEFAULT)
        records = SaveDocument.from_bytes(raw).values['PlayerGameplayEffects']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['GameplayEffect'], CLASS)
        self.assertEqual(records[0]['Level'], 5.0)
        raw, _ = write_blessing(d, 'LastLight', remove=True)
        self.assertEqual(SaveDocument.from_bytes(raw).values['PlayerGameplayEffects'], [])

    def test_remove_duplicates_but_refuse_ambiguous_quality_update(self):
        d = self.doc(effects=[effect_record(), effect_record()])
        with self.assertRaises(SaveError):
            write_blessing(d, DEFAULT)
        raw, report = write_blessing(d, DEFAULT, remove=True)
        self.assertEqual(SaveDocument.from_bytes(raw).values['PlayerGameplayEffects'], [])
        self.assertEqual(report['removed_count'], 2)

    def test_remove_unknown_existing_is_allowed_add_is_not(self):
        unknown = '/Game/Unknown.Unknown'
        d = self.doc(effects=[effect_record(unknown)])
        self.assertFalse(blessing_status(d)[0]['known'])
        with self.assertRaises(SaveError):
            write_blessing(d, unknown)
        raw, _ = write_blessing(d, unknown, remove=True)
        self.assertEqual(SaveDocument.from_bytes(raw).values['PlayerGameplayEffects'], [])

    def test_noop_is_byte_identical(self):
        d = self.doc()
        self.assertEqual(write_blessing(d, DEFAULT, quality='Epic')[0], d.raw)
        self.assertEqual(write_blessing(d, OTHER, remove=True)[0], d.raw)

    def test_invalid_values(self):
        d = self.doc()
        for quality in [None, True, 4, 'EScalingQuality::Epic', 'Mythic']:
            with self.subTest(quality=quality), self.assertRaises(SaveError):
                write_blessing(d, DEFAULT, quality=quality)
        for path in [None, '', 10, '/Game/Fake.Fake']:
            with self.subTest(path=path), self.assertRaises(SaveError):
                write_blessing(d, path)
        with self.assertRaises(SaveError):
            write_blessing(d, DEFAULT, remove=1)

    def test_missing_or_wrong_array_schema_is_refused(self):
        with self.assertRaises(SaveError):
            blessing_status(SaveDocument.from_bytes(fixture()))
        wrong = prop('PlayerGameplayEffects', tn('ArrayProperty', tn('ObjectProperty')), struct.pack('<i', 0))
        with self.assertRaises(SaveError):
            write_blessing(SaveDocument.from_bytes(fixture(extra=wrong)), DEFAULT)


if __name__ == '__main__':
    unittest.main()
