"""SQLite-backed content-addressed checkpoints for trusted local workflow steps."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_json(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Checkpoints:
    """Checkpoint store. Treat state path as private; it may contain file hashes."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.db = sqlite3.connect(db_path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS stages (
            name TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            status TEXT NOT NULL,
            output_hashes TEXT NOT NULL,
            updated_utc TEXT NOT NULL,
            elapsed_seconds REAL NOT NULL,
            error TEXT NOT NULL
        )""")
        self.db.commit()

    def get(self, name: str) -> dict | None:
        row = self.db.execute(
            "SELECT name,fingerprint,status,output_hashes,updated_utc,elapsed_seconds,error "
            "FROM stages WHERE name=?", (name,)
        ).fetchone()
        if row is None:
            return None
        keys = ("name", "fingerprint", "status", "output_hashes", "updated_utc", "elapsed_seconds", "error")
        result = dict(zip(keys, row))
        result["output_hashes"] = json.loads(result["output_hashes"])
        return result

    def record(self, name: str, fingerprint: str, status: str, outputs: dict[str, str],
               elapsed: float = 0.0, error: str = "") -> None:
        self.db.execute("""INSERT INTO stages(name,fingerprint,status,output_hashes,updated_utc,elapsed_seconds,error)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET
            fingerprint=excluded.fingerprint,status=excluded.status,
            output_hashes=excluded.output_hashes,updated_utc=excluded.updated_utc,
            elapsed_seconds=excluded.elapsed_seconds,error=excluded.error""",
            (name, fingerprint, status, json.dumps(outputs, sort_keys=True), utcnow(), elapsed, error))
        self.db.commit()

    def list(self) -> list[dict]:
        names = self.db.execute("SELECT name FROM stages ORDER BY name").fetchall()
        return [self.get(row[0]) for row in names]

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
