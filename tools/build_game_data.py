"""Build the small runtime catalogue from the user's FModel export.

The source export is only required at build time. The editor reads game_data.json
and the selected PNGs; it never needs the original game installation or export.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from PIL import Image


LANGUAGES = {"pt": "Português", "en": "English", "de": "Deutsch", "es": "Español",
             "fr": "Français", "it": "Italiano", "ja": "日本語", "zh": "简体中文"}
QUALITY_NAMES = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]
NO_DESCRIPTION = {"pt": "O jogo não fornece uma descrição para este efeito no material exportado.",
                  "en": "The exported game data contains no description for this effect.",
                  "de": "Die exportierten Spieldaten enthalten keine Beschreibung für diesen Effekt.",
                  "es": "Los datos exportados del juego no contienen una descripción de este efecto.",
                  "fr": "Les données exportées du jeu ne contiennent aucune description de cet effet.",
                  "it": "I dati di gioco esportati non contengono una descrizione di questo effetto.",
                  "ja": "エクスポートされたゲームデータに、この効果の説明はありません。",
                  "zh": "导出的游戏数据中没有此效果的描述。"}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def plain(text):
    return re.sub(r"<[^>]*>", "", text or "").replace("\\n", "\n").strip()


def asset_package(reference):
    if isinstance(reference, dict):
        reference = reference.get("AssetPathName") or reference.get("ObjectPath") or ""
    return str(reference or "").split(".", 1)[0]


def interpolate(row, level):
    keys = sorted(row.get("Keys", []), key=lambda x: x["Time"])
    if not keys:
        return None
    if level <= keys[0]["Time"]:
        return keys[0]["Value"]
    for a, b in zip(keys, keys[1:]):
        if level <= b["Time"]:
            if row.get("InterpMode", "").endswith("RCIM_Constant"):
                return a["Value"]
            return a["Value"] + (b["Value"] - a["Value"]) * (level - a["Time"]) / (b["Time"] - a["Time"])
    return keys[-1]["Value"]


class Builder:
    def __init__(self, content, output):
        self.content, self.output = content, output
        self.languages = {code: load_json(content / "Localization/Game" / code / "Game.json")
                          for code in LANGUAGES if (content / "Localization/Game" / code / "Game.json").exists()}
        self.images = {str(f.relative_to(content).with_suffix("")).replace("\\", "/").lower(): f
                       for f in content.rglob("*.png")}
        self.copied = {}
        self.missing_icons = []

    def localized(self, reference, fallback=""):
        reference = reference or {}
        table = str(reference.get("TableId", "")).split(".")[-1]
        key = reference.get("Key", "")
        source = reference.get("SourceString") or reference.get("LocalizedString") or fallback
        return {code: plain(data.get(table, {}).get(key) or source) for code, data in self.languages.items()}

    def localized_fallback(self, reference, english, portuguese="", preferred=()):
        """Some item JSONs existed only in the previous supplied export archive.

        Their exact English string is still available in the old catalogue. Match
        it against a string-table entry, then use that same key in all languages.
        This preserves translations without guesses based on internal filenames.
        """
        if reference:
            return self.localized(reference, english)
        tables = self.languages.get("en", {})
        matches = [(table, key) for table, values in tables.items() if table.startswith("ST_")
                   for key, value in values.items() if value == english and english]
        if matches:
            matches.sort(key=lambda pair: (pair[0] not in preferred, pair[0], pair[1]))
            table, key = matches[0]
            return {code: plain(data.get(table, {}).get(key) or english) for code, data in self.languages.items()}
        return {code: plain(portuguese if code == "pt" and portuguese else english) for code in self.languages}

    def icon(self, reference):
        pkg = asset_package(reference)
        rel = pkg.removeprefix("/Game/").lower()
        source = self.images.get(rel)
        if not source:
            if pkg:
                self.missing_icons.append(pkg)
            return ""
        if source in self.copied:
            return self.copied[source]
        digest = hashlib.sha1(str(source.relative_to(self.content)).encode()).hexdigest()[:8]
        target = self.output / "assets/icons" / (source.stem + "_" + digest + ".png")
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as img:
            img.thumbnail((256, 256), Image.Resampling.LANCZOS)
            img.save(target, optimize=True)
        result = target.relative_to(self.output).as_posix()
        self.copied[source] = result
        return result

    def ui_image(self, source, filename, size=None):
        source = self.content / source
        if not source.exists():
            return ""
        target = self.output / "assets/ui" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as img:
            if size:
                img.thumbnail(size, Image.Resampling.LANCZOS)
            img.save(target, optimize=True)
        return target.relative_to(self.output).as_posix()

    def item(self, item):
        source = self.content / Path(item["package_name"].removeprefix("/Game/") + ".json")
        exports = load_json(source) if source.exists() else []
        props = next((x.get("Properties", {}) for x in exports if x.get("Name") == item["asset_name"]), {})
        menu = props.get("MenuDisplay", {})
        rows = item.get("table_rows", {})
        stats = (rows.get("ItemsAttributesRow") or {}).get("raw_row", {})
        factors = (rows.get("ItemFactorAttributesRow") or {}).get("raw_row", {})
        effects = [asset_package(x.get("raw")) + "." + x.get("referenced_name", "")
                   for x in item.get("additional_effects", [])]
        allowed = (rows.get("ItemBoonOptionsRow") or {}).get("raw_row", {}).get("Boons", [])
        allowed_effects = []
        for entry in allowed:
            ref = entry.get("Boon", {})
            name = ref.get("ObjectName", "").split("'")[-2] if "'" in ref.get("ObjectName", "") else ""
            if name:
                allowed_effects.append(asset_package(ref) + "." + name)
        icon = self.icon(menu.get("Icon") or item.get("icon_reference"))
        if not icon:
            icon = self.icon(menu.get("LargeIcon") or item.get("large_icon_reference"))
        tags = props.get("Tags", {}).get("Tags", [])
        grip = "Unknown"
        grip_source = ""
        if item["type"] == "InventoryItemWeapon":
            category_key = menu.get("Category", {}).get("Key", "")
            moveset = asset_package(props.get("Moveset", {}).get("Moveset", {}))
            if any(".TwoHanded" in tag for tag in tags):
                grip, grip_source = "TwoHanded", "exported_gameplay_tag"
            elif any(".OneHanded" in tag for tag in tags):
                grip, grip_source = "OneHanded", "exported_gameplay_tag"
            elif category_key.startswith("TwoHanded"):
                grip, grip_source = "TwoHanded", "exported_category_key"
            elif category_key.startswith("OneHanded") or "OneHanded" in moveset:
                grip, grip_source = "OneHanded", "exported_category_or_moveset"
        return {"id": item["asset_name"], "object_path": item["object_path"], "type": item["type"],
                "category_id": item["category_id"],
                "names": self.localized_fallback(menu.get("DisplayName"), item["name_en"], item["name_pt"], ("ST_Trinkets", "ST_WeaponArts")),
                "descriptions": self.localized_fallback(menu.get("Description"), item["description_en"], item["description_pt"], ("ST_Trinkets", "ST_WeaponArts")),
                "categories": self.localized(menu.get("Category"), item["category"]),
                "icon": icon,
                "effect_paths": effects, "allowed_effect_paths": allowed_effects,
                "stats": stats, "factor_stats": factors,
                "stats_note": "exported_base_values",
                "use_factor_stats": bool(props.get("UseItemFactorAttributes", False)),
                "weapon_handedness": grip, "weapon_handedness_source": grip_source,
                "weapon_tags": tags,
                "review_flags": item.get("review_flags", [])}

    def utility_items(self):
        """Known save references whose Inventory JSONs were absent from this export.

        The runtime uses these for display and editing existing stack counts only;
        they never expand the original gear replacement whitelist.
        """
        specs = [
            ("/Game/Data/Inventory/Consumables/IICo_OathboundOil", "InventoryItemConsumable", "Consumable", "ST_Consumables", "OathboundElixirName", "OathboundElixirDesc", "UI/Icons/Items/T_Icon_Consumable_Oathbound_512", "matched_name_and_visual_asset"),
            ("/Game/Data/Inventory/Throwables/ThrowingKnife/IICo_BloodseekerKnife", "InventoryItemThrowable", "Throwable", "ST_Consumables", "BloodseekerBladeName", "BloodseekerBladeDesc", "UI/Icons/Items/T_Icon_ThrowingKnives_Bloodseeker_512", "matched_name_and_visual_asset"),
            ("/Game/Data/Inventory/Throwables/ThrowingKnife/IICo_ThrowingKnife", "InventoryItemThrowable", "Throwable", "ST_Consumables", "ThrowingKnifeName", "ThrowingKnifeDesc", "UI/Icons/Items/T_Icon_ThrowingKnives_512", "matched_name_and_visual_asset"),
            ("/Game/Data/Inventory/Potions/Flasks/IIF_HealthFlask", "InventoryItemFlask", "HealthFlask", "", "B4F7824449B82B0FA3402B839BAF1034", "", "UI/Icons/Items/T_HealingFlask", "visual_asset_name_fallback"),
            ("/Game/Data/Inventory/Potions/Flasks/IIF_ManaFlask", "InventoryItemFlask", "ManaFlask", "", "1AA4395B41945AD3BD268BB89267BDAF", "", "UI/Icons/Items/T_DistilledAether", "visual_asset_name_fallback"),
            ("/Game/Data/Inventory/Currency/IC_GoldCoins", "InventoryItemCurrency", "All", "", "018A69384FB16C6B155AD183617BC9D2", "", "UI/Icons/Items/T_GoldCoins", "matched_visual_asset"),
            ("/Game/Data/Inventory/Currency/IC_Souls", "InventoryItemCurrency", "All", "", "2D5F725A48555E618BFC718BC41334BF", "", "UI/Icons/HUD/Currency/T_UI_HUD_Currency_Icon_128x128", "matched_hud_texture"),
        ]
        result = {}
        for package, type_name, slot, table, name_key, desc_key, image, icon_status in specs:
            ident = package.rsplit("/", 1)[-1]
            path = package + "." + ident
            result[path] = {"id": ident, "object_path": path, "type": type_name,
                            "category_id": "currency" if type_name.endswith("Currency") else "utilities",
                            "names": {code: plain(loc.get(table, {}).get(name_key, ident)) for code, loc in self.languages.items()},
                            "descriptions": {code: plain(loc.get(table, {}).get(desc_key, "")) for code, loc in self.languages.items()},
                            "icon": self.icon("/Game/" + image), "icon_reference_status": icon_status,
                            "equipment_slot": slot, "stats": {}, "factor_stats": {},
                            "effect_paths": [], "allowed_effect_paths": [], "review_flags": ["display_only_definition"],
                            "source_note": "Referenced by saved inventory; display text and texture available, full InventoryItem export absent."}
        return result

    def angel_data(self):
        result = {}
        for source in sorted((self.content / "Characters/PlayerCharacters/Angels").rglob("DA_Angel_*.json")):
            export = next((e for e in load_json(source) if e.get("Type") == "AngelDataAsset"), None)
            if not export:
                continue
            props = export.get("Properties", {})
            path = export["Package"] + "." + export["Name"]
            result[path] = {"id": export["Name"], "object_path": path,
                            "names": self.localized(props.get("AngelDisplayName"), export["Name"]),
                            "descriptions": self.localized(props.get("AngelDescription")),
                            "icon": self.icon(props.get("AngelIcon")),
                            "portrait": "assets/ui/portrait_azrael.png" if "Azrael" in export["Name"] else "assets/ui/portrait.png"}
        return result

    def blessing(self, source, curves):
        exports = load_json(source)
        ui = next((x.get("Properties", {}) for x in exports if x.get("Type") == "CoreGameplayEffectUIData"), None)
        default = next((x for x in exports if x.get("Name") == "Default__" + source.stem + "_C"), None)
        if not ui or not default or not ui.get("EffectUIName"):
            return None
        pkg = default.get("Package") or "/Game/" + source.relative_to(self.content).with_suffix("").as_posix()
        ident = source.stem.removeprefix("GE_Boon_")
        names = self.localized(ui.get("EffectUIName"), ident)
        desc_ref = ui.get("EffectDescription", {})
        desc_table = str(desc_ref.get("TableId", "")).split(".")[-1]
        desc_key = desc_ref.get("Key", "")
        base_key = desc_key.removesuffix("_Dynamic")
        descriptions = self.localized({**desc_ref, "Key": base_key})
        experimental = not descriptions.get("en")
        if experimental:
            names = {code: re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name) for code, name in names.items()}
            descriptions = {code: NO_DESCRIPTION[code] for code in self.languages}
        dynamic_key = base_key + "_Dynamic"
        dynamic = {code: plain(data.get(desc_table, {}).get(dynamic_key, ""))
                   for code, data in self.languages.items()}
        # Only replace placeholders where the export explicitly provides the matching
        # curve. Most native ability formulas are absent from FModel JSON exports.
        curve = curves.get(ident)
        by_level = {}
        if curve:
            for level in range(1, 6):
                value = interpolate(curve, level)
                formatted = f"{value:g}"
                by_level[str(level)] = {code: text.replace("{0}", formatted)
                                       for code, text in dynamic.items()
                                       if text and set(re.findall(r"\{(\d+)\}", text)) <= {"0"}}
        fixed = {code: text for code, text in dynamic.items() if text and not re.search(r"\{\d+\}", text)}
        if fixed:
            for level in range(1, 6):
                by_level.setdefault(str(level), {}).update(fixed)
        params = default.get("Properties", {})
        return {"id": ident, "effect_path": pkg + "." + source.stem + "_C",
                "default_object_path": pkg + "." + default["Name"],
                "names": names, "descriptions": descriptions, "descriptions_by_level": by_level,
                "dynamic_descriptions": dynamic, "description_kind": "exported_base_text",
                "icon": self.icon(ui.get("EffectIcon")),
                "min_level": 1, "max_level": 5, "max_stacks": 1,
                "source_stack_limit": params.get("StackLimitCount", 1), "experimental": experimental,
                "keyword_tags": ui.get("KeywordTags", []),
                "scaling_curve": curve.get("Keys", []) if curve else []}

    def build(self):
        old = load_json(self.output / "data/catalogo.json")
        items = {x["object_path"]: self.item(x) for x in old["items"]}
        items.update(self.utility_items())
        curves = load_json(self.content / "GameSystems/GAS/CT_ScalingBoons.json")[0]["Rows"]
        blessings = []
        for source in sorted((self.content / "GameSystems/GAS/Effects/Boons").rglob("GE_Boon_*.json")):
            entry = self.blessing(source, curves)
            if entry:
                blessings.append(entry)
        labels = {}
        for code, loc in self.languages.items():
            labels[code] = {**loc.get("ST_ItemDetailLabels", {}), **loc.get("ST_ATTRIBUTES", {}),
                            **loc.get("ST_InventoryScreens", {})}
        ui = {
            "equipment_bg": self.ui_image("UI/Common/Decorative/T_InventoryEquipmentBG.png", "equipment_bg.png"),
            "portrait": self.ui_image("UI/Icons/Progression/Angelic_Form/T_Angel_Aegis.png", "portrait.png", (384, 384)),
            "portrait_azrael": self.ui_image("UI/Icons/Progression/Angelic_Form/T_Angel_Azrael.png", "portrait_azrael.png", (384, 384)),
            "logo": self.ui_image("UI/CM_UI/Foundation/Icon/T_CM_Logo_Transparent_C.png", "logo.png", (768, 384)),
            "boon_glass": self.ui_image("UI/Icons/HUD/Boons/T_IMG_Boon_StainedGlass.png", "boon_glass.png"),
            "boon_outline": self.ui_image("UI/Icons/HUD/Boons/T_IMG_Boon_SlotOutline_Default.png", "boon_outline.png"),
            "item_glass": self.ui_image("UI/Shared_PMUI/Textures/EquipmentTile/T_PMUI_ItemRarity_Rosette.png", "item_glass.png", (256, 256)),
            "coins": self.ui_image("UI/Icons/Items/T_GoldCoins.png", "coins.png", (128, 128)),
            "souls": self.ui_image("UI/Icons/HUD/Currency/T_UI_HUD_Currency_Icon_128x128.png", "souls.png", (128, 128)),
            "skull": self.ui_image("UI/Icons/WartableIcons/T_WarTable_Icon_Skull_128x128.png", "skull.png", (128, 128)),
            "equipment_card_bg": self.ui_image("UI/Shared_PMUI/Textures/EquipmentTile/T_PMUI_EquipmentItem_Bg_Base.png", "equipment_card_bg.png"),
            "equipment_card_frame": self.ui_image("UI/Shared_PMUI/Textures/EquipmentTile/T_PMUI_EquipmentItem_Frame.png", "equipment_card_frame.png"),
            "empty_card_bg": self.ui_image("UI/Icons/Items/T_EmptySlotBG.png", "empty_card_bg.png"),
            "empty_card_frame": self.ui_image("UI/Icons/Items/T_EmptySlotFrame.png", "empty_card_frame.png"),
            "placeholder_twohand": self.ui_image("UI/Icons/Inventory/T_Inventory_Itemlist_Axe.png", "placeholder_twohand.png"),
            "placeholder_throwable": self.ui_image("UI/Icons/Inventory/T_ICN_TabMenu_ThrowingWeapons.png", "placeholder_throwable.png"),
            "placeholder_consumable": self.ui_image("UI/Icons/Inventory/T_Inventory_Itemlist_Bottle.png", "placeholder_consumable.png"),
            "placeholder_weapon": self.ui_image("UI/Icons/Inventory/T_ICN_TabMenu_Weapons.png", "placeholder_weapon.png"),
        }
        with Image.open(self.output / ui["logo"]) as logo:
            logo = logo.convert("RGBA")
            logo.thumbnail((256, 256), Image.Resampling.LANCZOS)
            icon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            icon.alpha_composite(logo, ((256 - logo.width) // 2, (256 - logo.height) // 2))
            icon.save(self.output / "assets/ui/app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        ui["app_icon"] = "assets/ui/app.ico"
        data = {"schema": 1, "languages": [{"id": code, "label": LANGUAGES[code]} for code in self.languages],
                "items": items, "blessings": blessings, "labels": labels, "ui_assets": ui,
                "angels": self.angel_data(),
                "qualities": [{"id": name, "level": level,
                               "names": {code: labels[code].get("Quality_" + name, name) for code in self.languages}}
                              for level, name in enumerate(QUALITY_NAMES, 1)],
                "progression": {},
                "inventory_layout": {"slot_key": ["EquipmentSlot", "EquipmentSlotIndex"],
                                     "preset_array_capacities": {"RightHand": 3, "LeftHand": 3, "Consumable": 8, "Trinket": 4, "Amulet": 1},
                                     "note": "Serialized preset array sizes; usable slots may be gated by progression. RightHand index is an alternate weapon index, not a distinct two-handed enum.",
                                     "angel_path": "SaveGameInventory/AngelAsset"},
                "provenance": {"source": "User-supplied CrimsonMoonNG FModel export", "item_count": len(items),
                               "description_note": "Base descriptions are official localization text. Only curves explicitly exported are resolved for each quality. Final gameplay values may depend on native game logic.",
                               "missing_icons": sorted(set(self.missing_icons))}}
        (self.output / "data/game_data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(json.dumps({"items": len(items), "blessings": len(blessings), "languages": list(self.languages),
                          "icons": len(self.copied), "missing_icons": sorted(set(self.missing_icons)),
                          "level_descriptions": sum(bool(x["descriptions_by_level"]) for x in blessings)}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", type=Path, required=True, help="Path to the exported CrimsonMoonNG Content folder")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1]/"local_resources")
    args = parser.parse_args()
    public_root = Path(__file__).resolve().parents[1]
    if args.output.resolve() == public_root:
        parser.error("Private resources must not overwrite the tracked public edition.")
    if not (args.output/"data/catalogo.json").exists():
        args.output.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copytree(public_root/"data", args.output/"data", dirs_exist_ok=True)
    (args.output/"PRIVATE_GAME_RESOURCES").write_text("Local-only game resources; do not redistribute.\n", encoding="utf-8")
    Builder(args.content, args.output).build()


if __name__ == "__main__":
    main()
