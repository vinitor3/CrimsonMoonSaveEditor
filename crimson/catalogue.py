"""Local catalogue and comparisons based on the user's exported definitions.

Missing values are None, never an invented zero. Attribute and factor rows are
kept separate. No rarity multiplier, combat formula or subjective score is used.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
import unicodedata
from typing import Any
from .gvas import SaveError

TYPE_SLOTS = {
    'InventoryItemArmorArms': 'Arms', 'InventoryItemArmorBody': 'Body',
    'InventoryItemArmorHead': 'Head', 'InventoryItemArmorLegs': 'Legs',
    'InventoryItemWeapon': 'RightHand', 'InventoryItemShield': 'LeftHand',
    'InventoryItemTrinket': 'Trinket', 'InventoryItemAmulet': 'Amulet',
}
SLOT_LABELS = {'Head': 'Cabeça', 'Body': 'Corpo', 'Arms': 'Braços', 'Legs': 'Pernas',
               'RightHand': 'Mão dominante', 'LeftHand': 'Mão secundária', 'Trinket': 'Acessório',
               'Amulet': 'Amuleto', 'All': 'Reserva / geral', 'Consumable': 'Consumível',
               'Throwable': 'Arremessável', 'HealthFlask': 'Frasco de vida', 'ManaFlask': 'Frasco de mana',
               'WeaponArt': 'Arte da arma'}
QUALITY_LABELS = {'Common': 'Comum', 'Uncommon': 'Incomum', 'Rare': 'Raro', 'Epic': 'Épico', 'Legendary': 'Lendário'}


def clean_enum(value: Any) -> str:
    return str(value or '').split('::')[-1]


def folded(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))


def format_number(value: Any) -> str:
    if value is None:
        return '—'
    if type(value) not in (int, float):
        return str(value)
    if isinstance(value, float):
        value = round(value, 6)
        if value.is_integer():
            value = int(value)
    return f'{value:,}'.replace(',', '@').replace('.', ',').replace('@', '.')


@dataclass
class Catalogue:
    items: list[dict]
    labels: dict
    metadata: dict

    def __post_init__(self):
        self.by_path: dict[str, dict] = {}
        self.by_asset: dict[str, dict] = {}
        self.search_text = {}
        for item in self.items:
            path, pkg, asset = item['object_path'], item['package_name'], item['asset_name']
            if (not pkg.startswith('/Game/') or path != pkg + '.' + asset or not asset
                    or pkg.rsplit('/', 1)[-1] != asset or path in self.by_path):
                raise SaveError('Catálogo com caminho incompleto ou duplicado.')
            self.by_path[path] = item
            self.by_asset[asset] = item
            effects = self.effect_text(item)
            self.search_text[path] = folded(' '.join([item['name_pt'], item['name_en'], asset,
                                                     path, item['description_pt'], effects]))

    @classmethod
    def load(cls, folder: str | Path) -> 'Catalogue':
        folder = Path(folder)
        data = json.loads((folder/'catalogo.json').read_text(encoding='utf-8'))
        labels = json.loads((folder/'textos_pt.json').read_text(encoding='utf-8'))
        if data.get('schema') != 2 or not isinstance(data.get('items'), list):
            raise SaveError('Versão do catálogo não suportada.')
        return cls(data['items'], labels, {k: v for k, v in data.items() if k != 'items'})

    def search(self, query: str = '', *, category: str | None = None, type_name: str | None = None,
               hide_special: bool = False) -> list[dict]:
        tokens = folded(query).split()
        result = []
        for item in self.items:
            if category and item['category_id'] != category:
                continue
            if type_name and item['type'] != type_name:
                continue
            if hide_special and self.block_reason(item):
                continue
            if all(token in self.search_text[item['object_path']] for token in tokens):
                result.append(item)
        return sorted(result, key=lambda x: (folded(x['name_pt']), x['asset_name']))

    def item(self, path: str) -> dict:
        if path not in self.by_path:
            raise SaveError('A definição deste item não está no catálogo recebido.')
        return self.by_path[path]

    def name(self, path: str) -> str:
        if path in self.by_path:
            return self.by_path[path]['name_pt']
        asset = path.rsplit('.', 1)[-1]
        return {'IC_Souls': 'Almas', 'IC_GoldCoins': 'Dinheiro'}.get(asset, asset or 'Sem referência')

    @staticmethod
    def block_reason(item: dict) -> str | None:
        if item['type'] not in TYPE_SLOTS:
            return 'Esta categoria está disponível somente para consulta nesta versão.'
        flags = set(item.get('review_flags', []))
        if flags & {'ftue_variant', 'angel_weapon_folder'}:
            return 'Variante de introdução ou arma de anjo: consulta permitida; troca bloqueada.'
        if item.get('default_stability_explicit') not in (None, 'EItemStability::Purifiable'):
            return 'Estabilidade especial exige uma regra ainda não validada.'
        return None

    def effect_name(self, name: str) -> str:
        key = name.removeprefix('GE_Boon_').removesuffix('_C')
        translated = self.labels.get('ST_Boons', {}).get(key)
        return f'{translated} [{name}]' if translated else name

    def effect_text(self, item: dict | None) -> str:
        if item is None:
            return 'Sem definição no catálogo.'
        refs = item.get('additional_effects', [])
        if not refs:
            return 'Nenhuma referência explícita em AdditionalEffects.'
        return '\n'.join(self.effect_name(x.get('referenced_name', '?')) for x in refs)

    def art_text(self, item: dict | None) -> str:
        if item is None:
            return 'Sem dados.'
        refs = item.get('auto_equip_weapon_arts', [])
        return '\n'.join((x.get('referenced_display_name') or {}).get('pt') or
                         x.get('referenced_name', '?') for x in refs) or 'Sem referência explícita.'

    def compare(self, current: dict | None, selected: dict | None, *, section: str = 'ItemsAttributesRow') -> list[dict]:
        if section not in ('ItemsAttributesRow', 'ItemFactorAttributesRow'):
            raise SaveError('Seção de comparação inválida.')
        def flatten(item):
            row = item.get('table_rows', {}).get(section) if item else None
            if not row:
                return {}, False
            output = {}
            def visit(node, path=''):
                if isinstance(node, dict):
                    for k, v in node.items():
                        visit(v, f'{path}/{k}' if path else k)
                elif type(node) in (float, int):
                    output[path] = node
            visit(row['raw_row'])
            return output, True
        a, has_a = flatten(current)
        b, has_b = flatten(selected)
        out = []
        labels = self.labels.get('ST_ItemDetailLabels', {})
        # Only suppress rows that are explicitly zero on both sides.
        for key in sorted(a.keys() | b.keys()):
            av, bv = a.get(key), b.get(key)
            if av == 0 and bv == 0:
                continue
            leaf = key.rsplit('/', 1)[-1]
            delta = None if av is None or bv is None else bv-av
            out.append({'key': key, 'label': labels.get(leaf, leaf), 'before': av, 'after': bv,
                        'delta': delta, 'group': key.split('/')[0]})
        if not has_a and not has_b:
            out.append({'key': '', 'label': 'Nenhuma linha explícita nesta seção', 'before': None,
                        'after': None, 'delta': None, 'group': ''})
        return out
