"""In-memory editing. No filesystem side effect; every step is reread and checked.

Equipment edits affect an existing backpack instance, NOT the permanent unlock
map or saved presets. These are intentionally different operations. No item is
inserted or deleted, and no arbitrary gameplay effect is injected.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from .gvas import SaveDocument, SaveError
from .writer import edit_fields
from .service import MAX_AMOUNT, currency_field, write_currency, semantic_diff
from .catalogue import Catalogue, TYPE_SLOTS, QUALITY_LABELS, clean_enum

ATTRIBUTES = {
    'NephilimStrength': 'Força', 'NephilimDexterity': 'Destreza',
    'NephilimIntelligence': 'Inteligência', 'NephilimVitality': 'Vitalidade',
    'NephilimEndurance': 'Resistência', 'NephilimWillpower': 'Força de vontade',
}
MAX_ATTRIBUTE = 999  # UI/editor guardrail, not a claim about the game's maximum.
MAX_HISTORY = 50
MAX_HISTORY_BYTES = 128 * 1024 * 1024
INV = '/SaveGameInventory/BackpackContents'


def require_profile(doc: SaveDocument) -> None:
    if doc.header.get('class') != '/Script/CrimsonMoonNG.SaveGameCharacter':
        raise SaveError('Selecione um save de personagem do Crimson Moon.')
    if type(doc.values.get('SavedDataVersion')) is not int or doc.values['SavedDataVersion'] != 8:
        raise SaveError('SavedDataVersion diferente de 8. Gravação recusada.')
    inv=doc.values.get('SaveGameInventory')
    if not isinstance(inv,dict) or not isinstance(inv.get('BackpackContents'),list) or not all(isinstance(e,dict) for e in inv['BackpackContents']):
        raise SaveError('Mochila não encontrada no perfil esperado.')


def backpack(doc: SaveDocument) -> list[dict]:
    require_profile(doc)
    return doc.values['SaveGameInventory']['BackpackContents']


def equipment_entry(doc: SaveDocument, catalog: Catalogue, index: int) -> tuple[dict, dict]:
    entries = backpack(doc)
    if type(index) is not int or not 0 <= index < len(entries):
        raise SaveError('Selecione um registro válido da mochila.')
    entry = entries[index]
    item = catalog.item(entry.get('Item', ''))
    reason = catalog.block_reason(item)
    if reason:
        raise SaveError(reason)
    ap = entry.get('AssetPath', {})
    if not isinstance(ap,dict):raise SaveError('Referência de equipamento inválida.')
    required={'AssetPath/PackageName':'NameProperty','AssetPath/AssetName':'NameProperty',
              'Item':'ObjectProperty','Count':'IntProperty','EquipmentSlot':'EnumProperty',
              'EquipmentSlotIndex':'IntProperty','ItemQuality':'EnumProperty'}
    for key,kind in required.items():
        p=doc.properties.get(f'{INV}/{index}/{key}')
        if p is None or p.type.name!=kind or p.flags!=0:
            raise SaveError('Estrutura inesperada no campo de equipamento: '+key)
    qp=doc.properties[f'{INV}/{index}/ItemQuality']
    if not qp.type.inner or qp.type.inner[0].name!='EScalingQuality':
        raise SaveError('Enumeração de qualidade diferente da esperada.')
    if (ap.get('PackageName'), ap.get('AssetName'), entry.get('Item')) != (
            item['package_name'], item['asset_name'], item['object_path']):
        raise SaveError('AssetPath e Item divergentes. Troca recusada.')
    if type(entry.get('Count')) is not int or entry.get('Count') != 1:
        raise SaveError('Esta versão exige uma instância de equipamento com quantidade 1.')
    slot = clean_enum(entry.get('EquipmentSlot'))
    # A reservation (All/-1) is valid; an unrelated equipped slot is not.
    if slot not in (TYPE_SLOTS[item['type']], 'All'):
        raise SaveError('O slot registrado não corresponde à categoria do item.')
    if type(entry.get('EquipmentSlotIndex')) is not int:
        raise SaveError('Índice de slot ausente ou inválido.')
    if clean_enum(entry.get('ItemQuality')) not in QUALITY_LABELS:
        raise SaveError('Qualidade atual desconhecida; edição recusada.')
    return entry, item


def quality_value(value: str) -> str:
    if type(value) is not str or value not in QUALITY_LABELS:
        raise SaveError('Escolha uma das cinco qualidades documentadas no catálogo de textos.')
    return 'EScalingQuality::' + value


@dataclass
class Step:
    before: bytes
    after: bytes
    operation: dict
    validation: dict


class EditBuffer:
    def __init__(self, document: SaveDocument, catalog: Catalogue):
        require_profile(document)
        self.original = document
        self.document = document
        self.catalog = catalog
        self._undo: list[Step] = []
        self._redo: list[Step] = []

    @property
    def dirty(self) -> bool:
        return self.original.raw != self.document.raw

    @property
    def operations(self) -> list[dict]:
        return [deepcopy(s.operation) for s in self._undo]

    @property
    def experimental(self) -> bool:
        return any(s.operation['kind'] != 'currency' for s in self._undo) and self.dirty

    def _record(self, data: bytes, operation: dict, validation: dict) -> bool:
        if data == self.document.raw:
            return False
        if len(self._undo) >= MAX_HISTORY or sum(len(s.after) for s in self._undo) + len(data) > MAX_HISTORY_BYTES:
            raise SaveError('Limite de 50 etapas/128 MiB em memória. Aplique ou descarte antes de continuar.')
        new = SaveDocument.from_bytes(data)
        require_profile(new)
        self._undo.append(Step(self.document.raw, data, operation, validation))
        self._redo.clear()
        self.document = new
        return True

    def set_currency(self, kind: str, value: int) -> bool:
        old, path = currency_field(self.document, kind)
        data, check = write_currency(self.document, kind, value)
        return self._record(data, {'kind': 'currency', 'currency': kind,
                                  'label': 'Almas' if kind == 'souls' else 'Dinheiro',
                                  'before': old, 'after': value, 'path': path}, check)

    def set_attribute(self, name: str, value: int) -> bool:
        if name not in ATTRIBUTES or type(value) is not int or not 1 <= value <= MAX_ATTRIBUTE:
            raise SaveError(f'Atributo inválido. Limite preventivo do editor: 1 a {MAX_ATTRIBUTE}.')
        path = '/NephilimAttributes/' + name
        p = self.document.properties.get(path)
        if p is None or p.type.name != 'IntProperty' or p.flags != 0:
            raise SaveError('Atributo não está serializado como inteiro editável.')
        data, check = edit_fields(self.document, {path: value})
        return self._record(data, {'kind': 'attribute', 'label': ATTRIBUTES[name],
                                  'before': p.value, 'after': value, 'path': path}, check)

    def set_quality(self, index: int, quality: str) -> bool:
        entry, item = equipment_entry(self.document, self.catalog, index)
        path = f'{INV}/{index}/ItemQuality'
        data, check = edit_fields(self.document, {path: quality_value(quality)})
        return self._record(data, {'kind': 'quality', 'label': f'Qualidade: {item["name_pt"]}',
                                  'index': index, 'before': entry['ItemQuality'],
                                  'after': quality_value(quality), 'path': path}, check)

    def replace_equipment(self, index: int, selected_path: str, quality: str | None = None) -> bool:
        entry, old = equipment_entry(self.document, self.catalog, index)
        selected = self.catalog.item(selected_path)
        reason = self.catalog.block_reason(selected)
        if reason:
            raise SaveError(reason)
        if selected['type'] != old['type']:
            raise SaveError('Troque apenas por um item da mesma categoria/parte do corpo.')
        # Preserve all per-instance state. Do not carry an unknown custom rune or
        # random boon to a different definition, nor silently delete it.
        if selected_path != old['object_path']:
            effect = entry.get('InstanceEquippedEffect')
            if entry.get('SlottedRunes') != [] or effect != {'PackageName': 'None', 'AssetName': 'None', 'SubPath': ''}:
                raise SaveError('Esta instância possui runas/efeito próprio ou estrutura desconhecida. '
                                'Troca bloqueada para não perder ou transferir esses dados; qualidade pode ser editada.')
            if entry.get('ItemStability') != 'EItemStability::Purifiable':
                raise SaveError('A instância tem estabilidade especial; troca ainda não suportada.')
        path = f'{INV}/{index}'
        changes = {
            path + '/AssetPath/PackageName': selected['package_name'],
            path + '/AssetPath/AssetName': selected['asset_name'],
            path + '/Item': selected['object_path'],
        }
        if quality is not None:
            changes[path + '/ItemQuality'] = quality_value(quality)
        data, check = edit_fields(self.document, changes)
        notes = ['Somente a instância da mochila é alterada; coleção e conjuntos salvos permanecem intactos.',
                 'Edição de equipamento não foi validada em execução do jogo.']
        if old.get('auto_equip_weapon_arts') != selected.get('auto_equip_weapon_arts'):
            notes.append('As definições de artes da arma diferem. O editor não remove nem cria os registros '
                         'de artes da mochila. A atualização pelo jogo precisa de teste.')
        return self._record(data, {'kind': 'equipment', 'label': 'Troca de equipamento', 'index': index,
                                  'before': old['name_pt'], 'after': selected['name_pt'],
                                  'before_path': old['object_path'], 'after_path': selected_path,
                                  'quality': quality, 'scope': 'backpack_instance_only', 'notes': notes}, check)

    def undo(self) -> bool:
        if not self._undo:
            return False
        step = self._undo.pop()
        self._redo.append(step)
        self.document = SaveDocument.from_bytes(step.before)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        step = self._redo.pop()
        self._undo.append(step)
        self.document = SaveDocument.from_bytes(step.after)
        return True

    def discard(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self.document = self.original

    def audit(self) -> dict:
        return {'operations': self.operations,
                'semantic_changes': semantic_diff(self.original.values, self.document.values),
                'validation': {'reread_ok': SaveDocument.from_bytes(self.document.raw).values == self.document.values,
                               'every_step_reversible': all(s.validation['reverse_matches_input'] for s in self._undo),
                               'game_load_tested_for_this_output': False,
                               'historical_user_validation': 'Almas: usuário confirmou persistência após reiniciar o jogo.'},
                'experimental_operations': self.experimental,
                'source_sha256': self.original.sha256, 'output_sha256': self.document.sha256}


def loadout_reference(doc: SaveDocument, entry: dict) -> str | None:
    """Return the saved preset reference at this slot, never call it live gear."""
    preset = doc.values.get('SaveGameInventory', {}).get('SelectedCustomLoadout', {})
    if not isinstance(preset,dict):return None
    slot = clean_enum(entry.get('EquipmentSlot'))
    idx = entry.get('EquipmentSlotIndex', -1)
    singles = {'Head': 'HeadItem', 'Body': 'BodyItem', 'Arms': 'ArmsItem', 'Legs': 'LegsItem',
               'HealthFlask': 'HealthFlaskItem', 'ManaFlask': 'ManaFlaskItem', 'Throwable': 'ThrowableItem'}
    arrays = {'RightHand': 'RightHandItems', 'LeftHand': 'LeftHandItems', 'Trinket': 'TrinketItems',
              'Amulet': 'AmuletItems', 'Consumable': 'ConsumableItems'}
    if slot in singles:
        return preset.get(singles[slot])
    vals = preset.get(arrays.get(slot, ''), [])
    result=vals[idx] if isinstance(vals,list) and type(idx) is int and 0<=idx<len(vals) else None
    return result if isinstance(result,str) else None
