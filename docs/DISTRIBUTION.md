# Distribution policy

- Original Python source, authored UI wording, documentation and procedural geometric icons are published under MIT.
- Object paths, enum values, field names, numeric attribute records and index mappings are compatibility metadata. Their inclusion does not transfer ownership of the game or grant rights to other game content.
- Extracted game pictures, official localized item names/descriptions, original localization tables, raw FModel exports and game binaries are excluded. No permission to redistribute these was provided.
- Personal saves, Steam metadata, backups, machine paths and credentials are excluded.
- FModel and UE4SS are credited as external research tools, with upstream links. No copies are distributed.
- Binary distribution includes separate third-party notices, license texts, replaceable Qt shared libraries and matching corresponding-source archives. Do not apply the editor MIT license to Qt, Python or other third-party work.

Run `python tools/audit_public.py` before publishing. The checked resource manifest is an allowlist of this reviewed public edition. It is not evidence of permission for arbitrary replacement files. Keep private imports outside tracked folders. Never commit locally imported game content or attach a private build to a release.

[Nexus file submission guidelines](https://help.nexusmods.com/article/28-file-submission-guidelines) require appropriate rights; credit alone is insufficient. This document records the publication boundary, not a guarantee concerning every jurisdiction or future contribution.

## Original v0.3.1 legacy download

The separately published original v0.3.1 portable ZIP contains extracted game artwork and official localized names/descriptions. These are third-party game content, not MIT-licensed editor assets. No permission to redistribute them has been obtained from the rights holders. Attribution does not supply permission. The resource exclusions above apply to the repository source and v0.3.2 public edition. See [version notes](VERSION_0.3.1.md) for scope and the original checksum. This notice does not establish legal clearance or Nexus approval.
