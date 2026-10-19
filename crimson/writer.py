"""Targeted GVAS edits with nested size repair; untouched bytes are copied verbatim.

This is not a generic serializer. Public editing rules live in editing.py. The
legacy same-size currency writer stays available in service.py for regression.
"""
from __future__ import annotations

from copy import deepcopy
import math
import struct
from typing import Any

from .gvas import MAX_FILE, MAX_STRING, Property, Reader, SaveDocument, SaveError
from .service import semantic_diff

STRING_TYPES = {'StrProperty', 'NameProperty', 'ObjectProperty', 'ClassProperty', 'EnumProperty'}
INT_TYPES = {'IntProperty': ('i', -(2**31), 2**31-1), 'Int64Property': ('q', -(2**63), 2**63-1)}


def pack_string(text: str, original: bytes | None = None) -> bytes:
    if type(text) is not str or '\0' in text:
        raise SaveError('Texto inválido para uma referência do save.')
    wide = bool(original and len(original) >= 4 and struct.unpack('<i', original[:4])[0] < 0)
    raw = text.encode('utf-16-le' if wide else 'utf-8') + (b'\0\0' if wide else b'\0')
    if len(raw) > MAX_STRING:
        raise SaveError('Texto excede o limite do leitor.')
    # Preserve even unusual empty-string encodings on a no-op.
    if original is not None:
        r = Reader(original)
        if r.string() == text and r.pos == len(original):
            return original
    return struct.pack('<i', -len(raw)//2 if wide else len(raw)) + raw


def tag_positions(doc: SaveDocument, p: Property) -> tuple[int, int]:
    r = Reader(doc.raw, p.start, p.payload_start)
    if r.string() != p.name or r.type_node() != p.type:
        raise SaveError('Tag inconsistente com os metadados de leitura.')
    size_offset = r.pos
    if r.u32() != p.size:
        raise SaveError('Tamanho da tag diverge da leitura.')
    flags_offset = r.pos
    if r.number('B') != p.flags:
        raise SaveError('Flags da tag divergem da leitura.')
    return size_offset, flags_offset


def encode_property(doc: SaveDocument, p: Property, value: Any) -> bytes:
    raw = doc.raw[p.payload_start:p.end]
    if p.value == value and type(p.value) is type(value):
        return raw
    kind = p.type.name
    if kind in INT_TYPES:
        fmt, low, high = INT_TYPES[kind]
        if type(value) is not int or not low <= value <= high:
            raise SaveError('Inteiro fora dos limites do campo.')
        return struct.pack('<' + fmt, value)
    if kind in ('FloatProperty', 'DoubleProperty'):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise SaveError('O campo exige um número finito.')
        try:
            data = struct.pack('<f' if kind == 'FloatProperty' else '<d', value)
        except (OverflowError, struct.error) as exc:
            raise SaveError('Número fora da precisão representável.') from exc
        if not math.isfinite(struct.unpack('<f' if kind == 'FloatProperty' else '<d', data)[0]):
            raise SaveError('Número fora da precisão representável.')
        return data
    if kind in STRING_TYPES or (kind == 'ByteProperty' and p.type.inner):
        return pack_string(value, raw)
    if kind in ('SoftObjectProperty', 'SoftClassProperty'):
        if type(value) is not dict or set(value) != {'PackageName', 'AssetName', 'SubPath'}:
            raise SaveError('Referência flexível inválida.')
        r = Reader(raw)
        result = []
        for key in ('PackageName', 'AssetName', 'SubPath'):
            start = r.pos
            r.string()
            result.append(pack_string(value[key], raw[start:r.pos]))
        if r.pos != len(raw):
            raise SaveError('Referência flexível com bytes inesperados.')
        return b''.join(result)
    if kind == 'ArrayProperty' and len(p.type.inner) == 1 and p.type.inner[0].name in STRING_TYPES:
        if type(value) is not list or len(value) != len(p.value):
            raise SaveError('A edição desta lista deve preservar a quantidade de posições.')
        r = Reader(raw)
        count = r.count()
        result = [raw[:r.pos]]
        if count != len(value):
            raise SaveError('Contagem de lista inconsistente.')
        for item in value:
            start = r.pos
            r.string()
            result.append(pack_string(item, raw[start:r.pos]))
        if r.pos != len(raw):
            raise SaveError('Lista de referências não foi consumida exatamente.')
        return b''.join(result)
    raise SaveError(f'Edição não implementada para {kind}. Os bytes foram preservados.')


def splice_payloads(doc: SaveDocument, payloads: dict[str, bytes], *, booleans: dict[str, bool] | None = None) -> bytes:
    """Internal: replace complete payloads and repair *all* enclosing tag sizes.

    Reject parent+child patches together. Boolean tagged values live in flag
    bit 0x10, not in a data byte. Native/opaque fields must not be edited by callers.
    """
    replacements: list[tuple[int, int, bytes]] = []
    edited: list[tuple[Property, int]] = []
    for path, raw in payloads.items():
        p = doc.properties.get(path)
        if p is None or type(raw) is not bytes:
            raise SaveError('Patch sem propriedade ou sem bytes válidos.')
        if p.type.name == 'BoolProperty':
            raise SaveError('Booleanos devem ser alterados na flag da tag.')
        if raw == doc.raw[p.payload_start:p.end]:
            continue
        if any(x['path'] == path for x in doc.opaque):
            raise SaveError('Campo opaco não é editável.')
        replacements.append((p.payload_start, p.end, raw))
        edited.append((p, len(raw) - p.size))
    ordered = sorted(replacements, key=lambda x: (x[0], x[1]))
    for a, b in zip(ordered, ordered[1:]):
        if a[1] > b[0]:
            raise SaveError('Não aplique simultaneamente patches sobrepostos ou pai/filho.')
    # Containment in the byte tree is used; no guessed absolute offsets.
    for q in doc.properties.values():
        delta = sum(delta for p, delta in edited if q.payload_start <= p.payload_start and p.end <= q.end)
        if delta:
            size = q.size + delta
            if not 0 <= size <= MAX_FILE:
                raise SaveError('Novo contêiner excede o limite do leitor.')
            size_pos, _ = tag_positions(doc, q)
            replacements.append((size_pos, size_pos+4, struct.pack('<I', size)))
    for path, val in (booleans or {}).items():
        p = doc.properties.get(path)
        if p is None or p.type.name != 'BoolProperty' or p.size != 0 or type(val) is not bool:
            raise SaveError('Flag booleana inválida.')
        if val == p.value:
            continue
        _, flag_pos = tag_positions(doc, p)
        flags = (p.flags | 0x10) if val else (p.flags & ~0x10)
        replacements.append((flag_pos, flag_pos+1, bytes([flags])))
    if not replacements:
        return doc.raw
    replacements.sort(key=lambda x: (x[0], x[1]))
    out, cursor = [], 0
    for start, end, raw in replacements:
        if start < cursor or start < doc.root_start or end > doc.root_end:
            raise SaveError('Patches sobrepostos ou fora da raiz.')
        out.extend([doc.raw[cursor:start], raw])
        cursor = end
    out.append(doc.raw[cursor:])
    result = b''.join(out)
    if len(result) > MAX_FILE:
        raise SaveError('Save excede o tamanho suportado.')
    return result


def at_path(values: Any, path: str) -> Any:
    node = values
    for part in path.strip('/').split('/'):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def set_path(values: Any, path: str, value: Any) -> None:
    parts = path.strip('/').split('/')
    node = values
    for key in parts[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    key = int(parts[-1]) if isinstance(node, list) else parts[-1]
    node[key] = deepcopy(value)


def edit_fields(doc: SaveDocument, changes: dict[str, Any]) -> tuple[bytes, dict]:
    """Edit supported *existing* fields, reread and match the full expected tree.

    No new items, map entries or unknown properties are synthesized here. This
    is deliberately narrower than a full SaveGame serializer.
    """
    if not changes:
        return doc.raw, {'semantic_changes': [], 'reverse_matches_input': True}
    expected = deepcopy(doc.values)
    payloads, bools, before = {}, {}, {}
    paths = sorted(changes)
    for i, path in enumerate(paths):
        if any(other.startswith(path + '/') for other in paths[i+1:]):
            raise SaveError('Não edite simultaneamente uma propriedade e seus campos.')
        p = doc.properties.get(path)
        if p is None:
            raise SaveError(f'Campo ausente: {path}.')
        before[path] = deepcopy(p.value)
        if p.type.name == 'BoolProperty':
            if type(changes[path]) is not bool:
                raise SaveError('O campo exige verdadeiro/falso.')
            bools[path] = changes[path]
        else:
            payloads[path] = encode_property(doc, p, changes[path])
        set_path(expected, path, changes[path])
    result = splice_payloads(doc, payloads, booleans=bools)
    new = SaveDocument.from_bytes(result)
    if new.values != expected:
        raise SaveError('A releitura divergiu da alteração solicitada. Nada foi aplicado em disco.')
    # Opaque fields can move but may never change their contents or identities.
    old_opaque = {p['path']: at_path(doc.values, p['path']) for p in doc.opaque}
    new_opaque = {p['path']: at_path(new.values, p['path']) for p in new.opaque}
    if old_opaque != new_opaque:
        raise SaveError('Conteúdo opaco foi alterado inesperadamente.')
    reverse_payloads, reverse_bools = {}, {}
    for path in changes:
        p = new.properties[path]
        if p.type.name == 'BoolProperty':
            reverse_bools[path] = before[path]
        else:
            # Original bytes, not re-encoded approximations, recover the input.
            old = doc.properties[path]
            reverse_payloads[path] = doc.raw[old.payload_start:old.end]
    restored = splice_payloads(new, reverse_payloads, booleans=reverse_bools)
    if restored != doc.raw:
        raise SaveError('A reversão não recuperou os bytes originais.')
    return result, {'semantic_changes': semantic_diff(doc.values, new.values),
                    'reverse_matches_input': True,
                    'source_bytes': len(doc.raw), 'output_bytes': len(result),
                    'opaque_fields_preserved': list(old_opaque)}
