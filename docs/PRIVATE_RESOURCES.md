# Optional local resources

The public app works with generic icons and technical aliases. An existing privately customized editor may supply local game artwork/descriptions without putting them in this repository.

```powershell
python tools/import_private_resources.py --from-folder "D:\PrivateEditor"
$env:CM_EDITOR_RESOURCES = (Resolve-Path local_resources).Path
python crimson_editor.py
```

Use a folder containing both `data/` and `assets/`. The importer copies them into the gitignored `local_resources/` directory, creates a private-content marker and refuses an existing destination. It never reads installed saves. Do not share these files without permission from the rights holders. The runtime resource override also changes the backend catalogs, keeping interface and validated paths consistent.

Unset `CM_EDITOR_RESOURCES` before tests or public packaging. Public packaging refuses this override and verifies the original public resource manifest. The optional FModel export builder `tools/build_game_data.py` requires Pillow (`pip install -r requirements-dev.txt`); always target `local_resources`, never the tracked public data/assets folders. See its `--help` for arguments.
