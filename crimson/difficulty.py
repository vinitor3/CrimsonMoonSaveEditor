"""Five-skull difficulty options read from the game's production menu asset.

The stored value is a modifier, not a skull count or an enemy level. The menu
visualizer uses inclusive zero-based indices: index 0 already lights one skull.
The sixth source parameter has no sixth segment; it is identified and preserved
without inventing a skull representation. All operations here stay in memory.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from .editing import require_profile
from .gvas import SaveDocument, SaveError
from .writer import edit_fields

from .resource_paths import resource_root
DATA = resource_root() / 'data'
DIFFICULTY_FIELD = '/WorldRunState/UserChosenDifficulty'


@lru_cache(maxsize=1)
def difficulty_catalog() -> dict:
    data = json.loads((DATA / 'difficulty.json').read_text(encoding='utf-8'))
    modes = data.get('modes', [])
    if (data.get('schema') != 1 or data.get('skull_slots') != 5
            or [(m.get('skulls'), m.get('menu_index'), m.get('raw_value')) for m in modes]
            != [(1, 0, 0), (2, 1, 15), (3, 2, 30), (4, 3, 45), (5, 4, 60)]):
        raise SaveError('Catálogo de dificuldade não corresponde à definição exportada.')
    return data


def raw_for_skulls(skulls: int) -> int:
    if type(skulls) is not int or not 1 <= skulls <= 5:
        raise SaveError('Selecione de uma a cinco caveiras.')
    return difficulty_catalog()['modes'][skulls - 1]['raw_value']


def skulls_for_raw(raw_value: int) -> int | None:
    """Return an exact supported match. Custom values are never rounded."""
    if type(raw_value) is not int:
        raise SaveError('A dificuldade salva deve ser um inteiro.')
    return next((mode['skulls'] for mode in difficulty_catalog()['modes']
                 if mode['raw_value'] == raw_value), None)


def difficulty_updates(skulls: int) -> dict[str, int]:
    """Merge with other write_progression updates to prepare one atomic step."""
    return {'difficulty': raw_for_skulls(skulls)}


def difficulty_status(doc: SaveDocument) -> dict:
    require_profile(doc)
    field = doc.properties.get(DIFFICULTY_FIELD)
    if field is None or field.type.name != 'IntProperty' or field.flags != 0:
        raise SaveError('A dificuldade não está salva no formato esperado.')
    raw = field.value
    catalog = difficulty_catalog()
    mode = next((m for m in catalog['modes'] + catalog['additional_defined_modes']
                 if m['raw_value'] == raw), None)
    return {'raw_value': raw, 'skulls': skulls_for_raw(raw),
            'canonical': mode is not None,
            'visualizer_supported': bool(mode and mode['visualizer_supported']),
            'mode': deepcopy(mode), 'skull_slots': catalog['skull_slots'],
            'max_world_difficulty': catalog['max_world_difficulty'],
            'options': deepcopy(catalog['modes'])}


def write_difficulty(doc: SaveDocument, skulls: int) -> tuple[bytes, dict]:
    """Write a verified menu option while preserving unlocks, scores and phase."""
    before = difficulty_status(doc)
    raw_value = raw_for_skulls(skulls)
    result, report = edit_fields(doc, {DIFFICULTY_FIELD: raw_value})
    report.update({'kind': 'difficulty', 'before': before['raw_value'],
                   'after': raw_value, 'skulls': skulls,
                   'game_load_tested': False, 'unlocks_modified': False})
    return result, report
