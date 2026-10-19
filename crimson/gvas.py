"""Leitor tipado + regravação lossless do perfil GVAS observado no Crimson Moon.

Não é um conversor GVAS universal. Os headers e bytes que não são editados
permanecem literalmente iguais. A escrita aceita apenas patches do mesmo tamanho
em propriedades primitivas já localizadas pela leitura, nunca por busca de texto.
Referência do layout genérico: uesave, PropertyTagFull e Header/Root (ver docs).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import hashlib
import struct

MAX_FILE = 32 * 1024 * 1024
MAX_STRING = 1024 * 1024
MAX_ENTRIES = 100_000
MAX_DEPTH = 64

class SaveError(ValueError):
    """Arquivo inválido, recurso não suportado ou operação recusada."""

class Unsupported(SaveError):
    """Formato fora do perfil suportado."""

@dataclass(frozen=True)
class TypeNode:
    name: str
    inner: tuple['TypeNode', ...] = ()

    def as_dict(self) -> dict:
        return {'name': self.name, 'inner': [x.as_dict() for x in self.inner]}

@dataclass(frozen=True)
class Property:
    path: str
    name: str
    type: TypeNode
    flags: int
    array_index: int
    start: int
    payload_start: int
    end: int
    value: Any

    @property
    def size(self) -> int:
        return self.end - self.payload_start

@dataclass
class Reader:
    data: bytes
    pos: int = 0
    limit: int | None = None
    properties: list[Property] = field(default_factory=list)
    opaque: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.limit is None:
            self.limit = len(self.data)

    def take(self, count: int) -> bytes:
        if count < 0 or self.pos + count > self.limit:
            raise SaveError(f'Leitura fora dos limites em 0x{self.pos:X} ({count} bytes).')
        out = self.data[self.pos:self.pos + count]
        self.pos += count
        return out

    def number(self, fmt: str) -> int | float:
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))[0]

    def u32(self) -> int:
        return int(self.number('I'))

    def count(self) -> int:
        n = int(self.number('i'))
        if not 0 <= n <= MAX_ENTRIES:
            raise SaveError(f'Contagem fora do limite do leitor: {n}.')
        return n

    def string(self) -> str:
        n = int(self.number('i'))
        if n == 0:
            return ''
        size = n if n > 0 else -2 * n
        if size > MAX_STRING:
            raise SaveError(f'String maior que o limite do leitor: {size} bytes.')
        raw = self.take(size)
        unit = 1 if n > 0 else 2
        if raw[-unit:] != b'\0' * unit:
            raise SaveError('String serializada sem terminador nulo.')
        try:
            text = raw[:-unit].decode('utf-8' if n > 0 else 'utf-16-le')
        except UnicodeError as exc:
            raise SaveError('Codificação da string não suportada.') from exc
        if '\0' in text:
            raise SaveError('String com terminador interno inesperado.')
        return text

    def type_node(self, depth: int = 0) -> TypeNode:
        if depth > MAX_DEPTH:
            raise SaveError('Profundidade de tipo excedida.')
        name = self.string()
        count = self.u32()
        if count > 16:
            raise SaveError('Quantidade inesperada de parâmetros de tipo.')
        return TypeNode(name, tuple(self.type_node(depth + 1) for _ in range(count)))

    def props(self, parent: str = '', depth: int = 0) -> dict[str, Any]:
        if depth > MAX_DEPTH:
            raise SaveError('Profundidade de propriedades excedida.')
        values: dict[str, Any] = {}
        while True:
            start = self.pos
            name = self.string()
            if name == 'None':
                return values
            if not name or '/' in name:
                raise SaveError('Nome de propriedade não suportado.')
            node = self.type_node()
            size = self.u32()
            flags = int(self.number('B'))
            if flags & ~0x1F or flags & 0x04:
                raise Unsupported(f'Flags/extensões de propriedade não suportadas: 0x{flags:X}.')
            index = self.u32() if flags & 0x01 else 0
            if flags & 0x02:
                self.take(16)
            key = name if index == 0 else f'{name}[{index}]'
            if key in values:
                raise SaveError(f'Propriedade duplicada/ambígua: {parent}/{key}.')
            path = parent + '/' + key
            payload_start = self.pos
            end = payload_start + size
            if end > self.limit:
                raise SaveError(f'Tamanho de propriedade excede o contêiner: {path}.')
            previous_limit = self.limit
            self.limit = end
            if len(self.properties) > MAX_ENTRIES:
                raise SaveError('Quantidade de propriedades excedida.')
            try:
                value = self.value(node, path, flags, depth + 1, tagged=True)
                if self.pos != end:
                    raise SaveError(f'Propriedade não consumida exatamente: {path} ({self.pos} != {end}).')
            finally:
                self.limit = previous_limit
            prop = Property(path, name, node, flags, index, start, payload_start, end, value)
            self.properties.append(prop)
            values[key] = value

    def opaque_value(self, path: str, reason: str) -> dict:
        start = self.pos
        raw = self.take(self.limit - self.pos)
        self.opaque.append({'path': path, 'offset': start, 'size': len(raw), 'reason': reason})
        return {'_unparsed_hex': raw.hex()}

    def value(self, node: TypeNode, path: str, flags: int, depth: int, *, tagged: bool = False) -> Any:
        if depth > MAX_DEPTH:
            raise SaveError('Profundidade de valor excedida.')
        kind = node.name
        numbers = {
            'IntProperty': 'i', 'Int8Property': 'b', 'Int16Property': 'h', 'Int64Property': 'q',
            'UInt8Property': 'B', 'UInt16Property': 'H', 'UInt32Property': 'I', 'UInt64Property': 'Q',
            'FloatProperty': 'f', 'DoubleProperty': 'd',
        }
        if kind in numbers:
            return self.number(numbers[kind])
        if kind == 'BoolProperty':
            if tagged:
                if self.pos != self.limit:
                    raise SaveError('BoolProperty tipada com payload inesperado.')
                return bool(flags & 0x10)
            byte = int(self.number('B'))
            if byte not in (0, 1):
                raise SaveError('Booleano inválido.')
            return bool(byte)
        if kind in ('StrProperty', 'NameProperty', 'ObjectProperty', 'ClassProperty', 'EnumProperty'):
            return self.string()
        if kind == 'ByteProperty':
            return self.string() if node.inner else self.number('B')
        if kind in ('SoftObjectProperty', 'SoftClassProperty'):
            return {'PackageName': self.string(), 'AssetName': self.string(), 'SubPath': self.string()}
        if kind == 'TextProperty' and tagged:
            return self.opaque_value(path, 'TextProperty preservada, sem interpretação/edição nesta versão.')
        if kind == 'StructProperty':
            if not node.inner:
                raise SaveError('Struct sem informação de tipo.')
            st = node.inner[0].name
            if flags & 0x08:
                if st == 'Guid':
                    return '-'.join(f'{self.u32():08X}' for _ in range(4))
                if st in ('DateTime', 'Timespan'):
                    return {'ticks': self.number('q')}
                if st == 'GameplayTagContainer':
                    return [self.string() for _ in range(self.count())]
                if tagged:
                    return self.opaque_value(path, f'Struct nativa {st} preservada sem interpretação.')
                raise Unsupported(f'Struct nativa não suportada no contêiner: {st}.')
            return self.props(path, depth + 1)
        if kind == 'ArrayProperty':
            if len(node.inner) != 1:
                raise SaveError('Array sem um único tipo de elemento.')
            count = self.count()
            return [self.value(node.inner[0], f'{path}/{i}', flags & 8, depth + 1) for i in range(count)]
        if kind == 'MapProperty':
            if len(node.inner) != 2:
                raise SaveError('Map sem tipos de chave e valor.')
            removed = [self.value(node.inner[0], f'{path}/removed/{i}', flags & 8, depth + 1)
                       for i in range(self.count())]
            entries = []
            for i in range(self.count()):
                k = self.value(node.inner[0], f'{path}/{i}/key', flags & 8, depth + 1)
                v = self.value(node.inner[1], f'{path}/{i}/value', flags & 8, depth + 1)
                entries.append({'key': k, 'value': v})
            return {'removed': removed, 'entries': entries}
        if kind == 'SetProperty':
            if len(node.inner) != 1:
                raise SaveError('Set sem tipo de elemento.')
            removed = [self.value(node.inner[0], f'{path}/removed/{i}', flags & 8, depth + 1)
                       for i in range(self.count())]
            entries = [self.value(node.inner[0], f'{path}/{i}', flags & 8, depth + 1)
                       for i in range(self.count())]
            return {'removed': removed, 'entries': entries}
        if tagged:
            return self.opaque_value(path, f'{kind} preservada sem interpretação.')
        raise Unsupported(f'Tipo de elemento não suportado: {kind}.')

@dataclass
class SaveDocument:
    raw: bytes
    header: dict
    values: dict
    properties: dict[str, Property]
    opaque: list[dict]
    root_start: int
    root_end: int

    @classmethod
    def from_bytes(cls, raw: bytes) -> 'SaveDocument':
        if not isinstance(raw, bytes) or not 32 <= len(raw) <= MAX_FILE:
            raise SaveError('Tamanho de arquivo fora do intervalo suportado.')
        r = Reader(raw)
        if r.take(4) != b'GVAS':
            raise SaveError('Não é um save GVAS. Selecione um .sav, não um .7z ou .json.')
        version, ue4, ue5 = r.u32(), r.u32(), r.u32()
        if version != 3:
            raise Unsupported(f'Versão GVAS não suportada: {version}.')
        engine = [int(r.number('H')) for _ in range(3)]
        build = r.u32()
        branch = r.string()
        if (ue4, ue5, *engine) != (522, 1017, 5, 6, 1):
            raise Unsupported('Cabeçalho diferente do perfil observado (GVAS3 / 522 / 1017 / UE5.6.1).')
        custom_format, count = r.u32(), r.count()
        if custom_format != 3:
            raise Unsupported('Formato de versões personalizadas não suportado.')
        r.take(count * 20)
        class_name = r.string()
        root_flag = r.number('B')
        if root_flag != 0:
            raise Unsupported('Extensão da raiz não suportada.')
        root_start = r.pos
        values = r.props()
        root_end = r.pos
        if r.take(r.limit - r.pos) != b'\0' * 4:
            raise Unsupported('Trailer diferente do observado; gravação recusada.')
        props = {p.path: p for p in r.properties}
        if len(props) != len(r.properties):
            raise SaveError('Caminhos de propriedades duplicados.')
        header = {'version': version, 'ue4': ue4, 'ue5': ue5, 'engine': engine,
                  'build': build, 'branch': branch, 'class': class_name,
                  'custom_version_count': count, 'properties_offset': root_start}
        return cls(raw, header, values, props, r.opaque, root_start, root_end)

    @classmethod
    def load(cls, path: str | Path) -> 'SaveDocument':
        p = Path(path)
        if not p.is_file() or p.stat().st_size > MAX_FILE:
            raise SaveError('Arquivo ausente ou maior que o limite suportado.')
        return cls.from_bytes(p.read_bytes())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()

    def rebuild(self, patches: dict[str, bytes] | None = None) -> bytes:
        """Reconstrói por segmentos preservados e payloads do mesmo tamanho.

        Esta API é de baixo nível; o serviço público permite SOMENTE moedas.
        A ausência de patches preserva tudo, inclusive textos não interpretados.
        """
        patches = patches or {}
        replacements = []
        for path, payload in patches.items():
            if path not in self.properties:
                raise SaveError(f'Propriedade não localizada: {path}.')
            p = self.properties[path]
            if p.type.name != 'IntProperty' or p.size != 4 or p.flags != 0:
                raise SaveError('Escrita de baixo nível limitada a IntProperty de 4 bytes, flags zero.')
            if type(payload) is not bytes or len(payload) != p.size:
                raise SaveError('Patch precisa manter o tamanho exato.')
            replacements.append((p.payload_start, p.end, payload))
        replacements.sort()
        # Particiona a raiz por tags já lidas. Sem reserializar strings desconhecidas.
        top = sorted((p for p in self.properties.values() if p.path.count('/') == 1), key=lambda p: p.start)
        parts = [self.raw[:self.root_start]]
        cursor = self.root_start
        for p in top:
            if p.start != cursor:
                raise SaveError('Partição da raiz inconsistente.')
            block_start = p.start
            for start, end, payload in replacements:
                if p.start <= start < p.end:
                    if start < block_start or end > p.end:
                        raise SaveError('Patches sobrepostos ou fora de uma propriedade.')
                    parts.extend([self.raw[block_start:start], payload])
                    block_start = end
            parts.append(self.raw[block_start:p.end])
            cursor = p.end
        parts.append(self.raw[cursor:])
        result = b''.join(parts)
        if len(result) != len(self.raw):
            raise SaveError('A regravação alterou inesperadamente o tamanho.')
        return result
