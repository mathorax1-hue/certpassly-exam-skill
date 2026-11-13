"""certpassly.media_prep command-line interface.

Subcommands and exit codes (stable contract, mirrored in docs):

  doctor          dependency/OS/pinned-upstream inventory          0 / 1
  scan            read-only source image role inventory            0 / 1 / 2
  prepare         write verified clean candidates + manifest       0 / 1 / 2
  verify-package  strict allowlist privacy gate for a ZIP          0 / 1 / 3

  exit 0  applicable machine gates passed
  exit 1  invalid config or operational failure
  exit 2  blocked source / ambiguous / missing clean source (scan+prepare
          list every blocked question with a stable reason code)
  exit 3  privacy, integrity or manifest-tamper refusal (fail-closed)

Common flags: --config CONFIG (required for scan/prepare/verify-package),
--json (machine output), --explain (per-question decision summary),
--dry-run (prepare: decide + report, write nothing except the console),
--output/--report (write machine JSON), --force-extract (scan: re-run the
pinned upstream extractor), --out-dir (prepare: override output.clean_dir).

Windows: every command works unchanged in PowerShell / cmd; use py -3.11 and
forward slashes or quoted backslashes for paths. See
docs/NONAI-IMAGE-OPERATOR-RUNBOOK.md for full walkthroughs.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys

from . import (EXIT_BLOCKED, EXIT_OK, EXIT_OPERATIONAL, EXIT_TAMPER,
               TOOLKIT_NAME, TOOLKIT_VERSION, READINESS_SCHEMA_VERSION,
               MANIFEST_SCHEMA_VERSION, CONFIG_SCHEMA_VERSION,
               UPSTREAM_REPO, UPSTREAM_PIN)
from .errors import MediaPrepError


def _optional_module_status() -> dict:
    status = {}
    for key, mod in (("pymupdf", "fitz"), ("pillow", "PIL"), ("numpy", "numpy"),
                     ("opencv", "cv2"), ("jsonschema", "jsonschema")):
        try:
            __import__(mod)
            status[key] = True
        except ImportError:
            status[key] = False
    return status


def _tool_status() -> dict:
    return {name: bool(shutil.which(name)) for name in
            ("pdftohtml", "pdftoppm", "tesseract", "git")}


def cmd_doctor(args) -> int:
    report = {
        "toolkit": TOOLKIT_NAME,
        "version": TOOLKIT_VERSION,
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
        "modules": _optional_module_status(),
        "system_tools": _tool_status(),
        "schema_versions": {
            "readiness": READINESS_SCHEMA_VERSION,
            "manifest": MANIFEST_SCHEMA_VERSION,
            "config": CONFIG_SCHEMA_VERSION,
        },
        "upstream_pin": {"repo": UPSTREAM_REPO, "commit": UPSTREAM_PIN},
        "network_access": "none (strictly local; no upload/publication behavior)",
        "release_authority": False,
    }
    if args.config:
        from .config import load_config
        from .upstream_runner import upstream_status
        cfg = load_config(args.config)
        report["configured_upstream"] = upstream_status(cfg)
    ready = (report["modules"]["pymupdf"] and report["modules"]["pillow"]
             and report["modules"]["numpy"] and report["modules"]["opencv"])
    report["media_prep_ready"] = ready
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{TOOLKIT_NAME} {TOOLKIT_VERSION} | python {report['python']} | {report['os']}")
        print(f"modules: {report['modules']}")
        print(f"system tools: {report['system_tools']}")
        print(f"media_prep_ready: {ready}")
        if not ready:
            print("install: python -m pip install -e '.[phase1,visual]'")
    return EXIT_OK if (ready or args.json) else EXIT_OPERATIONAL


def _scan_inventory(cfg, *, force_extract=None):
    from .source_inventory import build_inventory
    return build_inventory(cfg, run_extract=force_extract)


def cmd_scan(args) -> int:
    from .config import load_config
    from .selection import run_selection
    cfg = load_config(args.config)
    inventory = _scan_inventory(cfg, force_extract=True if args.force_extract else None)

    readiness = run_selection(cfg, inventory)
    blocked = [qid for qid, r in sorted(readiness.items())
               if not r["is_learner_eligible"] and r["requires_image"]]

    out = {
        "schema_version": READINESS_SCHEMA_VERSION,
        "toolkit": {"name": TOOLKIT_NAME, "version": TOOLKIT_VERSION},
        "exam_code": cfg["exam_code"],
        "source_pdf_sha256": inventory["source_pdf_sha256"],
        "source_pdf_bytes": inventory["source_pdf_bytes"],
        "upstream": {"repo": cfg["upstream"]["repo"], "commit": cfg["upstream"]["commit"],
                     "out_dir": cfg["upstream"]["out_dir"]},
        "inventory_counts": inventory["counts"],
        "questions": [readiness[qid] for qid in sorted(readiness)],
        "counts": {
            "questions_total": len(readiness),
            "questions_requiring_image": sum(1 for r in readiness.values() if r["requires_image"]),
            "learner_eligible": sum(1 for r in readiness.values()
                                    if r["is_learner_eligible"] and r["requires_image"]),
            "blocked": len(blocked),
            "blocked_question_ids": blocked,
        },
    }
    if args.output:
        from .manifest import dump_json
        dump_json(args.output, out)
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        c = out["counts"]
        print(f"scan {cfg['exam_code']}: {c['questions_total']} questions, "
              f"{c['learner_eligible']} learner-eligible image questions, "
              f"{c['blocked']} blocked"
              + (f" -> {', '.join(blocked)}" if blocked else ""))
        if args.explain:
            for qid in sorted(readiness):
                r = readiness[qid]
                why = "; ".join(b["reason"] for b in r["blocked_reasons"]) or "ok"
                cand = r["clean_candidate"]
                method = cand["method"] if cand else "-"
                print(f"  {qid}: eligible={r['is_learner_eligible']} method={method} reasons={why}")
    return EXIT_BLOCKED if blocked else EXIT_OK


def cmd_prepare(args) -> int:
    from .config import load_config
    from .selection import run_selection
    from . import manifest as manifest_mod
    from .imageio import load_image
    from .renderer import render_crop
    cfg = load_config(args.config)
    if args.out_dir:
        cfg["output"]["clean_dir"] = os.path.abspath(args.out_dir)
    inventory = _scan_inventory(cfg)
    readiness = run_selection(cfg, inventory)

    clean_dir = cfg["output"]["clean_dir"]
    private_dir = os.path.join(cfg["output"]["private_dir"], "reviewer-only")
    written = {}
    reviewer_written = {}

    if not args.dry_run:
        # refuse to write into the upstream workspace: learner and reviewer
        # media must be separated from the extraction tree
        up_out = os.path.abspath(cfg["upstream"]["out_dir"])
        for label, target in (("clean_dir", clean_dir), ("private_dir", private_dir)):
            if os.path.abspath(target).startswith(up_out + os.sep):
                from .errors import ConfigError
                raise ConfigError(f"output.{label} must live OUTSIDE the upstream workspace "
                                  f"({up_out}); learner and reviewer media must be separated")
    media_src = os.path.join(cfg["upstream"]["out_dir"], "media", "src")

    for qid, rec in sorted(readiness.items()):
        if not rec["clean_candidate"] or not rec["is_learner_eligible"]:
            continue
        cand = rec["clean_candidate"]
        if args.dry_run:
            written[qid] = {"path": f"{qid}.<ext>", "sha256": None, "bytes": None,
                            "method": cand["method"], "source_sha256": cand["source_sha256"]}
            continue
        src = None
        if cand.get("pixel_source") == "pdf_region_render":
            out = render_crop(cfg["source"]["pdf"], cand["render"]["page"],
                              cand["render"]["clip"],
                              dpi=cand["render"]["dpi"], annots=False)
            cand["_render_bytes"] = out["png_bytes"]
        else:
            src = load_image(os.path.join(media_src, cand["source_file"]))
        written[qid] = manifest_mod.write_clean_candidate(clean_dir, qid, src, cand)

    if not args.dry_run:
        # reviewer-only isolation copies (every marked or answer-role image)
        for qid, rec in sorted(readiness.items()):
            for d in rec["role_decisions"]:
                if d["verified_role"] == "answer_marked_reviewer_only":
                    fpath = os.path.join(media_src, d["source_file"])
                    if os.path.isfile(fpath):
                        with open(fpath, "rb") as f:
                            reviewer_written[d["source_file"]] = manifest_mod.write_reviewer_only(
                                private_dir, d["source_file"], f.read())

    identity = {"sha256": inventory["source_pdf_sha256"],
                "bytes": inventory["source_pdf_bytes"]}
    upstream_facts = {"out_dir": cfg["upstream"]["out_dir"],
                      "repo": cfg["upstream"]["repo"], "commit": cfg["upstream"]["commit"]}
    doc = manifest_mod.build_manifest(cfg, identity, readiness,
                                      upstream_facts=upstream_facts,
                                      written=written, reviewer_written=reviewer_written)
    if not args.dry_run:
        manifest_mod.dump_json(cfg["output"]["manifest"], doc)
        manifest_mod.dump_json(cfg["output"]["inventory"], inventory)

    blocked = doc["counts"]["blocked_question_ids"]
    if args.json:
        print(json.dumps(doc, indent=2, ensure_ascii=False))
    else:
        c = doc["counts"]
        print(f"prepare {cfg['exam_code']}: {c['clean_files_written']} clean files, "
              f"{c['learner_eligible']} eligible, {c['blocked']} blocked"
              + (f" -> {', '.join(blocked)}" if blocked else ""))
        if not args.dry_run:
            print(f"manifest: {cfg['output']['manifest']}")
        if args.explain:
            for e in doc["questions"]:
                cand = e.get("clean_candidate") or {}
                print(f"  {e['question_id']}: {e['review_status']} "
                      f"method={cand.get('method', '-')} file={cand.get('file', '-')}")
    return EXIT_BLOCKED if blocked else EXIT_OK


def cmd_verify_package(args) -> int:
    from .config import load_config
    from .privacy_gate import verify_package, enforce
    cfg = load_config(args.config)
    report = verify_package(
        cfg["output"]["manifest"], args.package,
        allow_external_urls=cfg["privacy"]["allow_external_urls"],
        allowed_hosts=cfg["privacy"]["allowed_hosts"])
    enforce(report)
    if args.report:
        from .manifest import dump_json
        dump_json(args.report, report)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"verify-package {args.package}: "
              f"{'PASS' if report['passed'] else 'REFUSED'} "
              f"({report['image_members']} image members, "
              f"{report['allowlisted_images']} allowlisted)")
        for f in report["flags"]:
            print(f"  FLAG {f['member']}: {f['flag']} ({f['detail']})")
    if not report["passed"]:
        return EXIT_TAMPER
    # answer-architecture honesty: scoring keys present -> cannot certify
    if report["flags"]:
        print("NOT CERTIFIED: learner-visible scoring keys found; "
              "server-side scoring architecture must be reviewed on staging first",
              file=sys.stderr)
        return EXIT_TAMPER
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m certpassly.media_prep",
        description=f"{TOOLKIT_NAME} {TOOLKIT_VERSION}: non-AI clean simulator-image "
                    "preparation and privacy verification on the pinned upstream extraction")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="dependency/OS/pinned-upstream inventory")
    d.add_argument("--config", help="optional config for upstream checkout status")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("scan", help="read-only source image role inventory + readiness")
    s.add_argument("--config", required=True)
    s.add_argument("--output", help="write the readiness JSON here")
    s.add_argument("--json", action="store_true")
    s.add_argument("--explain", action="store_true")
    s.add_argument("--force-extract", action="store_true",
                   help="re-run the pinned upstream extractor even if output exists")
    s.set_defaults(fn=cmd_scan)

    pr = sub.add_parser("prepare", help="write ONLY verified clean candidates + manifest")
    pr.add_argument("--config", required=True)
    pr.add_argument("--out-dir", help="override output.clean_dir")
    pr.add_argument("--json", action="store_true")
    pr.add_argument("--explain", action="store_true")
    pr.add_argument("--dry-run", action="store_true")
    pr.set_defaults(fn=cmd_prepare)

    v = sub.add_parser("verify-package", help="strict allowlist privacy gate for a draft ZIP")
    v.add_argument("--config", required=True)
    v.add_argument("--package", required=True)
    v.add_argument("--site-format", help="optional path to the upstream reference/site-format "
                                          "dir; the gate scans the same reference surface")
    v.add_argument("--report", help="write the verification report JSON here")
    v.add_argument("--json", action="store_true")
    v.set_defaults(fn=cmd_verify_package)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except MediaPrepError as exc:
        print(f"ERROR [{type(exc).__name__}]: {exc}", file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        print(f"ERROR [Operational]: {exc}", file=sys.stderr)
        return EXIT_OPERATIONAL


if __name__ == "__main__":
    sys.exit(main())
