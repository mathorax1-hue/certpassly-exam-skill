#!/usr/bin/env python3
"""Append authenticated/attributed conversation events to ONE existing master JSON.

Manual, explicitly invoked tool only. No ChatGPT account-wide export, memory
installation, network access, automatic monitoring, or guarantee of unavailable
historical conversations. Real master JSON and any owner evidence are PRIVATE.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROLES = {"user", "assistant", "tool", "system_summary"}
ORIGINS = {"visible_chat", "user_supplied_export", "connected_source", "manual_summary"}
CREDENTIALS = [
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{25,}"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
]
MAX_EVENT_TEXT = 250_000


def evidence_hash(master: dict) -> str:
    """Report integrity of existing embedded evidence without changing it."""
    evidence = master.get("single_file_evidence_archive")
    if evidence is None:
        return "absent"
    return hashlib.sha256(
        json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def validate_event(event: dict) -> None:
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    if not isinstance(event.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}", event["id"]):
        raise ValueError("event id missing or unsafe")
    if event.get("role") not in ROLES:
        raise ValueError(f"{event['id']}: unknown role")
    if event.get("origin") not in ORIGINS:
        raise ValueError(f"{event['id']}: origin not established")
    if not isinstance(event.get("text"), str) or not event["text"].strip():
        raise ValueError(f"{event['id']}: missing text")
    if len(event["text"]) > MAX_EVENT_TEXT:
        raise ValueError(f"{event['id']}: event text too long")
    if not isinstance(event.get("source_reference"), str) or not event["source_reference"].strip():
        raise ValueError(f"{event['id']}: missing provenance reference")
    if event.get("verbatim") not in (True, False):
        raise ValueError(f"{event['id']}: verbatim must be boolean")
    if event["verbatim"] and event["origin"] == "manual_summary":
        raise ValueError(f"{event['id']}: summarized text cannot claim verbatim transcript")
    if any(regex.search(event["text"]) for regex in CREDENTIALS):
        raise ValueError(f"{event['id']}: credential-like secret in new event")
    if event.get("released") is True or event.get("human_verified") is True:
        raise ValueError(f"{event['id']}: conversation history cannot grant release or human approval")


def update_master(master: dict, incoming: dict) -> tuple[dict, int]:
    if not isinstance(master, dict) or not isinstance(master.get("archive_metadata"), dict):
        raise ValueError("master archive metadata missing")
    if not isinstance(incoming, dict) or not isinstance(incoming.get("events"), list):
        raise ValueError("incoming event batch must contain an events list")
    if not incoming["events"]:
        raise ValueError("incoming events list is empty")
    source = incoming.get("batch_source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("batch_source required to recover provenance")
    before = evidence_hash(master)
    archive = json.loads(json.dumps(master, ensure_ascii=False))
    saved = archive.setdefault("conversation_events_incremental", [])
    if not isinstance(saved, list):
        raise ValueError("existing conversation_events_incremental is not a list")
    index = {}
    for event in saved:
        if not isinstance(event, dict) or not isinstance(event.get("id"), str):
            raise ValueError("existing event registry is malformed")
        if event["id"] in index:
            raise ValueError("existing duplicate event IDs")
        index[event["id"]] = event
    # Validate the entire batch before writing or changing the snapshot.
    new = []
    batch_seen = set()
    for event in incoming["events"]:
        validate_event(event)
        ident = event["id"]
        if ident in batch_seen:
            raise ValueError(f"duplicate ID within incoming batch: {ident}")
        batch_seen.add(ident)
        if ident in index:
            if index[ident] != event:
                raise ValueError(f"existing event ID conflict: {ident}")
            continue
        new.append(event)
    if not new:
        return archive, 0
    saved.extend(new)
    archive.setdefault("archive_update_history", []).append({
        "date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": "manual_append_explicitly_available_conversation_events",
        "batch_source": source,
        "added_events": len(new),
        "total_event_records_in_incremental_section": len(saved),
        "existing_embedded_evidence_sha256_preserved": before,
        "not_a_complete_global_chat_export": True,
    })
    metadata = archive["archive_metadata"]
    metadata["archive_status"] = "manual_append_only_master_json"
    metadata["last_appended_date_local"] = datetime.now(timezone.utc).date().isoformat()
    metadata["history_completion_claim"] = (
        "Only captured/accessible events, with explicit provenance. "
        "Never claim inaccessible or omitted chat turns were archived."
    )
    if evidence_hash(archive) != before:
        raise ValueError("existing embedded evidence unexpectedly changed")
    return archive, len(new)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--private-master", required=True, type=Path, help="Existing private master JSON; NEVER public path")
    p.add_argument("--event-batch", required=True, type=Path, help="Provenance-attributed JSON events")
    p.add_argument("--apply", action="store_true", help="Explicitly replace same master JSON atomically; otherwise dry-run")
    args = p.parse_args(argv)
    temp_name = None
    try:
        target = args.private_master.resolve(strict=True)
        if not target.is_file() or target.is_symlink():
            raise ValueError("master file must be an existing regular file")
        original = json.loads(target.read_text(encoding="utf-8"))
        incoming = json.loads(args.event_batch.read_text(encoding="utf-8"))
        updated, added = update_master(original, incoming)
        status = "preview" if not args.apply else "unchanged" if not added else "updated"
        if args.apply and added:
            # Only ever overwrite the existing canonical file. Never keep a ZIP
            # or second shadow master. Preserve existing access permissions.
            payload = (json.dumps(updated, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".history-update-", delete=False) as tmp:
                temp_name = tmp.name
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.chmod(temp_name, target.stat().st_mode & 0o777)
            os.replace(temp_name, target)
            temp_name = None
        print(json.dumps({"status": status, "new_events": added,
                          "total_incremental_events": len(updated.get("conversation_events_incremental", [])),
                          "embedded_evidence_sha256": evidence_hash(updated),
                          "history_claim": "accessible events only; not a global verbatim export"}, indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError, TypeError) as e:
        print("BLOCKED: " + str(e), file=sys.stderr)
        return 2
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
