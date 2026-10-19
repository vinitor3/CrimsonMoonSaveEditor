# Crimson Moon Save Editor

Unofficial Windows save editor by **vinitor3**, developed with **GPT / AI assistance**.

**Source code / v0.3.2 public edition:** original geometric icons, authored UI wording and technical interoperability metadata. No extracted game artwork or official item descriptions are included in the repository source or the v0.3.2 public ZIP.

## Version 0.3.1 — original legacy package

[Download v0.3.1](https://github.com/vinitor3/CrimsonMoonSaveEditor/releases/tag/v0.3.1) — portable Windows ZIP, no installer. This is the original 0.3.1 package, with in-game artwork and localized item/effect descriptions. The 0.3.2 public edition remains the current release.

**Game-content rights:** all extracted game artwork and official localization remain the property of the respective Crimson Moon rights holders. These resources are not covered by the editor's MIT license. No permission from the rights holders to redistribute them has been obtained; this notice is attribution, not authorization or endorsement. See [0.3.1 version notes](docs/VERSION_0.3.1.md).

Nexus automatic checks requiring manual review do not establish either malware or safety. A GitHub download is not Nexus approval; contact Nexus support to review the exact blocked file.

## Features

- Gold, souls and supported attributes; equipment replacement, rarity and numeric comparisons.
- Separate equipment slots, alternate weapons and a two-handed weapon view.
- Persistent blessings with quality selection and technical effect tooltips.
- Five skull difficulty selector; custom saved values are preserved.
- Manual campaign cursor: five mission positions across two stages, using known destination identifiers.
- Character rename and supported consumable stack quantities.
- Eight interface languages, reversible edits, explicit review, automatic backups and restore.

Some edits remain experimental. Structural tests do not prove every combination loads correctly in every game build. Close the game before applying edits and keep independent backups. Unknown save structures are refused.

## Run from source

Use Python 3.11 x64 on Windows 10/11. From the repository folder in PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe tools/bootstrap_public_assets.py
.venv\Scripts\python.exe crimson_editor.py
```

Open a character `.sav` through the interface. The default game save location is `%LOCALAPPDATA%\CrimsonMoonNG\Saved\SaveGames`. Backups and audit records use `%LOCALAPPDATA%\CrimsonMoonSaveEditor`. No game installation is required for synthetic tests.

## Tests and portable build

```powershell
.venv\Scripts\python.exe tools/run_tests.py
.venv\Scripts\python.exe tools/audit_public.py
.venv\Scripts\python.exe tools/package_release.py
```

The build produces a portable Windows ZIP and a companion ZIP containing the exact corresponding Qt/PySide library sources and licenses. **Distribute both ZIPs together.** No installer is required. The application source is included in the portable archive. The public build refuses local resource overrides and checks its resource manifest before packaging.

For optional local imports from an existing private editor folder, see [private resources](docs/PRIVATE_RESOURCES.md). They are excluded from publication. Source releases on GitHub can also be downloaded through **Code → Download ZIP**.

## License and attribution

Original editor code, documentation and geometric icon generator: [MIT](LICENSE). Third-party software retains its own licenses; see [notices](THIRD_PARTY_NOTICES.md), [credits](CREDITS.md) and [distribution policy](docs/DISTRIBUTION.md). Technical game identifiers are included for interoperability, with no ownership or license claim over the game or its trademarks. No affiliation with or endorsement by the game studio is claimed.

Repository: https://github.com/vinitor3/CrimsonMoonSaveEditor
