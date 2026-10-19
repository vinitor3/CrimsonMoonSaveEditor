"""Read-only localized game data used by the portable desktop interface."""
from __future__ import annotations

import json
from pathlib import Path


class GameData:
    def __init__(self, base, data):
        self.base = Path(base)
        self.data = data
        self.items = data.get("items", {})
        self.blessings = data.get("blessings", [])
        self.languages = data.get("languages", [])
        self.labels = data.get("labels", {})
        self.qualities = data.get("qualities", [])
        self.ui_assets = data.get("ui_assets", {})
        self.progression = data.get("progression", {})
        self.by_blessing_path = {}
        self.by_blessing_id = {}
        for blessing in self.blessings:
            self.by_blessing_id[blessing["id"]] = blessing
            for key in ("effect_path", "default_object_path"):
                self.by_blessing_path[blessing[key]] = blessing

    @classmethod
    def load(cls, base):
        base = Path(base)
        folder = base if (base / "game_data.json").exists() else base / "data"
        data = json.loads((folder / "game_data.json").read_text(encoding="utf-8"))
        if data.get("schema") != 1:
            raise ValueError("Unsupported game catalogue schema")
        return cls(folder.parent, data)

    @staticmethod
    def text(entry, field="names", lang="pt", fallback=""):
        values = (entry or {}).get(field, {})
        if isinstance(values, str):
            return values or fallback
        return values.get(lang) or values.get("en") or values.get("pt") or next(iter(values.values()), fallback)

    def item(self, path):
        return self.items.get(path)

    def blessing(self, path):
        return self.by_blessing_path.get(path) or self.by_blessing_id.get(path)

    def icon_path(self, entry):
        path = (entry or {}).get("icon", "")
        return str(self.base / path) if path else ""

    def ui_path(self, name):
        path = self.ui_assets.get(name, "")
        return str(self.base / path) if path else ""

    def label(self, key, lang="pt"):
        return self.labels.get(lang, {}).get(key) or self.labels.get("en", {}).get(key) or key

    def description(self, entry, lang="pt", level=None):
        if level is not None:
            variants = (entry or {}).get("descriptions_by_level", {}).get(str(int(level)), {})
            if variants.get(lang):
                return variants[lang]
        return self.text(entry, "descriptions", lang)

    def description_is_scaled(self, entry, lang="pt", level=None):
        return bool(level is not None and (entry or {}).get("descriptions_by_level", {}).get(str(int(level)), {}).get(lang))
