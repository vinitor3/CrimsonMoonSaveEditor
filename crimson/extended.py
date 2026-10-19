"""Evidence-scoped run and persistent-boon editing, entirely in memory.

Run indices come from the exported production manual run. Persistent boons use
the observed SaveGameGameplayEffectData schema (ObjectProperty, FloatProperty,
IntProperty), NOT an ability-class reference. Existing array entries are copied
byte-for-byte. This module never opens a save for writing.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path
import struct
from typing import Any

from .editing import require_profile
from .gvas import Reader, SaveDocument, SaveError
from .service import semantic_diff
from .writer import at_path, edit_fields, pack_string, splice_payloads

from .resource_paths import resource_root
DATA = resource_root() / 'data'
QUALITY_LEVELS = {'Common': 1.0, 'Uncommon': 2.0, 'Rare': 3.0,
                  'Epic': 4.0, 'Legendary': 5.0}
MAX_BLESSINGS = 128  # Editor resource limit, not a claimed in-game maximum.
RUN = '/WorldRunState/'
EFFECTS = '/PlayerGameplayEffects'
RUN_FIELDS = {'difficulty': 'UserChosenDifficulty', 'stage': 'CurrentManualStage',
              'section': 'CurrentManualSection',
              'first_mission_complete': 'bIsFirstMissionComplete'}
OPTIONAL_RUN_FIELDS = {'mission_index': 'CurrentManualMission'}


@lru_cache(maxsize=1)
def progression_catalog() -> dict:
    data = json.loads((DATA / 'progression.json').read_text(encoding='utf-8'))
    if data.get('schema') != 1 or not isinstance(data.get('stages'), list):
        raise SaveError('Catálogo de campanha inválido.')
    return data


@lru_cache(maxsize=1)
def _boon_paths() -> dict[str, str]:
    """Whitelist ONLY primary boons validated against exported default objects."""
    data = json.loads((DATA / 'game_data.json').read_text(encoding='utf-8'))
    result: dict[str, str] = {}
    for boon in data.get('blessings', []):
        default = boon.get('default_object_path')
        if not isinstance(default, str) or '.Default__GE_Boon_' not in default:
            continue
        result[default] = default
        for key in ('effect_path', 'id'):
            value = boon.get(key)
            if isinstance(value, str) and value:
                result[value] = default
    return result


def _require_run(doc: SaveDocument) -> dict:
    require_profile(doc)
    state = doc.values.get('WorldRunState')
    if not isinstance(state, dict):
        raise SaveError('WorldRunState ausente neste personagem.')
    for name, field in RUN_FIELDS.items():
        p = doc.properties.get(RUN + field)
        kind = 'BoolProperty' if name == 'first_mission_complete' else 'IntProperty'
        if p is None or p.type.name != kind or p.flags not in ((0, 16) if kind == 'BoolProperty' else (0,)):
            raise SaveError('Estrutura de campanha não reconhecida: ' + field)
    config = doc.properties.get(RUN + 'WorldRunConfig')
    if config is None or config.type.name != 'ObjectProperty' or config.flags != 0:
        raise SaveError('Referência de campanha não reconhecida.')
    return state


def progression_status(doc: SaveDocument) -> dict:
    state = _require_run(doc)
    catalog = progression_catalog()
    manual = state['WorldRunConfig'] == catalog['config_path']
    out = {name: state[field] for name, field in RUN_FIELDS.items()}
    out.update({'config_path': state['WorldRunConfig'], 'manual_supported': manual,
                'difficulty_min': catalog['editor_difficulty_min'],
                'difficulty_max': catalog['editor_difficulty_max'],
                'stages': deepcopy(catalog['stages']) if manual else [],
                'section_data': None, 'game_load_tested': False})
    mission = doc.properties.get(RUN + 'CurrentManualMission')
    mission_typed = bool(mission and mission.type.name == 'IntProperty' and mission.flags == 0)
    started = doc.properties.get(RUN + 'bPlayerStartedMission')
    started_typed = bool(started and started.type.name == 'BoolProperty'
                         and started.flags in (0, 16))
    out.update({'mission_index': state.get('CurrentManualMission'),
                'mission_supported': manual and mission_typed,
                'player_started_mission': state.get('bPlayerStartedMission') if started_typed else None,
                'player_started_mission_supported': started_typed})
    if manual and type(out['stage']) is int and type(out['section']) is int:
        stages = catalog['stages']
        if 0 <= out['stage'] < len(stages):
            sections = stages[out['stage']]['sections']
            if 0 <= out['section'] < len(sections):
                out['section_data'] = deepcopy(sections[out['section']])
    return out


def write_progression(doc: SaveDocument, updates: dict[str, Any]) -> tuple[bytes, dict]:
    """Update selected difficulty and the saved manual campaign cursor.

    Keys: difficulty (0..100), stage, section, first_mission_complete and optional
    mission_index. The mission index can only be edited when the game serialized
    its canonical property. Stage+section+mission must match exported options.
    Active-mission state, completion unlocks and scores stay byte-identical.
    """
    before = progression_status(doc)
    fields = {**RUN_FIELDS, **OPTIONAL_RUN_FIELDS}
    if type(updates) is not dict or not set(updates).issubset(fields):
        raise SaveError('Campo de campanha inválido.')
    catalog = progression_catalog()
    target = {name: updates.get(name, before[name]) for name in fields}
    if 'difficulty' in updates and (type(target['difficulty']) is not int or not
            catalog['editor_difficulty_min'] <= target['difficulty'] <= catalog['editor_difficulty_max']):
        raise SaveError('Dificuldade fora do limite preventivo do editor: 0 a 100.')
    if 'first_mission_complete' in updates and type(target['first_mission_complete']) is not bool:
        raise SaveError('A conclusão da primeira missão exige verdadeiro/falso.')
    if set(updates) & {'stage', 'section', 'mission_index'}:
        if not before['manual_supported']:
            raise SaveError('Índices de campanha disponíveis apenas na configuração manual documentada.')
        stage, section = target['stage'], target['section']
        stages = catalog['stages']
        if type(stage) is not int or not 0 <= stage < len(stages):
            raise SaveError('Etapa não consta da campanha exportada.')
        if type(section) is not int or not 0 <= section < len(stages[stage]['sections']):
            raise SaveError('Seção não pertence à etapa selecionada.')
        if 'mission_index' in updates and not before['mission_supported']:
            raise SaveError('O save não possui um índice de missão editável; o campo não será criado.')
        if before['mission_supported']:
            mission_index = target['mission_index']
            choices = stages[stage]['sections'][section]['missions']
            if type(mission_index) is not int or not 0 <= mission_index < len(choices):
                raise SaveError('Selecione uma missão oferecida na etapa e fase de destino.')
    result, report = edit_fields(doc, {RUN + fields[k]: v for k, v in updates.items()})
    report.update({'kind': 'progression', 'before': {k: before[k] for k in updates},
                   'after': deepcopy(updates), 'game_load_tested': False,
                   'notes': [catalog['capability_note'], catalog['difficulty_limit_note']]})
    return result, report


def _effect_records(doc: SaveDocument) -> tuple[list[dict], list[bytes]]:
    require_profile(doc)
    p = doc.properties.get(EFFECTS)
    if (p is None or p.type.name != 'ArrayProperty' or p.flags != 0 or len(p.type.inner) != 1
            or p.type.inner[0].name != 'StructProperty' or not p.type.inner[0].inner
            or p.type.inner[0].inner[0].name != 'SaveGameGameplayEffectData'
            or tuple(n.name for n in p.type.inner[0].inner[0].inner) != ('/Script/CrimsonMoonNG',)):
        raise SaveError('Lista de efeitos não corresponde ao formato documentado.')
    r = Reader(doc.raw, p.payload_start, p.end)
    count = r.count()
    records, blocks = [], []
    for i in range(count):
        start = r.pos
        value = r.value(p.type.inner[0], f'{EFFECTS}/{i}', 0, 1)
        if (not isinstance(value, dict) or not isinstance(value.get('GameplayEffect'), str)
                or type(value.get('Level')) not in (float, int)
                or not math.isfinite(value['Level']) or type(value.get('Stacks')) is not int):
            raise SaveError('Registro de efeito incompleto ou inválido.')
        for field, kind in [('GameplayEffect', 'ObjectProperty'), ('Level', 'FloatProperty'), ('Stacks', 'IntProperty')]:
            q = doc.properties.get(f'{EFFECTS}/{i}/{field}')
            if q is None or q.type.name != kind or q.flags != 0:
                raise SaveError('Tag de efeito incompatível: ' + field)
        records.append(value)
        blocks.append(doc.raw[start:r.pos])
    if r.pos != p.end or records != p.value:
        raise SaveError('A lista de efeitos não foi consumida exatamente.')
    return records, blocks


def blessing_status(doc: SaveDocument) -> list[dict]:
    records, _ = _effect_records(doc)
    paths = _boon_paths()
    result = []
    for i, record in enumerate(records):
        level = record['Level']
        result.append({'index': i, 'effect_path': record['GameplayEffect'],
                       'level': level, 'stacks': record['Stacks'],
                       'quality': next((k for k, v in QUALITY_LEVELS.items() if v == level), None),
                       'known': record['GameplayEffect'] in paths})
    return result


def _tag(name: str, kind: str, payload: bytes) -> bytes:
    return (pack_string(name) + pack_string(kind) + struct.pack('<I', 0)
            + struct.pack('<I', len(payload)) + b'\0' + payload)


def _new_effect(effect: str, level: float) -> bytes:
    # Exact field order/types/terminator from the observed version-8 character.
    return (_tag('GameplayEffect', 'ObjectProperty', pack_string(effect))
            + _tag('Level', 'FloatProperty', struct.pack('<f', level))
            + _tag('Stacks', 'IntProperty', struct.pack('<i', 1)) + pack_string('None'))


def _replace_array(doc: SaveDocument, blocks: list[bytes], expected: list[dict]) -> tuple[bytes, dict]:
    payload = struct.pack('<i', len(blocks)) + b''.join(blocks)
    result = splice_payloads(doc, {EFFECTS: payload})
    new = SaveDocument.from_bytes(result)
    tree = deepcopy(doc.values)
    tree['PlayerGameplayEffects'] = deepcopy(expected)
    if new.values != tree:
        raise SaveError('A releitura da lista de bênçãos divergiu da edição.')
    old_opaque = {p['path']: at_path(doc.values, p['path']) for p in doc.opaque}
    new_opaque = {p['path']: at_path(new.values, p['path']) for p in new.opaque}
    if old_opaque != new_opaque:
        raise SaveError('Conteúdo opaco foi alterado inesperadamente.')
    p = doc.properties[EFFECTS]
    restored = splice_payloads(new, {EFFECTS: doc.raw[p.payload_start:p.end]})
    if restored != doc.raw:
        raise SaveError('A reversão não recuperou o save original.')
    return result, {'semantic_changes': semantic_diff(doc.values, new.values),
                    'reverse_matches_input': True, 'source_bytes': len(doc.raw),
                    'output_bytes': len(result), 'opaque_fields_preserved': list(old_opaque)}


def write_blessing(doc: SaveDocument, effect_path: str, remove: bool = False,
                   quality: str = 'Legendary') -> tuple[bytes, dict]:
    """Add/update one primary persistent boon, or remove its saved entries.

    Adds are catalog-whitelisted. A duplicate is updated rather than appended;
    duplicate ambiguous existing instances reject updates. Removal can also
    target an existing unknown effect without inventing a new reference.
    """
    records, blocks = _effect_records(doc)
    if type(effect_path) is not str or not effect_path or type(remove) is not bool:
        raise SaveError('Selecione uma bênção válida.')
    paths = _boon_paths()
    canonical = paths.get(effect_path, effect_path)
    matching = [i for i, r in enumerate(records)
                if paths.get(r['GameplayEffect'], r['GameplayEffect']) == canonical]
    if remove:
        wanted = [i for i in range(len(records)) if i not in matching]
        result, report = _replace_array(doc, [blocks[i] for i in wanted], [records[i] for i in wanted])
        action = 'remove'
    else:
        if effect_path not in paths:
            raise SaveError('A bênção não está entre os efeitos primários exportados e verificados.')
        if type(quality) is not str or quality not in QUALITY_LEVELS:
            raise SaveError('Qualidade de bênção inválida.')
        if len(matching) > 1:
            raise SaveError('Há múltiplos registros desta bênção; remova-os antes de adicionar novamente.')
        level = QUALITY_LEVELS[quality]
        if matching:
            index = matching[0]
            # Preserve nonstandard per-instance state. Normal boons have one
            # stack, but quality editing must not silently rewrite stacks.
            result, report = edit_fields(doc, {f'{EFFECTS}/{index}/Level': level})
            action = 'quality'
        else:
            if len(records) >= MAX_BLESSINGS:
                raise SaveError('Limite preventivo do editor: 128 efeitos persistentes.')
            record = {'GameplayEffect': canonical, 'Level': level, 'Stacks': 1}
            result, report = _replace_array(doc, blocks + [_new_effect(canonical, level)], records + [record])
            action = 'add'
    report.update({'kind': 'blessing', 'action': action, 'effect_path': canonical,
                   'removed_count': len(matching) if remove else 0,
                   'quality': None if remove else quality, 'game_load_tested': False})
    return result, report
