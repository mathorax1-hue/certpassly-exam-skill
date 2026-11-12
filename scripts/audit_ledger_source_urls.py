#!/usr/bin/env python3
"""Fail-closed strict per-URL validator for ledger source URLs vs saved evidence.

For EVERY ``source_urls`` entry of EVERY ledger record this tool requires a
byte-verified saved snapshot: a matching receipt, the receipt's recorded source
URL equal to the ledger URL or to an explicitly documented redirect target, a
saved page whose SHA-256 and byte length match the receipt, ``capture_mode``
``downloaded``, and a proof quote present in the saved page's visible text.

It deliberately does NOT accept a single per-question hash field as proof for a
question that references several URLs: each URL instance is checked on its own.

Additionally, when ledger records carry per-record evidence blocks (by default
``official_source_evidence_20261112``, override with ``--evidence-field``),
this tool validates the blocks themselves, fail closed: every URL-bearing
record must carry a block, the block's ``urls`` list must match the record's
``source_urls`` in exact count, order and URL, and every block entry must agree
with the byte-verified receipt and saved page for that exact URL instance
(receipt filename, page filename, SHA-256, byte length, capture timestamp,
capture mode and final redirect target). A block on a record without
``source_urls`` fails; a missing block on a URL-bearing record fails; a block
whose redirect target is not corroborated by the per-question linkage sidecar
fails (this closes cross-question redirect substitution).

The linkage sidecar is bound per question: each sidecar record must match a
ledger record that actually carries ``source_urls``, must list that record's
exact URL list, and each per-URL mapping must reference only URLs that record
actually lists. Unknown or orphan sidecar mappings are blockers, never silent
proof. Redirected instances require the per-question sidecar mapping; a
redirect documented nowhere or only by the ledger block itself fails closed.

A ledger with per-record blocks absent everywhere runs in an explicitly
reduced-assurance mode: ``source_urls`` vs receipts is still validated, but the
report clearly states the per-record evidence blocks were NOT validated, so the
result must not be mislabeled as complete ledger evidence. A ledger with zero
URL instances never reports vacuous success.

Many-to-one reuse (one URL shared by several records) is valid only when every
instance resolves to the same receipt and the sidecar's shared-with lists agree
with the actual ledger sharing. Evidence files no ledger URL refers to are
reported as orphans. This is structural byte/linkage validation, not semantic
answer verification, human review, or release approval. Public tests use
wholly synthetic fixtures; real evidence stays private. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_official_source import normalized_text, validate_url  # noqa: E402

SHA = re.compile(r"^[a-f0-9]{64}$")
ALLOWED_VERDICTS_URL_STATE = {"captured_downloaded_verified"}
DEFAULT_EVIDENCE_FIELD = "official_source_evidence_20261112"


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path.name}: {exc}") from exc


def iter_receipts(evidence_dir: Path):
    for receipt_path in sorted(evidence_dir.glob("*.source.json")):
        if receipt_path.is_symlink():
            yield receipt_path, None
            continue
        try:
            record = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            yield receipt_path, None
            continue
        yield receipt_path, record


def audit(ledger: dict, evidence_dir: Path, linkage: dict | None, allow_hosts: list[str],
          evidence_field: str = DEFAULT_EVIDENCE_FIELD) -> dict:
    blockers: list[dict] = []

    def block(item: str, reason: str):
        blockers.append({"item": item, "reason": reason})

    if not isinstance(ledger, dict):
        return {"status": "invalid", "blockers": [{"item": "ledger", "reason": "not an object"}],
                "counts": {}, "url_instances": [], "note": "invalid ledger"}
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        return {"status": "invalid", "blockers": [{"item": "ledger", "reason": "entries must be a list"}],
                "counts": {}, "url_instances": [], "note": "invalid ledger"}

    # Receipt index keyed by the URL recorded inside the receipt (the final URL
    # the vendor served; redirects are documented per question by the sidecar).
    receipts_by_url: dict[str, dict] = {}
    for receipt_path, record in iter_receipts(evidence_dir):
        name = receipt_path.name
        if record is None:
            block(name, "receipt unreadable or a symlink")
            continue
        url = record.get("source_url")
        if not isinstance(url, str) or not url:
            block(name, "receipt missing source_url")
            continue
        if url in receipts_by_url:
            block(name, f"duplicate receipt for one URL: {url}")
            continue
        page_name = record.get("saved_content_path")
        if (not isinstance(page_name, str) or not page_name or "/" in page_name
                or "\\" in page_name or page_name.startswith(".")):
            block(name, "invalid saved_content_path")
            continue
        page = evidence_dir / page_name
        if not page.is_file() or page.is_symlink():
            block(name, "saved page missing or unsafe")
            continue
        blob = page.read_bytes()
        digest = record.get("sha256")
        if not isinstance(digest, str) or not SHA.fullmatch(digest):
            block(name, "receipt SHA-256 missing or malformed")
            continue
        if hashlib.sha256(blob).hexdigest() != digest:
            block(name, "saved page SHA-256 mismatch")
            continue
        if len(blob) != record.get("bytes"):
            block(name, "saved page byte length mismatch")
            continue
        if record.get("capture_mode") != "downloaded":
            block(name, "capture_mode is not downloaded")
            continue
        quote = record.get("quote")
        content_type = record.get("content_type")
        if (not isinstance(quote, str) or not quote.strip() or len(quote) > 250
                or content_type not in ("text/html", "text/plain")
                or " ".join(quote.split()) not in normalized_text(blob, content_type)):
            block(name, "proof quote absent from saved page")
            continue
        try:
            validate_url(url, allow_hosts)
        except ValueError:
            block(name, "receipt source_url not on the allowlist")
            continue
        receipts_by_url[url] = {
            "receipt": name,
            "page": page_name,
            "sha256": digest,
            "bytes": len(blob),
            "captured_at_utc": record.get("captured_at_utc"),
            "quote": quote,
            "source_url": url,
        }

    # ---------- ledger index ----------
    ledger_by_qid: dict[str, dict] = {}
    for item in entries:
        if not isinstance(item, dict):
            block("ledger entry", "entry is not an object")
            continue
        qid = str(item.get("question_key") or "?")
        if qid in ledger_by_qid:
            block(qid, "duplicate question_key in ledger")
            continue
        ledger_by_qid[qid] = item
    url_bearing = {q: e for q, e in ledger_by_qid.items()
                   if isinstance(e.get("source_urls"), list) and e.get("source_urls")}
    for q, e in ledger_by_qid.items():
        urls = e.get("source_urls")
        if urls is not None and not isinstance(urls, list):
            block(q, "source_urls must be a list")

    # actual sharing map straight from the ledger
    sharing: dict[str, set] = {}
    for q, e in url_bearing.items():
        for u in e["source_urls"]:
            if isinstance(u, str) and u:
                sharing.setdefault(u, set()).add(q)

    # ---------- per-question linkage sidecar binding ----------
    sidecar_by_qid: dict[str, dict] = {}
    linkage_provided = linkage is not None
    if linkage is not None:
        if not isinstance(linkage, dict):
            block("linkage", "linkage must be an object")
            linkage = None
    if linkage is not None:
        records = linkage.get("records")
        if not isinstance(records, list):
            block("linkage", "linkage records must be a list")
            records = []
        for record in records:
            if not isinstance(record, dict):
                block("linkage record", "linkage record is not an object")
                continue
            qid = str(record.get("question_key") or "?")
            if qid in sidecar_by_qid:
                block(f"linkage: {qid}", "duplicate linkage record for one question")
                continue
            sidecar_by_qid[qid] = record
        for qid, record in sidecar_by_qid.items():
            entry = url_bearing.get(qid)
            if entry is None:
                block(f"linkage: {qid}",
                      "unknown linkage record: question absent from ledger or without source_urls")
                continue
            declared = record.get("ledger_source_urls")
            if declared != entry["source_urls"]:
                block(f"linkage: {qid}",
                      "linkage ledger_source_urls does not equal the ledger record's source_urls "
                      "(count, order or URL mismatch)")
            links = record.get("url_links")
            if not isinstance(links, list):
                block(f"linkage: {qid}", "linkage url_links must be a list")
                links = []
            for link in links:
                if not isinstance(link, dict):
                    block(f"linkage: {qid}", "url_link is not an object")
                    continue
                url = link.get("ledger_url")
                if not isinstance(url, str) or url not in entry["source_urls"]:
                    block(f"linkage: {qid}", "orphan linkage mapping: URL not in this question's source_urls")
                    continue
                if link.get("state") != "captured_downloaded_verified":
                    block(f"linkage: {qid}: {url}", "linkage state is not captured_downloaded_verified")
                receipt_url = url
                redirected = bool(link.get("redirected"))
                if redirected:
                    final = link.get("final_redirected_url")
                    if not isinstance(final, str) or final == url:
                        block(f"linkage: {qid}: {url}",
                              "redirected mapping missing a distinct final_redirected_url")
                        continue
                    receipt_url = final
                receipt = receipts_by_url.get(receipt_url)
                if receipt is None:
                    block(f"linkage: {qid}: {url}",
                          "linkage mapping has no byte-verified receipt for its target URL")
                    continue
                if link.get("receipt_recorded_source_url") != receipt_url:
                    block(f"linkage: {qid}: {url}",
                          "linkage receipt_recorded_source_url does not match the mapped receipt URL")
                for field, actual in (("receipt_path", receipt["receipt"]),
                                      ("page_path", receipt["page"]),
                                      ("content_sha256", receipt["sha256"]),
                                      ("bytes", receipt["bytes"]),
                                      ("captured_at_utc", receipt["captured_at_utc"])):
                    declared_value = link.get(field)
                    if isinstance(declared_value, str) and "/" in declared_value:
                        # sidecar uses repo-relative paths; compare the basename
                        declared_value = declared_value.rsplit("/", 1)[-1]
                    if declared_value != actual:
                        block(f"linkage: {qid}: {url}",
                              f"linkage {field} does not match the byte-verified receipt")
                if link.get("capture_mode") != "downloaded":
                    block(f"linkage: {qid}: {url}", "linkage capture_mode is not downloaded")
                if not redirected and link.get("final_redirected_url") not in (None, url):
                    block(f"linkage: {qid}: {url}",
                          "non-redirected mapping must not claim a different final_redirected_url")
                for other in link.get("shared_with_question_keys", []) or []:
                    if other not in sharing.get(url, set()) - {qid}:
                        block(f"linkage: {qid}: {url}",
                              f"shared_with question {other} does not reference this URL in the ledger")
                # bidirectional completeness of shared_with
                expected_shared = sharing.get(url, set()) - {qid}
                declared_shared = set(link.get("shared_with_question_keys", []) or [])
                if declared_shared != expected_shared:
                    block(f"linkage: {qid}: {url}",
                          "shared_with_question_keys does not match the actual ledger sharing")
        for qid in url_bearing:
            if qid not in sidecar_by_qid:
                block(f"linkage: {qid}", "URL-bearing ledger record missing from the linkage sidecar")

    # ---------- per-record evidence blocks ----------
    blocks_present = any(
        isinstance(e.get(evidence_field), dict) or isinstance(e.get(evidence_field), list)
        for e in ledger_by_qid.values())
    blocks_validated = 0
    if blocks_present:
        for qid, entry in ledger_by_qid.items():
            urls = entry.get("source_urls") if isinstance(entry.get("source_urls"), list) else []
            block_data = entry.get(evidence_field)
            if not urls:
                if block_data is not None:
                    block(f"ledger block: {qid}",
                          f"evidence block present on a record without source_urls ({evidence_field})")
                continue
            if not isinstance(block_data, dict) or not isinstance(block_data.get("urls"), list):
                block(f"ledger block: {qid}",
                      f"URL-bearing record missing its {evidence_field} evidence block")
                continue
            block_urls = block_data["urls"]
            if len(block_urls) != len(urls):
                block(f"ledger block: {qid}",
                      f"evidence block url count {len(block_urls)} != source_urls count {len(urls)}")
            for i, (bu, su) in enumerate(zip(block_urls, urls)):
                if not isinstance(bu, dict) or bu.get("url") != su:
                    block(f"ledger block: {qid}#{i}",
                          "evidence block entry URL does not equal the source_urls entry "
                          "(order or content mismatch)")
            blocks_validated += 1

    # ---------- per-instance resolution and block field validation ----------
    instances = []
    seen_pairs = set()
    for qid, entry in url_bearing.items():
        urls = entry["source_urls"]
        block_data = entry.get(evidence_field) if blocks_present else None
        block_urls = block_data.get("urls", []) if isinstance(block_data, dict) else []
        for idx, url in enumerate(urls):
            if not isinstance(url, str) or not url:
                block(f"{qid}", "empty source_urls entry")
                continue
            key = (qid, url)
            instance_note = "duplicate listing of the same URL in one record" if key in seen_pairs else ""
            seen_pairs.add(key)
            receipt = receipts_by_url.get(url)
            redirected = False
            if receipt is None:
                # Only this question's own sidecar mapping may document a redirect.
                side = sidecar_by_qid.get(qid)
                final = None
                if side is not None:
                    for link in side.get("url_links", []) or []:
                        if isinstance(link, dict) and link.get("ledger_url") == url and link.get("redirected"):
                            final = link.get("final_redirected_url")
                            break
                if isinstance(final, str) and final != url and final in receipts_by_url:
                    receipt = receipts_by_url[final]
                    redirected = True
                else:
                    instances.append({"question_key": qid, "ledger_url": url,
                                      "state": "missing_saved_evidence"})
                    reason = "no byte-verified receipt for this exact URL instance"
                    if blocks_present and idx < len(block_urls):
                        reason += ("; the record's evidence block alone cannot document a redirect "
                                   "without the per-question linkage sidecar")
                    block(f"{qid}: {url}", reason)
                    continue
            else:
                # Direct receipt: the sidecar, if present, must not claim a redirect.
                side = sidecar_by_qid.get(qid)
                if side is not None:
                    for link in side.get("url_links", []) or []:
                        if (isinstance(link, dict) and link.get("ledger_url") == url
                                and link.get("redirected")
                                and link.get("final_redirected_url") != url):
                            block(f"{qid}: {url}",
                                  "sidecar claims a redirect but a byte-verified receipt exists "
                                  "for the exact ledger URL")
                            break
            entry_row = {
                "question_key": qid,
                "ledger_url": url,
                "resolved_url": receipt["source_url"] if redirected else url,
                "redirected": redirected,
                "state": "captured_downloaded_verified",
                "receipt": receipt["receipt"],
                "page": receipt["page"],
                "sha256": receipt["sha256"],
                "bytes": receipt["bytes"],
            }
            if instance_note:
                entry_row["note"] = instance_note
            # ---------- block field validation against the resolved receipt ----------
            if blocks_present:
                if idx >= len(block_urls) or not isinstance(block_urls[idx], dict):
                    block(f"ledger block: {qid}#{idx}",
                          "no evidence block entry for this URL instance")
                else:
                    bu = block_urls[idx]
                    item = f"ledger block: {qid}#{idx}"
                    if bu.get("receipt") != receipt["receipt"]:
                        block(item, "block receipt filename does not match the byte-verified receipt "
                                    "for this URL instance")
                    if bu.get("page") != receipt["page"]:
                        block(item, "block page filename does not match the saved page")
                    if bu.get("content_sha256") != receipt["sha256"]:
                        block(item, "block content_sha256 does not match the receipt/saved-page SHA-256")
                    if bu.get("bytes") != receipt["bytes"]:
                        block(item, "block byte length does not match the saved page")
                    if bu.get("captured_at_utc") != receipt["captured_at_utc"]:
                        block(item, "block captured_at_utc does not match the receipt")
                    if bu.get("capture_mode") != "downloaded":
                        block(item, "block capture_mode is not downloaded")
                    final_claim = bu.get("final_redirected_url")
                    if redirected:
                        if final_claim != receipt["source_url"]:
                            block(item, "block final_redirected_url does not match the byte-verified "
                                       "redirect target recorded by the receipt")
                    else:
                        if final_claim not in (None, url):
                            block(item, "non-redirected instance must not claim a different "
                                       "final_redirected_url")
            instances.append(entry_row)

    # Orphan receipts: evidence no ledger URL refers to.
    referenced = {(i.get("resolved_url") or i.get("ledger_url")) for i in instances} | {i["ledger_url"] for i in instances}
    for url in receipts_by_url:
        if url not in referenced:
            block(receipts_by_url[url]["receipt"], "evidence not referenced by any ledger URL")

    shared: dict[str, list[str]] = {}
    for i in instances:
        if i.get("state") in ALLOWED_VERDICTS_URL_STATE:
            shared.setdefault(i["ledger_url"], []).append(i["question_key"])
    shared = {u: sorted(set(qs)) for u, qs in shared.items() if len(set(qs)) > 1}

    counts = {
        "records_with_source_urls": len(url_bearing),
        "url_instances": len(instances),
        "unique_ledger_urls": len({i["ledger_url"] for i in instances}),
        "verified_instances": sum(1 for i in instances if i["state"] in ALLOWED_VERDICTS_URL_STATE),
        "redirected_instances": sum(1 for i in instances if i.get("redirected")),
        "shared_urls": shared,
    }
    if any(not isinstance(e.get("captured_at_utc"), str) for e in receipts_by_url.values()):
        block("evidence", "receipt missing capture timestamp")

    # Vacuous-success suppression: nothing to verify is not a verification.
    if counts["records_with_source_urls"] == 0:
        block("ledger", "zero URL instances in the ledger; vacuous success suppressed")

    if blocks_present:
        counts["evidence_block_records"] = blocks_validated
        counts["evidence_blocks_mode"] = "strict_per_record_blocks_validated"
        assurance = "full_strict_per_url_and_blocks"
        assurance_note = ("Per-record evidence blocks were present and validated against the "
                          "byte-verified receipts and saved pages, per URL instance.")
    else:
        counts["evidence_block_records"] = 0
        counts["evidence_blocks_mode"] = "absent_read_only"
        assurance = "reduced_source_urls_only_no_blocks"
        assurance_note = ("REDUCED ASSURANCE: no per-record evidence blocks were present in this "
                          "ledger, so only source_urls vs receipts/pages was validated. This is NOT "
                          "complete ledger evidence validation and must not be labeled as such.")

    report = {
        "status": "blocked" if blockers else "all_url_instances_byte_verified",
        "counts": counts,
        "url_instances": instances,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "ledger_evidence_blocks": {
            "present": blocks_present,
            "field": evidence_field,
            "records_with_blocks": blocks_validated,
        },
        "assurance": assurance,
        "assurance_note": assurance_note,
        "human_review_approved": False,
        "release_approved": False,
        "note": "Strict per-URL byte/linkage validation only. No semantic answer, "
                "option-correctness, human-review or release judgment.",
    }
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--linkage", type=Path, help="Per-question URL linkage sidecar")
    parser.add_argument("--allow-host", action="append", required=True)
    parser.add_argument("--evidence-field", default=DEFAULT_EVIDENCE_FIELD,
                        help="Ledger field holding per-record evidence blocks "
                             f"(default: {DEFAULT_EVIDENCE_FIELD})")
    parser.add_argument("--private-report", type=Path)
    args = parser.parse_args(argv)
    try:
        ledger = load_json(args.ledger)
        linkage = load_json(args.linkage) if args.linkage else None
        if linkage is not None and not isinstance(linkage, dict):
            raise ValueError("linkage must be an object")
    except ValueError as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    report = audit(ledger, args.evidence_dir, linkage, args.allow_host, args.evidence_field)
    output = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.private_report:
        args.private_report.parent.mkdir(parents=True, exist_ok=True)
        args.private_report.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if report["status"] == "all_url_instances_byte_verified" else 2


if __name__ == "__main__":
    sys.exit(main())
