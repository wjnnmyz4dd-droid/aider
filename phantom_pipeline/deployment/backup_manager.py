"""Backup & Recovery (Phase 5) — checksummed backup/restore for
configuration, SQLite databases, analytics, and trade history.

SQLite databases are backed up via `sqlite3`'s own online backup API
(`Connection.backup`), never a raw file copy — a live database file can
be mid-write at copy time, so a plain `shutil.copy` risks capturing a
torn page; the online backup API is SQLite's own documented mechanism for
a consistent snapshot of a database that may be open elsewhere.

Every backup is checksummed (SHA-256) at creation time and
`verify_integrity` independently re-hashes the backup file itself,
never trusting the record's own claim.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import asdict
from datetime import datetime
from typing import Sequence, Tuple

from .models import BackupManifest, BackupRecord, BackupTarget, RestoreResult


def _sha256_of_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BackupManager:
    def __init__(self, backup_root: str) -> None:
        self._backup_root = backup_root

    def _target_dir(self, target: BackupTarget, now: datetime) -> str:
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        directory = os.path.join(self._backup_root, target.value.lower(), stamp)
        os.makedirs(directory, exist_ok=True)
        return directory

    def _backup_via_copy(self, target: BackupTarget, source_paths: Sequence[str], now: datetime) -> Tuple[BackupRecord, ...]:
        directory = self._target_dir(target, now)
        records = []
        for source_path in source_paths:
            if not os.path.isfile(source_path):
                continue
            backup_path = os.path.join(directory, os.path.basename(source_path))
            shutil.copy2(source_path, backup_path)
            records.append(
                BackupRecord(
                    target=target,
                    source_path=source_path,
                    backup_path=backup_path,
                    checksum=_sha256_of_file(backup_path),
                    size_bytes=os.path.getsize(backup_path),
                    timestamp=now,
                )
            )
        return tuple(records)

    def backup_configuration(self, config_paths: Sequence[str], now: datetime) -> Tuple[BackupRecord, ...]:
        return self._backup_via_copy(BackupTarget.CONFIGURATION, config_paths, now)

    def backup_analytics(self, analytics_paths: Sequence[str], now: datetime) -> Tuple[BackupRecord, ...]:
        return self._backup_via_copy(BackupTarget.ANALYTICS, analytics_paths, now)

    def backup_trade_history(self, trade_history_paths: Sequence[str], now: datetime) -> Tuple[BackupRecord, ...]:
        return self._backup_via_copy(BackupTarget.TRADE_HISTORY, trade_history_paths, now)

    def backup_database(self, db_paths: Sequence[str], now: datetime) -> Tuple[BackupRecord, ...]:
        directory = self._target_dir(BackupTarget.DATABASE, now)
        records = []
        for source_path in db_paths:
            if not os.path.isfile(source_path):
                continue
            backup_path = os.path.join(directory, os.path.basename(source_path))
            source_conn = sqlite3.connect(source_path)
            dest_conn = sqlite3.connect(backup_path)
            try:
                source_conn.backup(dest_conn)
            finally:
                dest_conn.close()
                source_conn.close()
            records.append(
                BackupRecord(
                    target=BackupTarget.DATABASE,
                    source_path=source_path,
                    backup_path=backup_path,
                    checksum=_sha256_of_file(backup_path),
                    size_bytes=os.path.getsize(backup_path),
                    timestamp=now,
                )
            )
        return tuple(records)

    def restore(self, record: BackupRecord, destination: str, now: datetime) -> RestoreResult:
        if not os.path.isfile(record.backup_path):
            return RestoreResult(record.target, False, "backup file missing", now)
        if _sha256_of_file(record.backup_path) != record.checksum:
            return RestoreResult(record.target, False, "backup checksum mismatch: refusing to restore", now)
        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
        shutil.copy2(record.backup_path, destination)
        if _sha256_of_file(destination) != record.checksum:
            return RestoreResult(record.target, False, "restored file checksum mismatch after copy", now)
        return RestoreResult(record.target, True, "restored successfully", now)

    def verify_integrity(self, record: BackupRecord) -> bool:
        if not os.path.isfile(record.backup_path):
            return False
        return _sha256_of_file(record.backup_path) == record.checksum

    def create_manifest(self, records: Sequence[BackupRecord], now: datetime) -> BackupManifest:
        return BackupManifest(records=tuple(records), created_at=now)

    def write_manifest(self, manifest: BackupManifest, path: str) -> None:
        payload = {
            "created_at": manifest.created_at.isoformat(),
            "records": [
                {**{k: v for k, v in asdict(r).items() if k not in ("target", "timestamp")},
                 "target": r.target.value, "timestamp": r.timestamp.isoformat()}
                for r in manifest.records
            ],
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2)

    def read_manifest(self, path: str) -> BackupManifest:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        records = tuple(
            BackupRecord(
                target=BackupTarget(r["target"]),
                source_path=r["source_path"],
                backup_path=r["backup_path"],
                checksum=r["checksum"],
                size_bytes=r["size_bytes"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
            )
            for r in payload["records"]
        )
        return BackupManifest(records=records, created_at=datetime.fromisoformat(payload["created_at"]))


__all__ = ["BackupManager"]
