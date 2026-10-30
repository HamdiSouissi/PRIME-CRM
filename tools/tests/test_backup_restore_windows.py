import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import backup_restore_windows as backup

DIRECT = (
    "postgresql://user:p%40ss%3Aword@ep-example.c-1.eu-central-1.aws.neon.tech/"
    "neondb?sslmode=require&channel_binding=require"
)


class NeonUrlTests(unittest.TestCase):
    def test_direct_url_decodes_credentials_and_requires_tls_channel_binding(self):
        source = backup.parse_neon_url(DIRECT)
        self.assertEqual(source.password, "p@ss:word")
        self.assertEqual(source.host, "ep-example.c-1.eu-central-1.aws.neon.tech")
        self.assertEqual(source.channel_binding, "require")
        self.assertNotIn("p@ss", repr(source))

    def test_rejects_pooler_other_hosts_databases_and_unsafe_options(self):
        invalid = [
            DIRECT.replace("ep-example.", "ep-example-pooler."),
            DIRECT.replace("aws.neon.tech", "aws.neon.tech.attacker.test"),
            DIRECT.replace("aws.neon.tech", "aws.neon.test"),
            DIRECT.replace("/neondb?", "/other?"),
            DIRECT.replace("sslmode=require", "sslmode=disable"),
            DIRECT + "&host=127.0.0.1",
            DIRECT + "&sslmode=require",
            DIRECT.replace(".aws.neon.tech/", ".aws.neon.tech:1234/"),
            DIRECT.replace("p%40ss%3Aword", ""),
            DIRECT + "#fragment",
            DIRECT + "\nextra",
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(backup.SafeFailure) as failure:
                backup.parse_neon_url(value)
            self.assertNotIn("p%40ss", str(failure.exception))

    def test_inherited_pg_settings_cannot_override_neon_or_local_target(self):
        inherited = {"PGHOST": "danger.example", "PGSERVICE": "prod", "PGHOSTADDR": "1.2.3.4"}
        with mock.patch.dict(os.environ, inherited):
            source = backup.source_environment(backup.parse_neon_url(DIRECT), Path("ca.pem"))
            local = backup.local_environment(54321, "random-local-password", backup.LOCAL_DATABASE)
        self.assertEqual(source["PGHOST"], "ep-example.c-1.eu-central-1.aws.neon.tech")
        self.assertEqual(source["PGSSLMODE"], "verify-full")
        self.assertEqual(source["PGGSSENCMODE"], "disable")
        self.assertEqual(source["PGOPTIONS"], "-c default_transaction_read_only=on")
        self.assertEqual(source["PGCHANNELBINDING"], "require")
        self.assertEqual(local["PGHOST"], "127.0.0.1")
        self.assertEqual(local["PGDATABASE"], backup.LOCAL_DATABASE)
        self.assertNotIn("PGSERVICE", source)
        self.assertNotIn("PGHOSTADDR", local)

    def test_local_database_is_never_selected_from_an_arbitrary_string(self):
        for database in ("neondb", "other", "postgresql://server/db"):
            with self.subTest(database=database), self.assertRaises(backup.SafeFailure):
                backup.local_environment(54321, "fake", database)


class CommandAndArchiveTests(unittest.TestCase):
    def test_subprocess_error_never_echoes_sensitive_output(self):
        fake = subprocess.CompletedProcess(["fake"], 1, "", "permission denied: customer@email.test SECRET")
        with mock.patch.object(backup.subprocess, "run", return_value=fake), self.assertRaises(backup.SafeFailure) as failure:
            backup.command(["fake"], label="Test")
        self.assertEqual(str(failure.exception), "Test : échec [PERMISSION].")
        self.assertNotIn("SECRET", str(failure.exception))
        self.assertNotIn("customer", str(failure.exception))

    def test_archive_created_in_new_folder_without_touching_previous_backups(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            previous = root / "ancienne.dump"
            previous.write_bytes(b"ancienne")

            def fake_command(args, **kwargs):
                self.assertEqual(args[:4], ["pg_dump", "--no-password", "--format=custom", "--compress=6"])
                path = Path(args[args.index("--file") + 1])
                path.write_bytes(b"archive fictive")
                return subprocess.CompletedProcess(args, 0, "", "")

            with mock.patch.object(backup, "command", side_effect=fake_command):
                archive, digest = backup.make_archive({"pg_dump": "pg_dump"}, {}, root)
            self.assertEqual(previous.read_bytes(), b"ancienne")
            self.assertNotEqual(archive.parent, root)
            self.assertEqual(digest, hashlib.sha256(b"archive fictive").hexdigest())

    def test_failed_backup_removes_only_new_partial_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            previous = root / "ancienne.dump"
            previous.write_bytes(b"ancienne")
            with mock.patch.object(backup, "command", side_effect=backup.SafeFailure("erreur")), self.assertRaises(backup.SafeFailure):
                backup.make_archive({"pg_dump": "pg_dump"}, {}, root)
            self.assertEqual([item.name for item in root.iterdir()], ["ancienne.dump"])
            self.assertEqual(previous.read_bytes(), b"ancienne")

    def test_cleanup_leaves_directory_when_server_status_is_uncertain(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "runtime"
            (root / "data").mkdir(parents=True)
            processes = [
                subprocess.CompletedProcess([], 1, "", ""),
                subprocess.CompletedProcess([], 4, "", ""),
            ]
            with mock.patch.object(backup, "command", side_effect=processes):
                self.assertFalse(backup.cleanup_local({"pg_ctl": "pg_ctl"}, root, True))
            self.assertTrue(root.exists())

    def test_cleanup_deletes_private_runtime_only_after_stopped_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "runtime"
            (root / "data").mkdir(parents=True)
            sibling = Path(folder) / "autre"
            sibling.write_bytes(b"keep")
            processes = [
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 3, "", ""),
            ]
            with mock.patch.object(backup, "command", side_effect=processes):
                self.assertTrue(backup.cleanup_local({"pg_ctl": "pg_ctl"}, root, True))
            self.assertFalse(root.exists())
            self.assertEqual(sibling.read_bytes(), b"keep")

    def test_mismatched_data_directory_prevents_any_restore(self):
        tools = {name: name for name in ("initdb", "pg_ctl", "psql", "createdb", "pg_restore")}
        invocations = []

        def fake_command(args, **kwargs):
            invocations.append(args)
            status = 3 if "status" in args else 0
            return subprocess.CompletedProcess(args, status, "", "")

        with tempfile.TemporaryDirectory() as folder:
            with (
                mock.patch.object(backup, "command", side_effect=fake_command),
                mock.patch.object(backup, "local_data_directory", return_value="/definitely/not/the/temp/folder"),
                self.assertRaises(backup.SafeFailure),
            ):
                backup.restore_archive(tools, Path(folder) / "fictive.dump", Path(folder))
            self.assertFalse(any(args[0] in ("pg_restore", "createdb") for args in invocations))
            self.assertEqual(list(Path(folder).iterdir()), [])


class CertificateAndSourceTests(unittest.TestCase):
    def test_windows_certificate_store_only_exports_trusted_server_roots(self):
        records = [
            (b"\x00", "x509_asn", True),
            (b"\x01", "x509_asn", {backup.SERVER_AUTH_OID}),
            (b"\x02", "x509_asn", {"1.2.3"}),
            (b"\x03", "x509_asn", False),
            (b"\x04", "pkcs_7_asn", True),
        ]
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(
            backup.ssl, "enum_certificates", return_value=records, create=True
        ), mock.patch.object(backup.ssl, "DER_cert_to_PEM_cert", side_effect=lambda value: value.hex()):
            target = Path(folder) / "ca.pem"
            backup.write_windows_root_certificates(target)
            self.assertEqual(target.read_text(encoding="ascii"), "00\n01")

    def test_source_version_must_be_postgresql_16(self):
        for output in ("other|160015\n", "neondb|170000\n", "invalid\n"):
            fake = subprocess.CompletedProcess([], 0, output, "")
            with self.subTest(output=output), mock.patch.object(backup, "command", return_value=fake), self.assertRaises(backup.SafeFailure):
                backup.source_check({"psql": "psql"}, {})
        fake = subprocess.CompletedProcess([], 0, "neondb|160015\n", "")
        with mock.patch.object(backup, "command", return_value=fake):
            backup.source_check({"psql": "psql"}, {})


@unittest.skipUnless(os.environ.get("PRIMECRM_TEST_PG_BIN"), "PostgreSQL 16 test binaries not provided")
class RealPostgreSQLTests(unittest.TestCase):
    def test_fake_archive_is_restored_and_temporary_server_removed(self):
        folder = Path(os.environ["PRIMECRM_TEST_PG_BIN"])
        suffix = ".exe" if os.name == "nt" else ""
        tools = {name: str(folder / f"{name}{suffix}") for name in (
            "pg_dump", "pg_restore", "psql", "initdb", "pg_ctl", "createdb", "postgres"
        )}
        with tempfile.TemporaryDirectory(prefix="primecrm-fake-integration-") as tmp:
            root = Path(tmp)
            backup.secure_directory(root)
            data = root / "fake_source"
            port = backup.free_loopback_port()
            backup.command([
                tools["initdb"], "-D", str(data), "-U", backup.LOCAL_ROLE,
                "--auth=trust", "--no-locale", "--encoding=UTF8",
            ])
            try:
                backup.command([
                    tools["pg_ctl"], "-D", str(data), "-l", str(root / "server.log"),
                    "-o", f"-c listen_addresses=127.0.0.1 -c port={port}", "start", "-w",
                ])
                env = backup.local_environment(port, "dummy-only")
                sql = (
                    "CREATE TABLE public.alembic_version (version_num varchar(32)); "
                    "INSERT INTO public.alembic_version VALUES ('20261029_02'); "
                    "CREATE TABLE public.users (id integer, is_active boolean, is_superuser boolean); "
                    "INSERT INTO public.users VALUES (1, true, true); "
                )
                sql += " ".join(f"CREATE TABLE public.fake_{i}(id integer);" for i in range(12))
                backup.command([tools["psql"], "-X", "-v", "ON_ERROR_STOP=1", "-c", sql], env=env)
                env["PGOPTIONS"] = "-c default_transaction_read_only=on"
                archive = root / "fake.dump"
                backup.command([tools["pg_dump"], "--no-password", "-Fc", "-f", str(archive)], env=env)
                write = backup.command([
                    tools["psql"], "-X", "-c", "CREATE TABLE public.blocked(id integer)"
                ], env=env, allow_failure=True)
                self.assertNotEqual(write.returncode, 0)
            finally:
                backup.command([tools["pg_ctl"], "-D", str(data), "stop", "-m", "fast", "-w"], allow_failure=True)
            result = backup.restore_archive(tools, archive, root)
            self.assertEqual(result, backup.RestoreResult("20261029_02", 14, 1))
            self.assertEqual(list(root.glob("primecrm-restore-*")), [])


class ReminderTests(unittest.TestCase):
    def test_reminder_has_no_secret_does_not_overwrite_and_warns_weekly(self):
        script = backup.reminder_registration_script()
        self.assertIn("-Weekly -DaysOfWeek Monday", script)
        self.assertIn("-LogonType Interactive", script)
        self.assertIn("if ($null -ne $existing)", script)
        self.assertNotIn("-Force", script)
        self.assertNotIn("PGPASSWORD", script)
        self.assertNotIn("-Password", script)

    def test_reminder_failure_does_not_claim_success(self):
        fake = subprocess.CompletedProcess([], 1, "INSTALLE", "failed")
        with mock.patch.dict(os.environ, {"SystemRoot": "C:/Windows"}), mock.patch.object(
            backup, "command", return_value=fake
        ):
            self.assertEqual(backup.install_reminder(), "NON_INSTALLE")


if __name__ == "__main__":
    unittest.main()
