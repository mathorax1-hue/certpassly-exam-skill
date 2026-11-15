#!/usr/bin/env python3
"""Fail-closed, independent CertPassly site-format V2 exam evidence gate.

No source PDF, answer key, question stem or option text is written to reports.
Use on a private runner. This does NOT verify semantic correctness, live website
security, source image fidelity, or independently prove answer truth.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HTML = re.compile(r"<\s*(?:[a-zA-Z!/]|\?)|javascript\s*:|data\s*:\s*text/html", re.I)
LEAK = {"answer_key", "correct_option_ids", "correct_answer", "is_correct",
        "server_only_answer_key", "option_rationales", "partial_credit"}
VALID_STATUS = {"owner_key", "researched_official", "researched_unverified", "answer_not_found"}
PASS_STATUS = {"owner_key", "researched_official"}
ALLOWED_EVIDENCE = {"source_sha256", "source_question_count", "questions"}
PROOF_KINDS = ("source", "interaction", "answer_mapping", "visual")

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def traverse(value, prefix="$"):
    if isinstance(value, dict):
        yield prefix, value
        for key, item in value.items():
            yield from traverse(item, prefix + "." + str(key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from traverse(item, prefix + "[" + str(i) + "]")
    else:
        yield prefix, value

def verify(exam_path, schema_path, registry_path, evidence_path, source_path=None, proof_root=None):
    # Fail closed when schema engine is unavailable.
    try:
        from jsonschema import Draft202012Validator
    except ImportError as e:
        raise RuntimeError("Install jsonschema: python -m pip install jsonschema") from e
    exam = json.loads(Path(exam_path).read_text(encoding="utf-8"))
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    issues = []
    proof_root = Path(proof_root).resolve() if proof_root is not None else Path(evidence_path).resolve().parent
    def issue(code, where, key=None):
        issues.append({"code": code, "path": where, **({"question_key": key} if key else {})})
    Draft202012Validator.check_schema(schema)
    for err in Draft202012Validator(schema).iter_errors(exam):
        issue("schema_invalid", "$" + "".join("["+str(x)+"]" for x in err.absolute_path))
    for path, obj in traverse(exam):
        if isinstance(obj, str) and HTML.search(obj):
            issue("html_or_script", path)
    questions = exam.get("questions") if isinstance(exam, dict) else None
    questions = questions if isinstance(questions, list) else []
    if not questions: issue("no_questions", "$.questions")
    types = registry.get("types", {})
    if not isinstance(types, dict): types = {}
    if set(evidence) - ALLOWED_EVIDENCE: issue("unrecognized_evidence_fields", "$evidence")
    source_count = evidence.get("source_question_count")
    if type(source_count) is not int or source_count < 1:
        issue("invalid_source_count", "$evidence.source_question_count")
    if len(questions) != source_count:
        issue("source_count_mismatch", "$.questions")
    source_sha = evidence.get("source_sha256")
    if not isinstance(source_sha, str) or not re.fullmatch("[0-9a-f]{64}", source_sha):
        issue("invalid_source_sha256", "$evidence.source_sha256")
    if source_path is None:
        issue("missing_source_file", "$source")
    else:
        try:
            if digest(source_path) != source_sha:
                issue("source_sha256_mismatch", "$source")
        except OSError:
            issue("source_file_unreadable", "$source")
    ev = evidence.get("questions")
    ev = ev if isinstance(ev, dict) else {}
    if len(ev) != len(questions): issue("evidence_count_mismatch", "$evidence.questions")
    seen = set()
    summary = {"questions": len(questions), "held": 0, "type_counts": {}}
    for i, q in enumerate(questions):
        p = f"$.questions[{i}]"
        if not isinstance(q, dict):
            issue("invalid_question", p); continue
        key = q.get("question_key")
        if not isinstance(key, str) or not key.strip():
            issue("invalid_question_key", p); continue
        if key in seen: issue("duplicate_question_key", p, key)
        seen.add(key)
        kind = q.get("type")
        summary["type_counts"][str(kind)] = summary["type_counts"].get(str(kind), 0) + 1
        if kind not in types:
            issue("unsupported_type", p + ".type", key)
        elif types[kind].get("publishable") is not True:
            issue("type_not_publishable", p + ".type", key)
        learner = q.get("learner", {})
        for subpath, node in traverse(learner, p + ".learner"):
            if isinstance(node, dict):
                for field in LEAK:
                    if field in node: issue("answer_leak", subpath + "." + field, key)
        ans = q.get("answer", {})
        ans = ans if isinstance(ans, dict) else {}
        status = ans.get("status")
        if status not in VALID_STATUS: issue("invalid_answer_status", p + ".answer.status", key)
        if status == "answer_not_found" and ans.get("scoring_excluded") is not True:
            issue("unscored_answer_not_excluded", p + ".answer", key)
        if status not in PASS_STATUS or ans.get("reviewer_needed") is True or ans.get("scoring_excluded") is True:
            issue("answer_not_release_eligible", p + ".answer", key)
        record = ev.get(key)
        if not isinstance(record, dict):
            issue("missing_source_evidence", "$evidence.questions." + key, key)
        else:
            if record.get("source_verified") is not True: issue("source_not_verified", "$evidence.questions." + key, key)
            if record.get("interaction_verified") is not True: issue("interaction_not_verified", "$evidence.questions." + key, key)
            if record.get("answer_mapping_verified") is not True: issue("answer_mapping_not_verified", "$evidence.questions." + key, key)
            if record.get("visual_verified") is not True: issue("visual_not_verified", "$evidence.questions." + key, key)
            proof = record.get("proof")
            proof = proof if isinstance(proof, dict) else {}
            for kind in PROOF_KINDS:
                entry = proof.get(kind)
                at = "$evidence.questions." + key + ".proof." + kind
                if not isinstance(entry, dict):
                    issue("missing_proof", at, key)
                    continue
                rel = entry.get("path")
                claimed = entry.get("sha256")
                if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or "\\\\" in rel:
                    issue("invalid_proof_path", at, key)
                    continue
                if not isinstance(claimed, str) or not re.fullmatch("[0-9a-f]{64}", claimed):
                    issue("invalid_proof_sha256", at, key)
                    continue
                fp = (proof_root / rel).resolve()
                if not fp.is_relative_to(proof_root) or not fp.is_file():
                    issue("proof_file_missing_or_unsafe", at, key)
                    continue
                if digest(fp) != claimed:
                    issue("proof_sha256_mismatch", at, key)
            if record.get("held") is True:
                summary["held"] += 1
                issue("question_held", "$evidence.questions." + key, key)
    for key in ev:
        if key not in seen: issue("orphan_source_evidence", "$evidence.questions", key)
    return {"status": "PASS" if not issues else "BLOCKED",
            "release_eligible": not issues,
            "exam_sha256": digest(exam_path),
            "schema_sha256": digest(schema_path),
            "registry_sha256": digest(registry_path),
            "evidence_sha256": digest(evidence_path),
            "source_sha256": source_sha,
            "summary": summary,
            "issues": sorted(issues, key=lambda x:(x["code"], x["path"], x.get("question_key",""))),
            "limits": ["Not a source-PDF semantic comparison", "Not a live site importer/browser/security test",
                       "Evidence booleans require independently documented review; not self-proving"]}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--exam", required=True)
    p.add_argument("--schema", required=True)
    p.add_argument("--registry", required=True)
    p.add_argument("--evidence", required=True)
    p.add_argument("--source-pdf", required=True, help="Immutable original source PDF, hashed against evidence")
    p.add_argument("--proof-root", help="Private root directory containing per-question evidence files")
    p.add_argument("--report", required=True)
    args = p.parse_args()
    try:
        result = verify(args.exam,args.schema,args.registry,args.evidence,args.source_pdf,args.proof_root)
    except (OSError, ValueError, RuntimeError, TypeError) as e:
        result = {"status":"BLOCKED","release_eligible":False,
                  "issues":[{"code":"gate_execution_failed","error_type":type(e).__name__}]}
    out=Path(args.report);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"report":str(out),
                      "issue_count":len(result["issues"])}))
    return 0 if result["release_eligible"] else 1

if __name__=="__main__":
    sys.exit(main())
