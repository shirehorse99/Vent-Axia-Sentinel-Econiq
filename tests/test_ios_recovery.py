"""Synthetic databases only; no phone, backup, credentials or network required."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'tools/recover_ios_credentials.py'
spec = importlib.util.spec_from_file_location('ios_recovery', MODULE)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'devices.db'
        self.key = '1234567890abcdef'  # Synthetic, never used for a connection.
        self.options = {'tcpTlsIdentity': '  saved identity  ', 'tcpTlsKey': self.key,
                        'pinCode': 1234, 'wifiPassword': 'synthetic-not-to-export'}
        self.make_database(self.options)

    def make_database(self, options):
        with contextlib.closing(sqlite3.connect(self.db)) as c, c:
            c.execute('CREATE TABLE IF NOT EXISTS devices (id TEXT, description TEXT, macAddress TEXT, key TEXT, options TEXT, modelName TEXT)')
            c.execute('DELETE FROM devices')
            c.execute('INSERT INTO devices VALUES (?, ?, ?, ?, ?, ?)',
                      ('TEST-UNIT', 'Synthetic unit', '00:00:00:00:00:00', 'not-tls-key', json.dumps(options), 'Econiq'))

    def test_identity_is_preserved_exactly_and_unrelated_secrets_excluded(self):
        value = r.recover(self.db, 'TEST-UNIT')
        self.assertEqual(value, {'device_id': 'TEST-UNIT', 'tls_identity': '  saved identity  ', 'tls_psk_hex': self.key})

    def test_source_database_unchanged_and_no_journal(self):
        before = self.db.read_bytes()
        r.recover(self.db, 'TEST-UNIT')
        self.assertEqual(before, self.db.read_bytes())
        self.assertFalse(Path(str(self.db) + '-journal').exists())
        self.assertFalse(Path(str(self.db) + '-wal').exists())

    def test_invalid_or_absent_key_is_not_guessed(self):
        for key in [None, '', '00' * 8, 'abc', '12 34', 1234]:
            with self.subTest(key=key):
                self.make_database(self.options | {'tcpTlsKey': key})
                with self.assertRaises(r.RecoveryError):
                    r.recover(self.db, 'TEST-UNIT')

    def test_missing_device_and_invalid_json_fail(self):
        with self.assertRaises(r.RecoveryError):
            r.recover(self.db, 'OTHER')
        with contextlib.closing(sqlite3.connect(self.db)) as c, c:
            c.execute("UPDATE devices SET options = 'bad json'")
        with self.assertRaises(r.RecoveryError):
            r.recover(self.db, 'TEST-UNIT')

    def test_private_output_no_overwrite_and_no_stdout_secret(self):
        output = self.root / 'private.json'
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = r.main(['--database', str(self.db), '--device-id', 'TEST-UNIT', '--output', str(output)])
        self.assertEqual(result, 0)
        self.assertNotIn(self.key, stdout.getvalue() + stderr.getvalue())
        self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
        before = output.read_bytes()
        with self.assertRaises(r.RecoveryError):
            r.save_credentials(output, {'changed': True})
        self.assertEqual(before, output.read_bytes())

    def test_symlink_output_is_not_followed(self):
        target = self.root / 'existing'
        target.write_text('unchanged')
        link = self.root / 'link'
        link.symlink_to(target)
        with self.assertRaises(r.RecoveryError):
            r.save_credentials(link, {})
        self.assertEqual(target.read_text(), 'unchanged')

    def make_backup(self, encrypted=False):
        backup = self.root / 'backup'
        backup.mkdir()
        (backup / 'Manifest.plist').write_bytes(plistlib.dumps({'IsEncrypted': encrypted}))
        file_id = 'a' * 40
        with contextlib.closing(sqlite3.connect(backup / 'Manifest.db')) as c, c:
            c.execute('CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT)')
            c.execute('INSERT INTO Files VALUES (?, ?, ?)', (file_id, 'AppDomain-uk.ventaxia.connect', 'Library/LocalDatabase/devices.db'))
        (backup / 'aa').mkdir()
        (backup / 'aa' / file_id).write_bytes(self.db.read_bytes())
        return backup

    def test_manifest_lookup_reads_sharded_database(self):
        backup = self.make_backup()
        manifest_before = (backup / 'Manifest.db').read_bytes()
        self.assertEqual(r.recover(r.find_database(backup), 'TEST-UNIT')['tls_psk_hex'], self.key)
        self.assertEqual(manifest_before, (backup / 'Manifest.db').read_bytes())

    def test_encrypted_backup_stops_without_password_request(self):
        backup = self.make_backup(encrypted=True)
        with self.assertRaisesRegex(r.RecoveryError, 'Encrypted backups are unsupported'):
            r.find_database(backup)

    def test_ambiguous_backup_is_not_arbitrarily_selected(self):
        backup = self.make_backup()
        with contextlib.closing(sqlite3.connect(backup / 'Manifest.db')) as c, c:
            c.execute('INSERT INTO Files VALUES (?, ?, ?)', ('b'*40, 'AppDomain-uk.ventaxia.connect', 'Documents/devices.db'))
        with self.assertRaises(r.RecoveryError):
            r.find_database(backup)


if __name__ == '__main__':
    unittest.main()
