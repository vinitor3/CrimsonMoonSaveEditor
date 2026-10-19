"""Small, evidence-scoped edits to existing version-8 character fields.

Every operation is in memory and delegates to the reversible typed writer.
This module never creates inventory records, edits player/account metadata, or
writes a file. Limits below are editor guardrails, not claimed game maxima.
"""
from __future__ import annotations

import unicodedata

from .editing import backpack, require_profile
from .gvas import SaveDocument, SaveError
from .writer import edit_fields

NAME_PATH = '/CharacterName'
MAX_NAME_UNITS = 32
MIN_STACK_COUNT = 1
MAX_STACK_COUNT = 15
INVENTORY = '/SaveGameInventory/BackpackContents'

# Only exact references already observed as consumable/throwable stacks in a
# version-8 character are accepted. Their definitions/capacity were absent from
# the export, so no broader filename-based inference or insertion is allowed.
STACK_ITEMS = {
    '/Game/Data/Inventory/Consumables/IICo_OathboundOil.IICo_OathboundOil':
        {'asset_name': 'IICo_OathboundOil', 'kind': 'consumable', 'slot': 'Consumable'},
    '/Game/Data/Inventory/Throwables/ThrowingKnife/IICo_BloodseekerKnife.IICo_BloodseekerKnife':
        {'asset_name': 'IICo_BloodseekerKnife', 'kind': 'throwable', 'slot': 'Throwable'},
    '/Game/Data/Inventory/Throwables/ThrowingKnife/IICo_ThrowingKnife.IICo_ThrowingKnife':
        {'asset_name': 'IICo_ThrowingKnife', 'kind': 'throwable', 'slot': 'Throwable'},
}


def character_name_status(doc: SaveDocument) -> dict:
    require_profile(doc)
    prop = doc.properties.get(NAME_PATH)
    value = doc.values.get('CharacterName')
    if (prop is None or prop.type.name != 'StrProperty' or prop.type.inner
            or prop.flags != 0 or prop.array_index != 0 or type(value) is not str
            or prop.value != value):
        raise SaveError('Nome do personagem não está no formato de texto reconhecido.')
    return {'value': value, 'path': NAME_PATH, 'max_units': MAX_NAME_UNITS,
            'length_unit': 'utf16_code_units', 'editable': True,
            'game_load_tested': False}


def write_character_name(doc: SaveDocument, name: str) -> tuple[bytes, dict]:
    """Rename this character only; UTF-16 length is limited to 1..32 units."""
    before = character_name_status(doc)['value']
    if type(name) is not str or not name or name != name.strip():
        raise SaveError('Use um nome não vazio, sem espaços no início ou no fim.')
    if any(unicodedata.category(char).startswith('C') for char in name):
        raise SaveError('O nome não pode conter controles ou caracteres invisíveis.')
    try:
        units = len(name.encode('utf-16-le')) // 2
    except UnicodeError as exc:
        raise SaveError('O nome contém Unicode inválido.') from exc
    if not 1 <= units <= MAX_NAME_UNITS:
        raise SaveError('Limite preventivo do editor: 1 a 32 unidades UTF-16 no nome.')
    raw, report = edit_fields(doc, {NAME_PATH: name})
    report.update({'kind': 'character_name', 'before': before, 'after': name,
                   'path': NAME_PATH, 'game_load_tested': False,
                   'note': 'Somente CharacterName; o arquivo Player.sav não é alterado.'})
    return raw, report


def _stack_entry(doc: SaveDocument, index: int) -> tuple[dict, dict]:
    entries = backpack(doc)
    if type(index) is not int or not 0 <= index < len(entries):
        raise SaveError('Selecione uma instância válida da mochila.')
    entry = entries[index]
    path = entry.get('Item')
    definition = STACK_ITEMS.get(path) if type(path) is str else None
    if definition is None:
        raise SaveError('Quantidade disponível apenas para os três consumíveis/arremessáveis reconhecidos.')
    package, asset = path.rsplit('.', 1)
    asset_path = entry.get('AssetPath')
    if not isinstance(asset_path, dict) or (asset_path.get('PackageName'), asset_path.get('AssetName')) != (package, asset):
        raise SaveError('AssetPath e Item divergentes. Quantidade preservada.')
    required = {'AssetPath/PackageName': 'NameProperty', 'AssetPath/AssetName': 'NameProperty',
                'Item': 'ObjectProperty', 'Count': 'IntProperty',
                'EquipmentSlot': 'EnumProperty', 'EquipmentSlotIndex': 'IntProperty'}
    for field, kind in required.items():
        prop = doc.properties.get(f'{INVENTORY}/{index}/{field}')
        if prop is None or prop.type.name != kind or prop.flags != 0 or prop.array_index != 0:
            raise SaveError('Estrutura de quantidade não reconhecida: ' + field)
    slot_prop = doc.properties[f'{INVENTORY}/{index}/EquipmentSlot']
    if not slot_prop.type.inner or slot_prop.type.inner[0].name != 'EEquipmentSlot':
        raise SaveError('Enumeração de slot não reconhecida.')
    slot = entry.get('EquipmentSlot')
    if slot not in ('EEquipmentSlot::'+definition['slot'], 'EEquipmentSlot::All'):
        raise SaveError('O slot não corresponde ao tipo do consumível/arremessável.')
    slot_index = entry.get('EquipmentSlotIndex')
    if type(slot_index) is not int or (slot == 'EEquipmentSlot::All' and slot_index != -1) or (
            slot != 'EEquipmentSlot::All' and slot_index < 0):
        raise SaveError('Índice do slot de quantidade não reconhecido.')
    count = entry.get('Count')
    count_prop = doc.properties[f'{INVENTORY}/{index}/Count']
    if (type(count) is not int or not 0 <= count <= 2_147_483_647
            or count_prop.size != 4 or count_prop.value != count):
        raise SaveError('Quantidade atual não está em um IntProperty válido.')
    return entry, definition


def stack_items(doc: SaveDocument) -> list[dict]:
    """List recognized existing stacks, including disabled malformed candidates."""
    result = []
    assets = {definition['asset_name'] for definition in STACK_ITEMS.values()}
    for index, entry in enumerate(backpack(doc)):
        asset_path = entry.get('AssetPath')
        candidate = (entry.get('Item') in STACK_ITEMS if type(entry.get('Item')) is str else False)
        candidate = candidate or (isinstance(asset_path, dict) and type(asset_path.get('AssetName')) is str
                                  and asset_path['AssetName'] in assets)
        if not candidate:
            continue
        row = {'index': index, 'item_path': entry.get('Item'), 'count': entry.get('Count'),
               'min_count': MIN_STACK_COUNT, 'max_count': MAX_STACK_COUNT,
               'game_capacity_known': False, 'experimental': True}
        try:
            _, definition = _stack_entry(doc, index)
            row.update(definition, editable=True, reason=None)
        except SaveError as exc:
            row.update(editable=False, reason=str(exc))
        result.append(row)
    return result


def write_stack_count(doc: SaveDocument, index: int, count: int) -> tuple[bytes, dict]:
    """Change Count on one existing whitelisted stack; never inserts/removes it."""
    entry, definition = _stack_entry(doc, index)
    if type(count) is not int or not MIN_STACK_COUNT <= count <= MAX_STACK_COUNT:
        raise SaveError('Limite preventivo de quantidade: 1 a 15; capacidade real não confirmada pelo jogo.')
    path = f'{INVENTORY}/{index}/Count'
    raw, report = edit_fields(doc, {path: count})
    report.update({'kind': 'stack_count', 'index': index, 'item_path': entry['Item'],
                   'asset_name': definition['asset_name'], 'path': path,
                   'before': entry['Count'], 'after': count,
                   'game_capacity_known': False, 'game_load_tested': False,
                   'note': 'Somente Count da instância existente. O jogo pode limitar/recalcular a quantidade.'})
    return raw, report
