#!/usr/bin/env python3
"""Validate one answer-free media-layout against the original 30-type registry.

Exit 0 = structurally valid technical media contract (NOT site approval).
Exit 2 = ambiguous, unpublishable or unsafe media geometry.
Exit 1 = invalid input/dependency. Only synthetic examples in public CI.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from certpassly.media_prep.media_layout import (
    load_type_registry, validate_layout, layout_fingerprint,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", required=True,
                    help="Original pinned upstream reference/site-format/v1/question_types.json")
    ap.add_argument("--layout", required=True, help="One answer-free media-layout-v1 JSON")
    ap.add_argument("--report", help="Optional local technical report JSON")
    args = ap.parse_args(argv)
    try:
        registry = load_type_registry(args.registry)
        layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
        result = validate_layout(layout, registry, for_learner=True)
        result["layout_sha256"] = layout_fingerprint(layout)
        result["source_registry_path"] = str(Path(args.registry).resolve())
        result["staging_importer_status"] = "UNTESTED"
        result["human_review_status"] = "NOT_APPROVED"
        rc = 0 if result["status"] == "PASS" else 2
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        result = {"status": "ERROR", "reasons": [str(exc)],
                  "site_ui_status": "UNTESTED", "staging_importer_status": "UNTESTED",
                  "human_review_status": "NOT_APPROVED"}
        rc = 1
    if args.report:
        Path(args.report).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                     encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
