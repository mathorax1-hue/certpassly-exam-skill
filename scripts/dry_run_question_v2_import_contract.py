#!/usr/bin/env python3
"""Offline Question V2 -> importer-contract projection dry-run.

Never connects to a website or database; no deploy, key research, or publication.
Learner view is projected from learner ONLY. Answer block is server-only;
the report contains digests, not private answer data. Keep output private.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

QFILE = re.compile(r"^(q\d{3})\.v(\d+)\.json$")
BAD_KEYS = {"answer_key", "correct_option_ids", "explanation", "correct_answers",
            "answers", "solution", "answer"}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
           separators=(",", ":")).encode()).hexdigest()

def secret_keys(value, path="learner"):
    problems = []
    if isinstance(value, dict):
        for k, v in value.items():
            here = path + "." + k
            if k.lower() in BAD_KEYS:
                problems.append(here)
            problems.extend(secret_keys(v, here))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            problems.extend(secret_keys(v, path + "[" + str(i) + "]"))
    return problems

def project(doc):
    if not isinstance(doc, dict):
        raise ValueError("not an object")
    key, version, kind = doc.get("question_key"), doc.get("version"), doc.get("type")
    learner = doc.get("learner")
    answer = doc.get("answer")
    if not isinstance(key, str) or not key or not isinstance(version, int) or version < 1:
        raise ValueError("invalid identity")
    if not isinstance(learner, dict) or not isinstance(answer, dict):
        raise ValueError("missing learner or server-only answer")
    leaks = secret_keys(learner)
    public_view = {"question_key": key, "version": version, "type": kind,
                   "public_view": learner, "record_status": "draft"}
    if "answer" in public_view or "answer_key" in public_view:
        leaks.append("public_view top-level")
    return {"question_key": key, "version": version,
            "idempotency_key": key + ":v" + str(version),
            "type": kind, "public_view_sha256": digest(public_view),
            "server_answer_sha256": digest(answer), "secret_leaks": leaks}

def inspect(folder, flagged_keys, expected=89):
    records = []
    seen = set()
    problems = []
    for path in sorted(Path(folder).glob("*.json")):
        m = QFILE.fullmatch(path.name)
        if not m:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            result = project(doc)
            if result["question_key"] != m.group(1) or result["version"] != int(m.group(2)):
                problems.append({"filename": path.name, "error": "identity mismatches filename"})
            if result["idempotency_key"] in seen:
                problems.append({"filename": path.name, "error": "duplicate reimport identity"})
            seen.add(result["idempotency_key"])
            if result["secret_leaks"]:
                problems.append({"filename": path.name, "error": "learner secret key",
                                 "paths": result["secret_leaks"]})
            result["source_review_blocked"] = result["question_key"] in set(flagged_keys)
            del result["secret_leaks"]
            records.append(result)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            problems.append({"filename": path.name, "error": type(exc).__name__})
    eligible = [r for r in records if not r["source_review_blocked"]]
    return {"schema": "certpassly.offline-importer-projection.v1",
            "draft_only": True, "website_import_tested": False,
            "production_deployed": False, "answer_research_performed": False,
            "expected": expected, "mapped": len(records), "unique_identities": len(seen),
            "source_blocked": len(records) - len(eligible),
            "non_source_blocked": len(eligible),
            "problems": problems, "projection_pass":
                len(records) == expected and len(seen) == expected and not problems,
            "records": records,
            "caution": "Only a local contract projection. Website ingestion, sanitizer, "
                       "database idempotency, answer encryption and browser rendering "
                       "remain untested."}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--v2-dir", required=True, type=Path)
    ap.add_argument("--cannot-convert", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--expected", type=int, default=89)
    a = ap.parse_args()
    cannot = json.loads(a.cannot_convert.read_text(encoding="utf-8"))
    keys = cannot.get("question_keys") or [x["question_key"] for x in cannot.get("items", [])]
    report = inspect(a.v2_dir, keys, a.expected)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in
        ("mapped", "source_blocked", "projection_pass", "website_import_tested")}))
    return 0 if report["projection_pass"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
