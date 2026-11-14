#!/usr/bin/env python3
"""B6 private original-PDF media replay (NO release authority).

This command generates reviewer-only evidence under config.output.private_dir.
Exit 0 = machine replay complete with no machine issues, still HUMAN PENDING;
exit 2 = blocked cases, mismatched original SHA, marked candidates or assets;
exit 1 = missing/corrupt inputs. Never send this output to a public repository.
"""
from __future__ import annotations

import argparse
import json
import sys

from certpassly.media_prep.replay_audit import run_private_media_replay
from certpassly.media_prep.errors import MediaPrepError


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",required=True,help="PRIVATE media-prep-v1 config")
    p.add_argument("--expected-source-assets",type=int,required=True,
                   help="Independently pinned original asset count")
    p.add_argument("--expected-image-questions",type=int,required=True,
                   help="Independently pinned image-requiring question count")
    p.add_argument("--gallery-folder",default="builder-replay",
                   help="One safe new folder INSIDE output.private_dir")
    a=p.parse_args(argv)
    try:
        r=run_private_media_replay(
            a.config,expected_source_assets=a.expected_source_assets,
            expected_image_questions=a.expected_image_questions,
            gallery_folder=a.gallery_folder)
        safe_summary={k:r[k] for k in (
            "exam_code","expected_source_assets","observed_source_assets",
            "expected_image_questions","observed_image_questions",
            "gallery_count","status","independent_verifier_status",
            "site_ui_status","human_approval_status",
            "ready_exams_promotion_allowed","publication_allowed")}
        safe_summary["issue_count"]=len(r["issues"])
        print(json.dumps(safe_summary,indent=2,sort_keys=True))
        return 0 if r["status"]=="MACHINE_REPLAY_COMPLETE_HUMAN_PENDING" else 2
    except (MediaPrepError,ValueError,OSError,KeyError,TypeError) as exc:
        print(f"PRIVATE AUDIT ERROR: {type(exc).__name__}: {exc}",file=sys.stderr)
        return 1


if __name__=="__main__":
    sys.exit(main())
