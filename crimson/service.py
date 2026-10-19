"""Operações públicas: inspeção e exportação de cópias, nunca escrita in-place."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import struct
import uuid

from . import __version__
from .gvas import SaveDocument, SaveError, MAX_FILE

CURRENCIES = {'gold': 'IC_GoldCoins', 'souls': 'IC_Souls'}
LABELS = {'gold': 'Dinheiro', 'souls': 'Almas'}
# Limite deliberado do protótipo, NÃO um limite confirmado do jogo.
MAX_AMOUNT = 10_000_000
MAX_SNAPSHOT_BYTES = 128 * 1024 * 1024
MAX_SNAPSHOT_FILES = 200

def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')

def currency_field(doc: SaveDocument, currency: str) -> tuple[int, str]:
    if currency not in CURRENCIES:
        raise SaveError('Moeda desconhecida. Use gold ou souls.')
    if doc.header['class'] != '/Script/CrimsonMoonNG.SaveGameCharacter':
        raise SaveError('Selecione Player_Character_N.sav, não Player.sav ou configurações.')
    if type(doc.values.get('SavedDataVersion')) is not int or doc.values['SavedDataVersion'] != 8:
        raise SaveError('SavedDataVersion diferente de 8: perfil de edição não validado.')
    inventory = doc.values.get('SaveGameInventory')
    if not isinstance(inventory, dict) or not isinstance(inventory.get('BackpackContents'), list):
        raise SaveError('Mochila não localizada ou estrutura diferente da amostra.')
    asset = CURRENCIES[currency]
    package = '/Game/Data/Inventory/Currency/' + asset
    objpath = package + '.' + asset
    matches = []
    for i, entry in enumerate(inventory['BackpackContents']):
        if not isinstance(entry, dict):
            raise SaveError('Registro de inventário não reconhecido.')
        ap = entry.get('AssetPath', {})
        if not isinstance(ap, dict):
            raise SaveError('AssetPath não reconhecido na mochila.')
        is_candidate = ap.get('AssetName') == asset or entry.get('Item') == objpath
        if not is_candidate:
            continue
        if (ap.get('PackageName'), ap.get('AssetName'), entry.get('Item')) != (package, asset, objpath):
            raise SaveError(f'Referências inconsistentes para {asset}. Nada foi escrito.')
        path = f'/SaveGameInventory/BackpackContents/{i}/Count'
        p = doc.properties.get(path)
        value = entry.get('Count')
        if p is None or p.type.name != 'IntProperty' or p.flags != 0 or p.size != 4:
            raise SaveError(f'Count de {asset} não é IntProperty canônica de 4 bytes.')
        if type(value) is not int or not 0 <= value <= 2_147_483_647:
            raise SaveError(f'Quantidade inválida no registro de {asset}.')
        if p.value != value or struct.unpack('<i', doc.raw[p.payload_start:p.end])[0] != value:
            raise SaveError('Inconsistência entre valor, propriedade e bytes.')
        matches.append((value, path))
    if not matches:
        raise SaveError(f'{LABELS[currency]}: registro ausente. Esta versão não cria itens novos.')
    if len(matches) != 1:
        raise SaveError(f'{LABELS[currency]}: registros duplicados/ambíguos. Edição bloqueada.')
    return matches[0]

def currency_status(doc: SaveDocument) -> dict:
    out = {}
    for kind in CURRENCIES:
        try:
            value, path = currency_field(doc, kind)
            out[kind] = {'value': value, 'path': path, 'editable': True, 'reason': None}
        except SaveError as exc:
            out[kind] = {'value': None, 'path': None, 'editable': False, 'reason': str(exc)}
    return out

def semantic_diff(a: Any, b: Any, path: str = '') -> list[dict]:
    if type(a) is not type(b):
        return [{'path': path, 'before': a, 'after': b}]
    if isinstance(a, dict):
        out = []
        for k in sorted(a.keys() | b.keys()):
            if k not in a or k not in b:
                out.append({'path': f'{path}/{k}', 'before': a.get(k), 'after': b.get(k),
                            'missing_before': k not in a, 'missing_after': k not in b})
            else:
                out.extend(semantic_diff(a[k], b[k], f'{path}/{k}'))
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [{'path': path, 'before_length': len(a), 'after_length': len(b)}]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(semantic_diff(x, y, f'{path}/{i}'))
        return out
    return [] if a == b else [{'path': path, 'before': a, 'after': b}]

def write_currency(doc: SaveDocument, kind: str, amount: int) -> tuple[bytes, dict]:
    if type(amount) is not int or not 0 <= amount <= MAX_AMOUNT:
        raise SaveError(f'O protótipo aceita inteiros de 0 a {MAX_AMOUNT:,}; não é um limite oficial do jogo.')
    old, path = currency_field(doc, kind)
    p = doc.properties[path]
    result = doc.rebuild({path: struct.pack('<i', amount)})
    reopened = SaveDocument.from_bytes(result)
    actual, reopened_path = currency_field(reopened, kind)
    changes = semantic_diff(doc.values, reopened.values)
    expected = [] if old == amount else [{'path': path, 'before': old, 'after': amount}]
    if actual != amount or reopened_path != path or changes != expected:
        raise SaveError('A releitura encontrou alterações além da moeda solicitada.')
    changed_offsets = [i for i, (x, y) in enumerate(zip(doc.raw, result)) if x != y]
    if any(not p.payload_start <= offset < p.end for offset in changed_offsets):
        raise SaveError('Mudança fora dos 4 bytes autorizados.')
    reversed_bytes = reopened.rebuild({path: struct.pack('<i', old)})
    if reversed_bytes != doc.raw:
        raise SaveError('A reversão não recuperou exatamente os bytes de entrada.')
    return result, {'currency': kind, 'label': LABELS[kind], 'before': old, 'after': amount,
                    'property_path': path, 'payload_offset': p.payload_start, 'payload_size': 4,
                    'changed_offsets': changed_offsets, 'semantic_changes': changes,
                    'reverse_matches_input': True}

def _snapshot(folder: Path) -> dict[str, bytes]:
    files = sorted(folder.glob('*.sav'))
    if len(files) > MAX_SNAPSHOT_FILES:
        raise SaveError('Mais de 200 saves na pasta. Use uma cópia isolada para o teste.')
    total = 0
    output = {}
    for p in files:
        if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_FILE:
            raise SaveError(f'Snapshot recusado para {p.name}.')
        raw = p.read_bytes()
        total += len(raw)
        if total > MAX_SNAPSHOT_BYTES or len(raw) > MAX_FILE:
            raise SaveError('Snapshot excede os limites do protótipo.')
        output[p.name] = raw
    return output

@dataclass
class Session:
    source: Path
    document: SaveDocument
    snapshot: dict[str, bytes]

    @classmethod
    def open(cls, source: str | Path) -> 'Session':
        p = Path(source)
        if p.is_symlink():
            raise SaveError('Não abra links simbólicos para saves.')
        p = p.resolve(strict=True)
        if p.suffix.lower() != '.sav' or '.backup.' in p.name.lower():
            raise SaveError('Abra o .sav principal, não o .backup.sav nem arquivos compactados.')
        snap = _snapshot(p.parent)
        if p.name not in snap:
            raise SaveError('Arquivo não incluído no snapshot da pasta.')
        doc = SaveDocument.from_bytes(snap[p.name])
        if doc.header['class'] != '/Script/CrimsonMoonNG.SaveGameCharacter':
            raise SaveError('Este painel edita somente saves de personagem Player_Character_N.sav.')
        if type(doc.values.get('SavedDataVersion')) is not int or doc.values['SavedDataVersion'] != 8:
            raise SaveError('SavedDataVersion diferente do perfil observado (8).')
        session = cls(p, doc, snap)
        session.assert_unchanged()
        return session

    def assert_unchanged(self) -> None:
        current = _snapshot(self.source.parent)
        if current != self.snapshot:
            raise SaveError('Um save foi alterado/adicionado/removido desde a abertura. Feche o jogo e reabra o arquivo.')

    def info(self) -> dict:
        v = self.document.values
        return {'filename': self.source.name, 'sha256': self.document.sha256,
                'bytes': len(self.document.raw), 'header': self.document.header,
                'character_name': v.get('CharacterName'), 'currencies': currency_status(self.document),
                'xp_read_only': v.get('PlayerLevel_XPCurrency'),
                'attributes_read_only': v.get('NephilimAttributes'),
                'inventory_read_only': v.get('SaveGameInventory', {}).get('BackpackContents', []),
                'effects_read_only': v.get('PlayerGameplayEffects', []),
                'opaque_preserved': self.document.opaque,
                'snapshot_files': [{'filename': n, 'bytes': len(b), 'sha256': digest(b)}
                                   for n, b in self.snapshot.items()]}

    def export(self, destination: str | Path, *, currency: str | None = None,
               amount: int | None = None) -> dict:
        """Cria um pacote novo de teste. Nunca substitui arquivos da pasta de origem."""
        if (currency is None) != (amount is None):
            raise SaveError('Informe moeda e valor juntos ou nenhum deles para o controle.')
        self.assert_unchanged()
        destination = Path(destination).expanduser().resolve()
        if destination == self.source.parent or self.source.parent in destination.parents:
            raise SaveError('Escolha uma saída fora da pasta original de saves.')
        if destination.exists():
            raise SaveError('A pasta de saída já existe. Use uma pasta nova; nada será sobrescrito.')
        if not destination.parent.is_dir():
            raise SaveError('A pasta pai da saída precisa existir.')
        if currency is None:
            data = self.document.rebuild()
            reread = SaveDocument.from_bytes(data)
            if data != self.document.raw or reread.values != self.document.values:
                raise SaveError('Controle sem alterações não passou na verificação.')
            change = None
            mode = 'control_no_changes'
        else:
            data, change = write_currency(self.document, currency, amount)
            mode = 'one_currency_only'
        report = {
            'tool': 'Crimson Moon Save Lab', 'version': __version__,
            'created_utc': datetime.now(timezone.utc).isoformat(), 'complete': True,
            'mode': mode, 'game_load_tested': False, 'game_build_version': None,
            'source': {'filename': self.source.name, 'sha256': self.document.sha256, 'bytes': len(self.document.raw)},
            'output': {'relative_path': 'save_teste/' + self.source.name, 'sha256': digest(data), 'bytes': len(data)},
            'change': change, 'same_length': len(data) == len(self.document.raw),
            'opaque_fields_preserved': self.document.opaque,
            'backups': [{'relative_path': 'backup_originais/' + n, 'sha256': digest(b), 'bytes': len(b)}
                        for n, b in self.snapshot.items()],
            'note': 'Backups são os bytes de entrada, nunca as versões modificadas. O arquivo .backup.sav do jogo não é editado.'}
        # mkdir exclusivo é a reserva da saída; nenhum arquivo existente é substituído.
        destination.mkdir(exist_ok=False)
        created: list[Path] = []
        dirs: list[Path] = []
        def put(path: Path, raw: bytes) -> None:
            with path.open('xb') as fh:
                created.append(path)
                fh.write(raw)
                fh.flush()
                os.fsync(fh.fileno())
            if path.read_bytes() != raw:
                raise SaveError(f'Falha ao verificar os bytes gravados: {path.name}.')
        try:
            for name in ['backup_originais', 'save_teste']:
                d = destination / name
                d.mkdir()
                dirs.append(d)
            for name, raw in self.snapshot.items():
                put(destination / 'backup_originais' / name, raw)
            target = destination / 'save_teste' / self.source.name
            put(target, data)
            if SaveDocument.load(target).rebuild() != data:
                raise SaveError('A releitura do arquivo em disco falhou.')
            put(destination / 'LEIA_ANTES_DO_TESTE.txt', (
                'PACOTE PRIVADO DE TESTE - NAO PUBLICAR SEUS SAVES\n\n'
                'save_teste: somente o arquivo de personagem a testar.\n'
                'backup_originais: copias EXATAS dos .sav encontrados na pasta de origem.\n'
                'NUNCA copie a pasta inteira deste pacote para dentro da pasta do jogo.\n'
                'O programa nao instalou nada e nao alterou nenhum arquivo original.\n'
                'Feche o jogo. Preserve uma copia externa completa de seus saves atuais.\n'
                'Leia docs/TESTE_NO_JOGO.md do programa antes de substituir qualquer arquivo.\n'
                'O arquivo so e considerado exportado quando manifesto.json existe e complete=true.\n'
                'Se o jogo retornar ao valor anterior ou acusar erro, interrompa o teste.\n'
                'Nao sobrescreva .backup.sav para tentar forcar o resultado.\n'
            ).encode('utf-8'))
            self.assert_unchanged()
            put(destination / 'manifesto.json', json_bytes(report))
        except Exception:
            # Remove SOMENTE os arquivos criados por esta chamada, nunca arquivos de usuário.
            for path in reversed(created):
                try: path.unlink()
                except OSError: pass
            for path in reversed(dirs):
                try: path.rmdir()
                except OSError: pass
            try: destination.rmdir()
            except OSError: pass
            raise
        return report

def new_export_name() -> str:
    return 'CM_teste_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
