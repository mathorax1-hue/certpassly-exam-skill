#!/usr/bin/env python3
"""Check our verifier against pinned upstream *actual* V2 example files.

All source files created here are synthetic. No private exam material is used.
"""
import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from scripts.verify_site_v2_release_gate import verify

def sha(data):
    return hashlib.sha256(data).hexdigest()

def main(argv):
    if len(argv) != 2:
        raise SystemExit("Usage: python scripts/test_pinned_site_v2_contract.py PINNED-UPSTREAM-DIR")
    upstream=Path(argv[1])
    v2=upstream/"reference/site-format/v2"
    schema=v2/"question.schema.json"
    registry=v2/"question_types.json"
    examples=sorted((v2/"examples").glob("valid-*.json"))
    if len(examples) < 8:
        raise SystemExit("BLOCKED: fewer than eight upstream example files")
    failures=[]
    outcomes=[]
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        source=root/"synthetic-source.pdf"
        source.write_bytes(b"NOT A REAL PDF - SIMULATED INTEGRATION INPUT")
        proof=root/"synthetic-proof.json"
        proof.write_text('{"result":"synthetic_only"}')
        for example in examples:
            document=json.loads(example.read_text())
            original=copy.deepcopy(document)
            content_path=root/"exam.json"
            content_path.write_text(json.dumps(document))
            records={}
            for question in document["questions"]:
                records[question["question_key"]]={
                    "source_verified":True,"interaction_verified":True,
                    "answer_mapping_verified":True,"visual_verified":True,
                    "held":False,
                    "proof":{kind:{"path":"synthetic-proof.json","sha256":sha(proof.read_bytes())}
                             for kind in ("source","interaction","answer_mapping","visual")}
                }
            ev={"source_sha256":sha(source.read_bytes()),"source_question_count":len(document["questions"]),"questions":records}
            evidence=root/"evidence.json"
            evidence.write_text(json.dumps(ev))
            result=verify(content_path,schema,registry,evidence,source,root)
            errs=[x["code"] for x in result["issues"]]
            outcomes.append({"example":example.name,"status":result["status"],"codes":errs})
            if not result["candidate_validation_eligible"]:
                failures.append("valid example failed: "+example.name+" "+str(errs))
            if result.get("final_exam_release_eligible") is not False:
                failures.append("Phase 6 candidate pass incorrectly authorized final release: "+example.name)
            if "release_eligible" in result:
                failures.append("ambiguous legacy release_eligible field still emitted: "+example.name)
            # Negative mutation: invalid injected HTML must always be rejected.
            document["exam"]["name"]="<script>bad</script>"
            content_path.write_text(json.dumps(document))
            bad=verify(content_path,schema,registry,evidence,source,root)
            if "html_or_script" not in [x["code"] for x in bad["issues"]]:
                failures.append("HTML mutation not rejected: "+example.name)
            if bad.get("candidate_validation_eligible") is not False or bad.get("final_exam_release_eligible") is not False:
                failures.append("blocked candidate reported an eligibility flag: "+example.name)
            if document is original:
                failures.append("unexpected identity")
    # Verify the canonical upstream package guard with the *technical V2*
    # isolation policy. Do not alter the guard or allow email in a V2 deliverable.
    import zipfile
    sys.path.insert(0, str((upstream / "scripts").resolve()))
    import package_guard as pg
    policy={"brand_denylist":[],"policy":{"contact_patterns":{
        "email":r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}"}}}
    policy_config={"package_exclude":[
        "questions.json","extracted/**","export/**","media/src/*"]}
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        stage=root/"staging"
        stage.mkdir()
        (stage/"extracted/items").mkdir(parents=True)
        (stage/"export").mkdir()
        (stage/"media/src").mkdir(parents=True)
        v2=stage/"AB-900.site-format.v2.json"
        v2.write_text('{"exam":{"exam_code":"SYN-001"},"questions":[]}')
        for name in ("questions.json","extracted/items/q081.json","export/fidelity.json"):
            (stage/name).write_text('{"private_example":"synthetic@sample.invalid"}')
        (stage/"media/src"/"source.jpg").write_bytes(b"not-a-real-image")
        excluded=pg.prepare(str(stage),policy,policy_config,log=lambda *_:None)
        excluded_set={v["path"] for v in excluded}
        if not {"questions.json","extracted/items/q081.json","export/fidelity.json","media/src/source.jpg"} <= excluded_set:
            failures.append("diagnostic content not fully excluded from technical V2 package")
        bundle=root/"technical-v2.zip"
        def write_zip():
            with zipfile.ZipFile(bundle,"w",zipfile.ZIP_DEFLATED) as z:
                for p in stage.rglob("*"):
                    if p.is_file(): z.write(p,p.relative_to(stage).as_posix())
        write_zip()
        clean=pg.scan_zip(str(bundle),policy)
        if clean["hits"]:
            failures.append("clean technical V2 package falsely failed")
        # Negative test: unsafe content in candidate-facing JSON remains forbidden.
        v2.write_text('{"exam":{"exam_code":"SYN-001"},"candidate":"synthetic@sample.invalid"}')
        write_zip()
        unsafe=pg.scan_zip(str(bundle),policy)
        if not unsafe["hits"]:
            failures.append("malicious V2 deliverable bypassed canonical package guard")
    packaging={"private_diagnostics_excluded":len(excluded_set),
               "clean_hits":len(clean["hits"]),"negative_deliverable_hits":len(unsafe["hits"])}
    print(json.dumps({"pinned_contract":str(upstream),"valid_exam_fixtures":len(examples),
                      "negative_html_mutations":len(examples),"failures":failures,
                      "packaging":packaging,"outcomes":outcomes},indent=2))
    return 1 if failures else 0

if __name__=="__main__":
    sys.exit(main(sys.argv))
