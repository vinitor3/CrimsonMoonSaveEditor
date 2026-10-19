# Save format and supported edits

The parser supports the observed GVAS tagged-property character profile, preserving unknown property bytes. Full parse/rebuild equality, per-field write boundaries and reversible edits are tested with synthetic saves. Installed save tests are opt-in and never part of the public dataset.

Currency references use IC_GoldCoins and IC_Souls. Equipment uses object paths and typed slot/index pairs. Persistent effects use whitelisted default-object paths. The five skull choices map to saved modifiers 0, 15, 30, 45 and 60; a separately defined 75 value is preserved without claiming a sixth displayed skull. Custom values are not silently rounded.

Manual progression contains five mission positions across two stages. Only indices present in the compatibility catalog are offered. Some saves omit the explicit current-mission cursor; the editor does not invent that field. Unlock requirements and progression gates are not granted automatically.

Gold/souls, supported attributes, existing equipment replacements/rarity, persistent blessings, character names and supported consumable stack edits use typed operations. A two-handed weapon is a weapon with handedness metadata, not a new serialized equipment-slot enum.

Other save files (profile metadata, settings and control mappings) are not edited. Structural validity does not prove the game accepts every edited combination. Backups and a closed game are required before applying changes.
