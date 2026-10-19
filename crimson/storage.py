"""Checked direct application, independent backups and restore transactions.

The old save is never removed first. A sibling temporary file is flushed and
validated; only then os.replace installs it. All writes require a stable snapshot
and a process check. Checks reduce races but cannot stop a user from starting the
game at the last instant; keep the game closed until the completion message.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Callable
import uuid

from . import __version__
from .catalogue import Catalogue
from .editing import EditBuffer, require_profile
from .gvas import MAX_FILE, SaveDocument, SaveError
from .service import Session, _snapshot, digest, json_bytes

CANONICAL = re.compile(r'Player_Character_\d+\.sav', re.IGNORECASE)
MAX_MANIFEST = 4 * 1024 * 1024


def user_data_dir() -> Path:
    if os.name == 'nt':
        root = os.environ.get('LOCALAPPDATA')
        if not root:
            raise SaveError('LOCALAPPDATA não foi localizada; selecione uma pasta de dados válida.')
        return Path(root)/'CrimsonMoonSaveEditor'
    return Path.home()/'.local'/'share'/'CrimsonMoonSaveEditor'


def folder_key(folder: Path) -> str:
    return hashlib.sha256(os.path.normcase(str(folder.resolve())).encode('utf-8')).hexdigest()[:32]


def no_links(path: Path) -> None:
    """Reject symlinks/junctions/reparse paths, including existing ancestors."""
    path = Path(os.path.abspath(path))
    for part in [path, *path.parents]:
        try:
            st = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode) or getattr(st, 'st_file_attributes', 0) & 0x400:
            raise SaveError('Links simbólicos/junções não são aceitos na aplicação automática.')


def parse_tasklist(output: str) -> list[str]:
    rows = list(csv.reader(io.StringIO(output)))
    names = [r[0].strip() for r in rows if len(r) >= 2 and r[1].strip().isdigit()]
    if not names:
        raise SaveError('Não foi possível interpretar a lista de processos. Aplicação bloqueada.')
    return names


def game_processes(names: list[str]) -> list[str]:
    found = []
    for name in names:
        name_only = name.replace('\\', '/').rsplit('/', 1)[-1]
        n = name_only.casefold()
        game_stems = ('crimsonmoonng', 'crimsonmoon', 'crimsonmoonngsteam')
        if any(n in (stem, stem+'.exe') or n.startswith(stem+'-') for stem in game_stems):
            found.append(name_only)
    return sorted(set(found))


def assert_game_closed() -> None:
    if os.name == 'nt':
        system = os.environ.get('SystemRoot', r'C:\Windows')
        command = [str(Path(system)/'System32'/'tasklist.exe'), '/FO', 'CSV', '/NH']
        try:
            proc = subprocess.run(command, capture_output=True, timeout=8, check=True,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.SubprocessError) as exc:
            raise SaveError('Falha ao verificar os processos do Windows. Nenhum save foi aplicado.') from exc
        names = parse_tasklist(proc.stdout.decode('utf-8', errors='replace'))
    elif sys.platform.startswith('linux'):
        try:
            proc = subprocess.run(['/bin/ps', '-eo', 'comm='], capture_output=True, text=True,
                                  timeout=5, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SaveError('Não foi possível verificar os processos. Aplicação bloqueada.') from exc
        names = [x.strip() for x in proc.stdout.splitlines() if x.strip()]
        if not names:
            raise SaveError('Lista de processos vazia; aplicação bloqueada.')
    else:
        raise SaveError('Aplicação automática não implementada neste sistema operacional.')
    running = game_processes(names)
    if running:
        raise SaveError('Feche completamente o Crimson Moon antes de aplicar/restaurar: ' + ', '.join(running))


def find_saves(root: Path | None = None) -> list[Path]:
    """Search only the expected game save root (max depth 3), never a whole drive."""
    if root is None:
        local = os.environ.get('LOCALAPPDATA')
        if not local:
            return []
        root = Path(local)/'CrimsonMoonNG'/'Saved'/'SaveGames'
    root = Path(root)
    if not root.is_dir():
        return []
    no_links(root)
    result: list[Path] = []
    stack = [(root, 0)]
    scanned = 0
    while stack and scanned < 500:
        folder, depth = stack.pop()
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        scanned += 1
        for p in entries:
            try:
                no_links(p)
                if p.is_file() and CANONICAL.fullmatch(p.name) and p.stat().st_size <= MAX_FILE:
                    result.append(p.resolve())
                elif p.is_dir() and depth < 3 and not any(x in p.name.casefold() for x in ('backup', 'cm_teste', 'editor')):
                    stack.append((p, depth+1))
            except (SaveError, OSError):
                continue
    return sorted(set(result), key=lambda p: str(p).casefold())


def _put_new(path: Path, raw: bytes) -> None:
    with path.open('xb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    if path.read_bytes() != raw:
        raise SaveError('Falha na conferência da cópia em disco: ' + path.name)


def _write_journal(path: Path, obj: dict) -> None:
    raw = json_bytes(obj)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        _put_new(tmp, raw)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _safe_snapshot(folder: Path) -> dict[str, bytes]:
    no_links(folder)
    for p in folder.iterdir():
        if p.suffix.lower() == '.sav':
            no_links(p)
    return _snapshot(folder)


@contextmanager
def folder_lock(base: Path, key: str):
    """OS lock is released by the OS on exit/crash; no stale lock deletion needed."""
    locks = base/'locks'
    no_links(locks)
    locks.mkdir(parents=True, exist_ok=True)
    lock = locks/(key + '.lock')
    no_links(lock)
    handle = lock.open('a+b')
    acquired = False
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            raise SaveError('Outra janela do editor está gravando nesta pasta. Aguarde e reabra o save.') from exc
        yield
    finally:
        if acquired:
            try:
                if os.name == 'nt':
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
        else:
            handle.close()


@dataclass
class EditorSession:
    original: Session
    edits: EditBuffer

    @classmethod
    def open(cls, source: str | Path, catalog: Catalogue) -> 'EditorSession':
        no_links(Path(source))
        old = Session.open(source)
        return cls(old, EditBuffer(old.document, catalog))

    @property
    def source(self) -> Path:
        return self.original.source


class TransactionStore:
    def __init__(self, base: str | Path | None = None, *, guard: Callable[[], None] | None = None):
        self.base = Path(base) if base is not None else user_data_dir()
        self.guard = guard if guard is not None else assert_game_closed

    def history(self, source: str | Path) -> list[dict]:
        src = Path(source).resolve()
        root = self.base/'backups'/folder_key(src.parent)
        no_links(root)
        if not root.is_dir():
            return []
        result = []
        for path in sorted(root.glob('*/manifesto.json'), reverse=True):
            try:
                no_links(path)
                if path.stat().st_size > MAX_MANIFEST:
                    continue
                data = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(data,dict) or not isinstance(data.get('source'),dict):continue
                if data.get('schema') != 2 or data['source'].get('filename') != src.name:
                    continue
                if not isinstance(data.get('created_utc'),str) or not isinstance(data['source'].get('sha256'),str):continue
                if not isinstance(data.get('output',{}),dict) or not isinstance(data.get('audit',{}),dict):continue
                operations=data.get('audit',{}).get('operations',[])
                if not isinstance(operations,list) or not all(isinstance(op,dict) for op in operations):continue
                # Do not interpret a prepared journal as proof of application.
                result.append({'path': path.parent, 'created_utc': data['created_utc'],
                               'mode': data.get('mode'), 'status': data.get('status'),
                               'source_hash': data['source']['sha256'],
                               'output_hash': data.get('output', {}).get('sha256'),
                               'operations': data.get('audit', {}).get('operations', [])})
            except (OSError, ValueError, KeyError, SaveError):
                continue
        return result

    def apply(self, session: EditorSession) -> dict:
        if not session.edits.dirty:
            raise SaveError('Não há alterações pendentes.')
        if session.edits.original.raw != session.original.document.raw:
            raise SaveError('A edição não pertence ao save aberto.')
        audit = session.edits.audit()
        return self._commit(session.source, session.original.snapshot, session.edits.document.raw,
                            audit=audit, mode='apply')

    def _commit(self, source: Path, snapshot: dict[str, bytes], output: bytes,
                *, audit: dict, mode: str) -> dict:
        no_links(source)
        source = source.resolve(strict=True)
        if not CANONICAL.fullmatch(source.name):
            raise SaveError('Aplicação direta exige o nome original Player_Character_N.sav. '
                            'Abra o arquivo real da pasta de saves, não uma cópia renomeada do chat.')
        base = self.base.expanduser().absolute()
        no_links(base)
        base = base.resolve()
        if source.parent == base or source.parent in base.parents:
            raise SaveError('A pasta de backups deve ficar fora da pasta de saves do jogo.')
        if source.name not in snapshot:
            raise SaveError('O arquivo alvo não está no snapshot.')
        require_profile(SaveDocument.from_bytes(output))
        original = snapshot[source.name]
        if output == original:
            raise SaveError('Nenhuma alteração para aplicar.')
        self.guard()
        with folder_lock(base, folder_key(source.parent)):
            if _safe_snapshot(source.parent) != snapshot:
                raise SaveError('Os saves mudaram desde a abertura. Reabra o save atual; nada foi substituído.')
            need = sum(map(len, snapshot.values())) + len(output) + 1024*1024
            base.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(base).free < need or shutil.disk_usage(source.parent).free < len(output)+65536:
                raise SaveError('Espaço livre insuficiente para backup e arquivo temporário.')
            txid = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '_' + uuid.uuid4().hex[:8]
            dest = base/'backups'/folder_key(source.parent)/txid
            no_links(dest)
            dest.mkdir(parents=True, exist_ok=False)
            backups = dest/'originais'
            backups.mkdir()
            report = {
                'schema': 2, 'tool': 'Crimson Moon Save Editor', 'version': __version__,
                'created_utc': datetime.now(timezone.utc).isoformat(), 'transaction': txid,
                'mode': mode, 'status': 'preparing', 'game_build_version': None,
                'source': {'filename': source.name, 'folder': str(source.parent), 'sha256': digest(original), 'bytes': len(original)},
                'output': {'filename': source.name, 'sha256': digest(output), 'bytes': len(output)},
                'backups': [], 'audit': audit,
                'game_load_tested_for_this_output': False,
                'policy': 'Only the selected main character file is replaced. All .sav siblings are backed up. '
                          'Game .backup.sav files and Player.sav are not modified.',
            }
            temp: Path | None = None
            replaced = False
            try:
                for name, data in snapshot.items():
                    if Path(name).name != name or '/' in name or '\\' in name:
                        raise SaveError('Nome de snapshot inválido.')
                    _put_new(backups/name, data)
                    report['backups'].append({'filename': name, 'sha256': digest(data), 'bytes': len(data)})
                # Keep the exact proposed output for later game round-trip comparison.
                (dest/'proposto').mkdir()
                _put_new(dest/'proposto'/source.name, output)
                report['status'] = 'prepared'
                _write_journal(dest/'manifesto.json', report)
                fd, tmpname = tempfile.mkstemp(prefix='.' + source.name + '.cmeditor-', suffix='.tmp', dir=source.parent)
                temp = Path(tmpname)
                with os.fdopen(fd, 'wb') as f:
                    f.write(output)
                    f.flush()
                    os.fsync(f.fileno())
                if temp.read_bytes() != output or SaveDocument.load(temp).rebuild() != output:
                    raise SaveError('Verificação do arquivo temporário falhou.')
                if os.name != 'nt':
                    os.chmod(temp, stat.S_IMODE(source.stat().st_mode))
                self.guard()
                if _safe_snapshot(source.parent) != snapshot:
                    raise SaveError('A pasta mudou durante a preparação. A aplicação foi cancelada.')
                no_links(source)
                os.replace(temp, source)
                replaced = True
                temp = None
                # Never blindly overwrite unexpected new progress during recovery.
                if source.read_bytes() != output:
                    raise SaveError('O arquivo mudou ou não pôde ser confirmado após a aplicação. '
                                    'Não tente aplicar novamente sem reabrir. Backup: ' + str(dest))
                report['status'] = 'applied'
                report['verified_in_place'] = True
                current = _safe_snapshot(source.parent)
                expected = dict(snapshot)
                expected[source.name] = output
                if current != expected:
                    report['warning'] = 'Um arquivo vizinho mudou após a aplicação. Feche o jogo e confira a pasta.'
                try:
                    _write_journal(dest/'manifesto.json', report)
                except OSError as exc:
                    report['warning'] = ('Save aplicado e conferido, mas a atualização final do manifesto falhou. '
                                         'O manifesto preparado e os backups permanecem disponíveis. ' + str(exc))
                report['backup_directory'] = str(dest)
                return report
            except Exception as exc:
                report['status'] = 'uncertain_after_replace' if replaced else 'aborted_before_replace'
                report['error'] = str(exc)
                try:
                    _write_journal(dest/'manifesto.json', report)
                except OSError:
                    pass
                if replaced:
                    raise SaveError('Houve falha após a substituição; o arquivo pode já ter sido aplicado. '
                                    'O editor não sobrescreveu um possível progresso novo. Reabra e confira. '
                                    'Backup preservado em: ' + str(dest)) from exc
                raise
            finally:
                if temp is not None:
                    try:
                        temp.unlink()
                    except FileNotFoundError:
                        pass

    def restore(self, source: str | Path, transaction: str | Path, *, expected_current_hash: str) -> dict:
        no_links(Path(source))
        source = Path(source).resolve(strict=True)
        tx = Path(transaction)
        no_links(tx)
        tx = tx.resolve(strict=True)
        expected_parent = (self.base/'backups'/folder_key(source.parent)).resolve()
        if tx.parent != expected_parent:
            raise SaveError('Escolha um backup registrado para esta pasta de saves.')
        manifest = tx/'manifesto.json'
        no_links(manifest)
        if manifest.stat().st_size > MAX_MANIFEST:
            raise SaveError('Manifesto maior que o limite.')
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if not isinstance(data,dict) or not isinstance(data.get('source'),dict):
            raise SaveError('Estrutura de manifesto inválida.')
        if data.get('schema') != 2 or data['source'].get('filename') != source.name:
            raise SaveError('Backup não corresponde a este personagem.')
        if data['source'].get('folder') != str(source.parent):
            raise SaveError('Backup pertence a outra pasta; restauração automática recusada.')
        candidate = tx/'originais'/source.name
        no_links(candidate)
        if not candidate.is_file() or candidate.stat().st_size > MAX_FILE:
            raise SaveError('Arquivo de backup ausente ou inválido.')
        raw = candidate.read_bytes()
        if digest(raw) != data['source']['sha256']:
            raise SaveError('Hash do backup não corresponde ao manifesto. Restauração recusada.')
        require_profile(SaveDocument.from_bytes(raw))
        snapshot = _safe_snapshot(source.parent)
        if source.name not in snapshot or digest(snapshot[source.name]) != expected_current_hash:
            raise SaveError('O save atual mudou desde a confirmação de restauração. Reabra e tente de novo.')
        return self._commit(source, snapshot, raw, mode='restore', audit={
            'restore_transaction': tx.name,
            'operations': [{'kind': 'restore', 'label': 'Restaurar backup', 'before': expected_current_hash,
                            'after': digest(raw)}],
            'note': 'O estado anterior à restauração recebeu um novo backup; arquivos vizinhos não foram substituídos.'})

    def export(self, session: EditorSession, destination: str | Path) -> dict:
        """Optional offline copy. No installation, no game process manipulation."""
        session.original.assert_unchanged()
        dest = Path(destination).expanduser().absolute()
        no_links(dest)
        dest = dest.resolve()
        if dest == session.source.parent or session.source.parent in dest.parents:
            raise SaveError('Exporte a cópia fora da pasta original de saves.')
        if dest.exists() or not dest.parent.is_dir():
            raise SaveError('Escolha uma pasta de saída nova em um diretório existente.')
        raw = session.edits.document.raw
        if SaveDocument.from_bytes(raw).rebuild() != raw:
            raise SaveError('A cópia não passou na releitura.')
        dest.mkdir()
        (dest/'save_teste').mkdir()
        (dest/'backup_originais').mkdir()
        # A partially exported directory is left with an incomplete marker, not
        # passed off as complete and never installed automatically.
        _put_new(dest/'INCOMPLETO.txt', b'Exportacao incompleta ate a criacao de manifesto.json.\n')
        for name, original in session.original.snapshot.items():
            _put_new(dest/'backup_originais'/name, original)
        _put_new(dest/'save_teste'/session.source.name, raw)
        session.original.assert_unchanged()
        report = {'schema': 2, 'mode': 'export_copy', 'complete': True, 'version': __version__,
                  'source': {'filename': session.source.name, 'sha256': session.original.document.sha256},
                  'output': {'sha256': digest(raw), 'bytes': len(raw)}, 'audit': session.edits.audit(),
                  'game_load_tested_for_this_output': False}
        _put_new(dest/'manifesto.json', json_bytes(report))
        (dest/'INCOMPLETO.txt').unlink()
        return report
