#!/usr/bin/env python3
"""Offline recovery of one existing app record; never contacts a unit.

Reads an unencrypted Finder backup or an independently exported devices.db.
Only the explicit output file is written. No credential values are printed.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import sqlite3
import sys


class RecoveryError(ValueError):
    """An expected recovery failure, safe to show without database contents."""


def readonly_database(path: Path):
    if not path.is_file():
        raise RecoveryError("Database file not found.")
    # immutable avoids journal/lock writes. Sources must be a completed backup/export,
    # not a live app database with outstanding WAL transactions.
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)


def find_database(backup: Path) -> Path:
    root = backup.resolve()
    metadata = root / "Manifest.plist"
    if not metadata.is_file():
        raise RecoveryError("Not a Finder backup directory: Manifest.plist is missing.")
    try:
        with metadata.open("rb") as stream:
            manifest = plistlib.load(stream)
    except (ValueError, plistlib.InvalidFileException):
        raise RecoveryError("Cannot read backup metadata.") from None
    if not isinstance(manifest, dict):
        raise RecoveryError("Invalid backup metadata.")
    if manifest.get("IsEncrypted"):
        raise RecoveryError("Encrypted backups are unsupported. Keep encryption enabled; use a trusted local decrypted app-database export instead. No password is requested.")
    with closing(readonly_database(root / "Manifest.db")) as connection:
        rows = connection.execute(
            "SELECT fileID, relativePath FROM Files WHERE domain = ?",
            ("AppDomain-uk.ventaxia.connect",),
        ).fetchall()
    matches = [(file_id, relative) for file_id, relative in rows
               if isinstance(relative, str) and PurePosixPath(relative).name == "devices.db"]
    if len(matches) != 1:
        raise RecoveryError("Expected exactly one Vent-Axia devices.db. Use an explicit completed database export if absent or ambiguous.")
    file_id, _ = matches[0]
    if not isinstance(file_id, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", file_id):
        raise RecoveryError("Invalid backup file identifier.")
    candidate = (root / file_id[:2] / file_id).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise RecoveryError("The app database payload is missing or outside the selected backup.")
    return candidate


def recover(database: Path, device_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", device_id):
        raise RecoveryError("Invalid device ID.")
    with closing(readonly_database(database)) as connection:
        rows = connection.execute("SELECT id, options FROM devices WHERE id = ?", (device_id,)).fetchall()
    if len(rows) != 1:
        raise RecoveryError("The selected device ID was not found uniquely. Check the app's device ID; serial labels may differ.")
    try:
        options = json.loads(rows[0][1])
    except (ValueError, TypeError):
        raise RecoveryError("The selected device has invalid saved options.") from None
    if not isinstance(options, dict):
        raise RecoveryError("The selected device has no usable saved options.")
    identity, key = options.get("tcpTlsIdentity"), options.get("tcpTlsKey")
    if not isinstance(identity, str) or not identity or "\0" in identity or len(identity.encode()) > 256:
        raise RecoveryError("No usable saved TLS identity exists for this device.")
    if not isinstance(key, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}){1,256}", key):
        raise RecoveryError("No usable saved hexadecimal TLS key exists for this device.")
    if not any(bytes.fromhex(key)):
        raise RecoveryError("The saved all-zero TLS key is unavailable, not a working credential.")
    # Deliberately exclude PIN, home Wi-Fi password, MAC and unrelated device data.
    return {"device_id": device_id, "tls_identity": identity, "tls_psk_hex": key}


def save_credentials(path: Path, credentials: dict) -> None:
    content = (json.dumps(credentials, indent=2, ensure_ascii=True) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        raise RecoveryError("Output already exists; choose a new filename. Nothing was overwritten.") from None
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
    except BaseException:
        if descriptor != -1:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--backup", type=Path, help="Completed unencrypted Finder backup directory")
    source.add_argument("--database", type=Path, help="Completed, standalone exported devices.db")
    parser.add_argument("--device-id", required=True, help="Exactly the existing app device ID")
    parser.add_argument("--output", required=True, type=Path, help="New private JSON file; never overwritten")
    args = parser.parse_args(argv)
    try:
        database = find_database(args.backup) if args.backup else args.database
        credentials = recover(database, args.device_id)
        save_credentials(args.output, credentials)
    except (RecoveryError, sqlite3.Error, OSError) as error:
        # Do not stringify sqlite/OS errors: paths or user-controlled values may leak.
        message = str(error) if isinstance(error, RecoveryError) else "Cannot read the selected source or create the private output file. No credentials are printed."
        print(message, file=sys.stderr)
        return 1
    print("Saved the selected device credentials to the new private JSON file. Keep it local and out of Git.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
