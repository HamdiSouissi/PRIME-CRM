"""Back up this CRM's Neon database and test the archive locally on Windows.

No cloud database is created or restored to.  PostgreSQL binaries must already
exist under PRIME-CRM-Outils/PostgreSQL-16/pgsql/bin in the Windows user profile.
The only cloud operation is a read-only PostgreSQL connection for pg_dump.
"""
from __future__ import annotations

import base64
import csv
import ctypes
import getpass
import hashlib
import io
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

EXPECTED_DATABASE = "neondb"
EXPECTED_REVISION = "20261029_02"
LOCAL_ROLE = "primecrm_restore"
LOCAL_DATABASE = "primecrm_restore_test"
TASK_NAME = "PRIME-CRM-Controle-Quotas-Hebdomadaire"
SERVER_AUTH_OID = "1.3.6.1.5.5.7.3.1"


class SafeFailure(Exception):
    """An error whose message is safe to display without subprocess output."""


@dataclass(frozen=True, repr=False)
class NeonSource:
    host: str
    user: str
    password: str = field(repr=False)
    database: str = EXPECTED_DATABASE
    channel_binding: str = "prefer"


@dataclass(frozen=True)
class RestoreResult:
    revision: str
    tables: int
    active_superusers: int


def parse_neon_url(text: str) -> NeonSource:
    """Accept only a direct AWS Neon URI for the known CRM database."""
    try:
        if not text or any(ch in text for ch in "\r\n\x00"):
            raise ValueError
        parsed = urlsplit(text.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("postgres", "postgresql") or parsed.fragment:
            raise ValueError
        if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.aws\.neon\.tech", host):
            raise ValueError
        if "-pooler." in host or parsed.port not in (None, 5432):
            raise ValueError
        if parsed.username is None or parsed.password is None:
            raise ValueError
        username = unquote(parsed.username, errors="strict")
        password = unquote(parsed.password, errors="strict")
        database = unquote(parsed.path.removeprefix("/"), errors="strict")
        if not username or not password or database != EXPECTED_DATABASE:
            raise ValueError
        if any(ch in username + password + database for ch in "\r\n\x00"):
            raise ValueError
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        options: dict[str, str] = {}
        for key, value in pairs:
            if key in options or key not in ("sslmode", "channel_binding"):
                raise ValueError
            options[key] = value
        if options.get("sslmode", "require") not in ("require", "verify-full"):
            raise ValueError
        binding = options.get("channel_binding", "prefer")
        if binding not in ("prefer", "require"):
            raise ValueError
        return NeonSource(host, username, password, database, binding)
    except (ValueError, UnicodeError):
        # Never echo the URI; it contains a password.
        raise SafeFailure(
            "URL Neon non reconnue : utilisez l'URL directe standard de la "
            "base neondb, sans pooler. Ne la partagez pas."
        ) from None


def clean_environment() -> dict[str, str]:
    # Prevent a previous PGHOST, PGSERVICE or PGOPTIONS from changing targets.
    return {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}


def source_environment(source: NeonSource, root_cert: Path) -> dict[str, str]:
    env = clean_environment()
    env.update({
        "PGHOST": source.host,
        "PGPORT": "5432",
        "PGDATABASE": source.database,
        "PGUSER": source.user,
        "PGPASSWORD": source.password,
        "PGSSLMODE": "verify-full",
        "PGSSLROOTCERT": str(root_cert),
        "PGGSSENCMODE": "disable",
        "PGCHANNELBINDING": source.channel_binding,
        "PGCONNECT_TIMEOUT": "30",
        "PGAPPNAME": "prime-crm-read-only-backup",
        "PGOPTIONS": "-c default_transaction_read_only=on",
        "PGCLIENTENCODING": "UTF8",
    })
    return env


def local_environment(port: int, password: str, database: str = "postgres") -> dict[str, str]:
    if not (1 <= port <= 65535) or database not in ("postgres", LOCAL_DATABASE):
        raise SafeFailure("Cible locale invalide ; restauration annulée.")
    env = clean_environment()
    env.update({
        "PGHOST": "127.0.0.1",
        "PGPORT": str(port),
        "PGDATABASE": database,
        "PGUSER": LOCAL_ROLE,
        "PGPASSWORD": password,
        "PGSSLMODE": "disable",  # loopback only, protected by a random SCRAM password
        "PGGSSENCMODE": "disable",
        "PGCONNECT_TIMEOUT": "5",
        "PGCLIENTENCODING": "UTF8",
    })
    return env


def failure_kind(output: str) -> str:
    """Classify diagnostics without revealing connection details or table data."""
    value = output.lower()
    if "password authentication failed" in value or "authentication failed" in value:
        return "AUTHENTIFICATION"
    if "certificate verify failed" in value or "certificate verify" in value:
        return "CERTIFICAT_TLS"
    if "could not translate host" in value or "name or service not known" in value:
        return "RESEAU_DNS"
    if "server version mismatch" in value or "aborting because of server version" in value:
        return "VERSION_POSTGRESQL"
    if "permission denied" in value:
        return "PERMISSION"
    return "DETAIL_NON_AFFICHE"


def command(args: list[str], *, env: dict[str, str] | None = None,
            timeout: int = 300, allow_failure: bool = False,
            label: str = "commande") -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args, env=clean_environment() if env is None else env,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        raise SafeFailure(f"{label} : délai dépassé.") from None
    except OSError:
        raise SafeFailure(f"{label} : exécutable inaccessible.") from None
    if result.returncode and not allow_failure:
        raise SafeFailure(f"{label} : échec [{failure_kind(result.stderr)}].")
    return result


def windows_system_executable(name: str) -> str:
    return str(Path(os.environ["SystemRoot"]) / "System32" / name)


def secure_directory(directory: Path) -> None:
    """Restrict a newly-created directory; never alter an existing user folder."""
    if os.name != "nt":  # also permits real PostgreSQL integration tests on Linux
        directory.chmod(0o700)
        return
    identity = command(
        [windows_system_executable("whoami.exe"), "/user", "/fo", "csv", "/nh"],
        label="Vérification du compte Windows",
    )
    try:
        rows = list(csv.reader(io.StringIO(identity.stdout)))
        sid = rows[0][1].strip()
        if not re.fullmatch(r"S-1-\d+(?:-\d+)+", sid):
            raise ValueError
    except (IndexError, ValueError, csv.Error):
        raise SafeFailure("Impossible de sécuriser les fichiers : SID Windows introuvable.") from None
    icacls = windows_system_executable("icacls.exe")
    # Grant first, then remove inherited ACEs, so the owner never loses access.
    command(
        [icacls, str(directory), "/grant:r", f"*{sid}:(OI)(CI)F",
         "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
        label="Protection des fichiers Windows",
    )
    command([icacls, str(directory), "/inheritance:r"], label="Protection des fichiers Windows")


def new_private_directory(parent: Path, prefix: str) -> Path:
    directory = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    try:
        secure_directory(directory)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)  # newly created and still empty
        raise
    return directory


def write_windows_root_certificates(target: Path) -> None:
    if not hasattr(ssl, "enum_certificates"):
        raise SafeFailure("Magasin de certificats Windows inaccessible.")
    certs: list[str] = []
    try:
        for der, encoding, trust in ssl.enum_certificates("ROOT"):
            server_trusted = trust is True or (
                isinstance(trust, (set, frozenset)) and SERVER_AUTH_OID in trust
            )
            if encoding == "x509_asn" and server_trusted:
                certs.append(ssl.DER_cert_to_PEM_cert(der))
        if not certs:
            raise ValueError
        target.write_text("\n".join(certs), encoding="ascii")
    except (OSError, ValueError, TypeError):
        raise SafeFailure("Impossible de préparer les autorités TLS Windows.") from None


def postgres_tools(profile: Path) -> dict[str, str]:
    folder = profile / "PRIME-CRM-Outils" / "PostgreSQL-16" / "pgsql" / "bin"
    names = ("pg_dump", "pg_restore", "psql", "initdb", "pg_ctl", "createdb", "postgres")
    suffix = ".exe" if os.name == "nt" else ""
    tools = {name: str(folder / f"{name}{suffix}") for name in names}
    if any(not Path(path).is_file() for path in tools.values()):
        raise SafeFailure("Les binaires PostgreSQL 16 complets sont introuvables dans PRIME-CRM-Outils.")
    for name in ("pg_dump", "pg_restore", "initdb", "pg_ctl", "psql", "createdb", "postgres"):
        version = command([tools[name], "--version"], label=f"Version {name}").stdout
        if not re.search(r"\b16\.\d+\b", version):
            raise SafeFailure(f"{name} n'est pas en version PostgreSQL 16.")
    return tools


def source_check(tools: dict[str, str], source_env: dict[str, str]) -> None:
    result = command([
        tools["psql"], "--no-password", "--no-psqlrc", "--tuples-only", "--no-align",
        "--command", "SELECT current_database() || '|' || current_setting('server_version_num')",
    ], env=source_env, label="Connexion Neon en lecture seule", timeout=60)
    value = result.stdout.strip().split("|")
    if len(value) != 2 or value[0] != EXPECTED_DATABASE or not value[1].isdigit():
        raise SafeFailure("Identité ou version Neon inattendue ; sauvegarde annulée.")
    if int(value[1]) // 10000 != 16:
        raise SafeFailure("Le serveur Neon n'est pas en PostgreSQL 16 ; sauvegarde annulée.")


def make_archive(tools: dict[str, str], source_env: dict[str, str], backup_root: Path) -> tuple[Path, str]:
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = new_private_directory(backup_root, f"neondb-{stamp}-")
    archive = destination / f"neondb-pg16-{stamp}.dump"
    try:
        command([
            tools["pg_dump"], "--no-password", "--format=custom", "--compress=6",
            "--file", str(archive),
        ], env=source_env, label="Sauvegarde Neon", timeout=1800)
        if not archive.is_file() or archive.stat().st_size == 0:
            raise SafeFailure("Sauvegarde vide ; archive non conservée.")
    except BaseException:
        # The directory was created by this invocation; never touch prior backups.
        # Interrupted pg_dump files must not be mistaken for completed archives.
        shutil.rmtree(destination, ignore_errors=True)
        raise
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return archive, digest.hexdigest()


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def local_data_directory(tools: dict[str, str], env: dict[str, str]) -> str:
    result = command([
        tools["psql"], "--no-password", "--no-psqlrc", "--tuples-only", "--no-align",
        "--command", "SHOW data_directory",
    ], env=env, label="Contrôle de la cible locale", timeout=30)
    return result.stdout.strip()


def same_directory(actual: str, expected: Path) -> bool:
    return bool(actual) and os.path.normcase(os.path.realpath(actual)) == os.path.normcase(os.path.realpath(expected))


def cleanup_local(tools: dict[str, str], runtime: Path, started: bool) -> bool:
    """Remove only our newly-created directory after confirming its server stopped."""
    data = runtime / "data"
    if started:
        try:
            command([tools["pg_ctl"], "--pgdata", str(data), "stop", "--mode=fast", "--wait", "--timeout=60"],
                    allow_failure=True, timeout=75)
            status = command([tools["pg_ctl"], "--pgdata", str(data), "status"],
                             allow_failure=True, timeout=15)
            if status.returncode != 3:
                return False
        except SafeFailure:
            return False
    try:
        shutil.rmtree(runtime)
        return True
    except OSError:
        return False


def restore_archive(tools: dict[str, str], archive: Path, temporary_parent: Path) -> RestoreResult:
    runtime = new_private_directory(temporary_parent, "primecrm-restore-")
    data = runtime / "data"
    password_file = runtime / "temporary-password.txt"
    password = secrets.token_urlsafe(32)
    port = free_loopback_port()
    started = False
    try:
        password_file.write_text(password + "\n", encoding="ascii")
        try:
            command([
                tools["initdb"], "--pgdata", str(data), "--username", LOCAL_ROLE,
                "--auth=scram-sha-256", "--pwfile", str(password_file),
                "--encoding=UTF8", "--no-locale",
            ], label="Initialisation locale", timeout=180)
        finally:
            password_file.unlink(missing_ok=True)
        # Mark started before invoking pg_ctl: it might time out after starting.
        started = True
        command([
            tools["pg_ctl"], "--pgdata", str(data), "--log", str(runtime / "postgres.log"),
            "--options", f"-c listen_addresses=127.0.0.1 -c port={port}",
            "start", "--wait", "--timeout=60",
        ], label="Démarrage PostgreSQL local", timeout=75)
        env = local_environment(port, password)
        if not same_directory(local_data_directory(tools, env), data):
            raise SafeFailure("La cible locale ne correspond pas au dossier jetable ; arrêt immédiat.")
        command([
            tools["createdb"], "--no-password", "--template=template0", LOCAL_DATABASE,
        ], env=env, label="Création de la base locale", timeout=60)
        env = local_environment(port, password, LOCAL_DATABASE)
        if not same_directory(local_data_directory(tools, env), data):
            raise SafeFailure("La cible de restauration n'est pas le serveur local jetable.")
        command([
            tools["pg_restore"], "--no-password", "--exit-on-error", "--single-transaction",
            "--no-owner", "--no-acl", "--no-tablespaces", "--dbname", LOCAL_DATABASE,
            str(archive),
        ], env=env, label="Restauration locale", timeout=1800)
        result = command([
            tools["psql"], "--no-password", "--no-psqlrc", "--tuples-only", "--no-align",
            "--command", (
                "SELECT (SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version) "
                "|| '|' || (SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE') "
                "|| '|' || (SELECT count(*) FROM public.users WHERE is_active IS TRUE AND is_superuser IS TRUE)"
            ),
        ], env=env, label="Vérification de la restauration", timeout=60)
        parts = result.stdout.strip().split("|")
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            raise SafeFailure("Résultat de vérification locale inattendu.")
        revision, table_count, active_count = parts[0], int(parts[1]), int(parts[2])
        if revision != EXPECTED_REVISION or table_count < 14 or active_count < 1:
            raise SafeFailure("Archive restaurée, mais révision, tables ou administrateur inattendus.")
        return RestoreResult(revision, table_count, active_count)
    finally:
        if not cleanup_local(tools, runtime, started):
            # Never delete the directory if the server's status is uncertain.
            print(f"NETTOYAGE_TEMPORAIRE=À VÉRIFIER : {runtime}")
            print("La copie locale peut encore exister ; ne la partagez pas.")
            raise SafeFailure("Le nettoyage de la base de test n'a pas été confirmé.") from None


def powershell_encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def reminder_registration_script() -> str:
    notification = """
Add-Type -AssemblyName System.Windows.Forms
$message = "Controlez les quotas PRIME-CRM : Netlify, Render, Neon et Upstash. Ouvrir les consoles ?"
$answer = [System.Windows.Forms.MessageBox]::Show($message, 'PRIME-CRM - controle hebdomadaire', 'YesNo', 'Information')
if ($answer -eq [System.Windows.Forms.DialogResult]::Yes) {
  Start-Process 'https://app.netlify.com/'
  Start-Process 'https://dashboard.render.com/billing'
  Start-Process 'https://console.neon.tech/'
  Start-Process 'https://console.upstash.com/'
}
"""
    encoded_notification = powershell_encoded(notification)
    # The task contains only static URLs and no credentials. Never replace an
    # existing task of the same name. It requires a logged-in Windows user.
    return f"""
$ErrorActionPreference = 'Stop'
$taskName = '{TASK_NAME}'
$existing = Get-ScheduledTask -TaskName $taskName -TaskPath '\\' -ErrorAction SilentlyContinue
if ($null -ne $existing) {{ Write-Output 'EXISTE'; exit 0 }}
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$exe = Join-Path $env:SystemRoot 'System32\\WindowsPowerShell\\v1.0\\powershell.exe'
$action = New-ScheduledTaskAction -Execute $exe -Argument '-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand {encoded_notification}'
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '09:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -TaskPath '\\' -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
Write-Output 'INSTALLE'
"""


def install_reminder() -> str:
    executable = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    try:
        result = command([
            str(executable), "-NoProfile", "-NonInteractive", "-EncodedCommand",
            powershell_encoded(reminder_registration_script()),
        ], allow_failure=True, timeout=60, label="Rappel Windows")
        state = result.stdout.strip()
        return state if result.returncode == 0 and state in ("INSTALLE", "EXISTE") else "NON_INSTALLE"
    except SafeFailure:
        return "NON_INSTALLE"


def ask_for_source() -> NeonSource:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            url = getpass.getpass("Collez l'URL Neon directe ici (elle ne s'affiche pas) : ")
    except (getpass.GetPassWarning, EOFError):
        raise SafeFailure("Saisie masquée indisponible : utilisez une fenêtre PowerShell normale.") from None
    try:
        return parse_neon_url(url)
    finally:
        del url


def main() -> int:
    if os.name != "nt":
        print("Cet outil doit être exécuté sur votre PC Windows.")
        return 1
    if ctypes.windll.shell32.IsUserAnAdmin():
        print("Ouvrez PowerShell normalement, sans 'Exécuter en tant qu'administrateur'.")
        return 1
    print("Sauvegarde Neon en lecture seule, puis restauration PostgreSQL locale jetable.")
    print("Un rappel Windows sans secret sera proposé chaque lundi à 09h si la session est ouverte.")
    print("Ne collez jamais votre URL Neon dans cette conversation.")
    print()
    reminder = install_reminder()
    print(f"RAPPEL_HEBDOMADAIRE={reminder}")
    if reminder == "EXISTE":
        print("Une tâche du même nom existe déjà ; elle n'a pas été modifiée.")
    elif reminder == "NON_INSTALLE":
        print("Rappel non installé ; prévoyez un rappel hebdomadaire dans votre calendrier.")
    root: Path | None = None
    archive: Path | None = None
    try:
        profile = Path(os.environ["USERPROFILE"])
        tools = postgres_tools(profile)
        root = new_private_directory(Path(tempfile.gettempdir()), "primecrm-tls-")
        ca_file = root / "windows-root-ca.pem"
        write_windows_root_certificates(ca_file)
        source = ask_for_source()
        env = source_environment(source, ca_file)
        del source
        source_check(tools, env)
        archive, digest = make_archive(tools, env, profile / "PRIME-CRM-Sauvegardes")
        env.pop("PGPASSWORD", None)
        print("SAUVEGARDE=OK")
        print(f"ARCHIVE={archive}")
        print(f"SHA256={digest}")
        print("Test de restauration locale en cours ; ne fermez pas cette fenêtre...")
        result = restore_archive(tools, archive, Path(tempfile.gettempdir()))
        print("RESTAURATION_LOCALE=OK")
        print(f"REVISION={result.revision}")
        print(f"TABLES_PUBLIQUES={result.tables}")
        print(f"ADMINISTRATEURS_ACTIFS={result.active_superusers}")
        print("NETTOYAGE_TEMPORAIRE=OK")
        print("Aucun fichier uploadé ni SECRET_KEY n'est inclus dans cette archive.")
        print("L'archive contient des données privées : ne la partagez pas et ne la commitez pas.")
        return 0
    except SafeFailure as error:
        print(f"ECHEC={error}")
        if archive is not None:
            print("La sauvegarde créée a été conservée, mais sa restauration n'est pas validée.")
        return 1
    except (OSError, KeyError):
        print("ECHEC=Accès local impossible ; vérifiez les droits et l'espace disque.")
        if archive is not None:
            print("La sauvegarde créée a été conservée, mais sa restauration n'est pas validée.")
        return 1
    except KeyboardInterrupt:
        print("ARRET=Interrompu ; vérifiez le message de nettoyage ci-dessus.")
        return 1
    finally:
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
