#!/usr/bin/env python3
"""Phase 7: staging website importer acceptance gate. Fail-closed.

The real site importer must be inspected rather than guessed. This tool
is the executable form of the documented site-import acceptance gate: it
verifies an IMPORT RECEIPT produced by an actual CertPassly website
importer and staging environment against the verified V2 import package.

Without a receipt there is nothing to accept: a missing, partial or
fabricated receipt must BLOCK. The receipt must prove that the actual
importer (inspected, named, versioned) performed a staging dry-run
import (never a production publish) of the exact package bytes, that
every question rendered with its real interaction type, that answer
keys and answer-reference images were not accessible before submission
in BOTH the frontend payload and API responses, that the functional
modes (timer, navigator, review, feedback, timeout, scoring, partial
credit, trial limits, access policy, encrypted answer isolation) and
accessibility checks (keyboard, screen reader, mobile, WCAG 2.2 AA)
passed, that an atomic publish/rollback path with content version,
named human reviewer and exact package hash exists, and that the
evidence files (import log, screenshots) are present with matching
hashes.

This tool never claims a website import happened. A PASS means the
receipt is complete, internally consistent and consistent with the
package; the reviewer must still compare it with the actual staging
environment. It does not run a website, import anything, or prove the
receipt truthful - a fabricated truthful-looking receipt that passes
here is still fraud, which is why the receipt must reference inspectable
evidence files and a named human reviewer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SHA = re.compile(r'[0-9a-f]{64}')
URL = re.compile(r'^https?://[^\s]+$')
REQUIRED_SECTIONS = ('importer', 'run', 'package', 'questions',
                     'functional', 'publish', 'content_audit')
LIST_SECTIONS = ('evidence_files',)
FUNCTIONAL_KEYS = ('timer', 'navigator', 'review', 'practice_feedback',
                   'exam_feedback', 'timeout', 'partial_credit',
                   'trial_limits', 'access_policy',
                   'encrypted_answer_isolation')
ACCESSIBILITY_KEYS = ('keyboard', 'screen_reader', 'mobile', 'wcag_2_2_aa')
MODE_KEYS = ('study', 'timed', 'resume', 'retry', 'review')
QUESTION_FLAGS = ('relations_ok', 'media_loaded',
                  'answer_hidden_before_submission',
                  'scored_correct_key_matches')
AUDIT_KEYS = ('no_owner_pdf_exposed', 'no_raw_extracts_exposed',
              'no_secrets_exposed', 'only_authorized_content')
BOT_PATTERNS = re.compile(r'\b(ai|bot|gpt|automat\w*|copilot)\b', re.I)
ALLOWED_REVIEW_DECISIONS = ('approved_staging',)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def package_facts(package_path):
    package = json.loads(Path(package_path).read_text(encoding='utf-8'))
    questions = package.get('questions') or []
    if not isinstance(questions, list) or not questions:
        raise ValueError('package has no questions')
    type_counts = {}
    media_count = 0
    answer_count = 0
    keys = []
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError('package question is not an object')
        typ = str(question.get('type'))
        type_counts[typ] = type_counts.get(typ, 0) + 1
        media_count += len(((question.get('learner') or {})
                            .get('media')) or [])
        answer = question.get('answer') or {}
        if answer.get('answer_key') not in (None, '', [], {}):
            answer_count += 1
        keys.append(question.get('question_key'))
    return {
        'package': package,
        'question_count': len(questions),
        'type_counts': type_counts,
        'media_count': media_count,
        'answer_count': answer_count,
        'question_keys': keys,
        'types_by_key': {q.get('question_key'): str(q.get('type'))
                         for q in questions},
        'sha256': sha256_file(package_path),
    }


def verify(package_path, schema_path, receipt_path, evidence_root,
           report_path):
    facts = package_facts(package_path)
    schema_sha = sha256_file(schema_path)
    issues = []

    def issue(code, detail):
        issues.append({'code': code, 'detail': detail})

    if receipt_path is None or not Path(receipt_path).is_file():
        issue('missing_import_receipt',
              'no importer receipt exists; an actual website importer '
              'staging run must produce one before any acceptance')
        receipt = None
    else:
        try:
            receipt = json.loads(
                Path(receipt_path).read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            issue('receipt_unreadable', str(exc))
            receipt = None

    if receipt is not None:
        if not isinstance(receipt, dict):
            issue('receipt_not_object', 'receipt root must be an object')
            receipt = None

    if receipt is not None:
        unknown = set(receipt) - set(REQUIRED_SECTIONS) - set(LIST_SECTIONS)
        if unknown:
            issue('receipt_unknown_sections',
                  'unexpected receipt sections: %s'
                  % ', '.join(sorted(unknown)))
        for section in REQUIRED_SECTIONS:
            if not isinstance(receipt.get(section), dict):
                issue('receipt_missing_section',
                      'missing or invalid section: %s' % section)

        imp = receipt.get('importer') or {}
        if imp.get('inspected') is not True:
            issue('importer_not_inspected',
                  'the actual importer code/API must be inspected, '
                  'not guessed')
        for field in ('identity', 'source', 'staging_environment'):
            value = imp.get(field)
            if not isinstance(value, str) or not value.strip():
                issue('importer_field_missing', 'importer.%s' % field)
        if imp.get('import_format_version') != '2':
            issue('import_format_version', 'expected site format version 2')
        if imp.get('content_schema_sha256') != schema_sha:
            issue('schema_sha_mismatch',
                  'receipt schema sha does not match the pinned '
                  'canonical V2 schema')

        run = receipt.get('run') or {}
        if run.get('mode') != 'staging_dry_run':
            issue('run_mode_not_staging_dry_run',
                  'Phase 7 imports without publishing: only '
                  'staging_dry_run is acceptable, got %r' % run.get('mode'))
        if not isinstance(run.get('site_url'), str) \
                or not URL.match(run.get('site_url') or ''):
            issue('run_site_url_invalid', 'run.site_url')
        if not isinstance(run.get('release_id'), str) \
                or not run.get('release_id', '').strip():
            issue('run_release_id_missing', 'run.release_id')

        pkg = receipt.get('package') or {}
        if pkg.get('sha256') != facts['sha256']:
            issue('package_sha_mismatch',
                  'receipt package sha does not match the verified '
                  'package file')
        if pkg.get('question_count') != facts['question_count']:
            issue('question_count_mismatch',
                  'receipt says %r, package has %r'
                  % (pkg.get('question_count'), facts['question_count']))
        if pkg.get('type_counts') != facts['type_counts']:
            issue('type_counts_mismatch',
                  'receipt type counts differ from the package')
        if pkg.get('media_count') != facts['media_count']:
            issue('media_count_mismatch',
                  'receipt media count differs from the package')
        if pkg.get('answer_count') != facts['answer_count']:
            issue('answer_count_mismatch',
                  'receipt answer count differs from the package')

        questions = receipt.get('questions') or {}
        if set(questions) != set(facts['question_keys']):
            issue('question_key_set_mismatch',
                  'receipt question keys differ from the package')
        for key in facts['question_keys']:
            record = questions.get(key)
            if not isinstance(record, dict):
                issue('question_record_missing', key)
                continue
            if record.get('rendered_type') != facts['types_by_key'][key]:
                issue('rendered_type_mismatch', key)
            for flag in QUESTION_FLAGS:
                if record.get(flag) is not True:
                    issue('question_flag_failed', '%s.%s' % (key, flag))
            probes = record.get('answer_exposure_probes') or []
            if not isinstance(probes, list) \
                    or not {'frontend_payload', 'api_response'} <= set(probes):
                issue('answer_exposure_probes_missing', key)
            modes = record.get('functional_modes') or {}
            for mode in MODE_KEYS:
                if modes.get(mode) is not True:
                    issue('functional_mode_failed', '%s.%s' % (key, mode))
            access = record.get('accessibility') or {}
            for check in ACCESSIBILITY_KEYS:
                if access.get(check) is not True:
                    issue('accessibility_check_failed',
                          '%s.%s' % (key, check))

        functional = receipt.get('functional') or {}
        for check in FUNCTIONAL_KEYS:
            if functional.get(check) is not True:
                issue('functional_check_failed', check)

        publish = receipt.get('publish') or {}
        if publish.get('atomic_publish_rollback') is not True:
            issue('publish_rollback_missing',
                  'atomic publish/rollback path required')
        version = publish.get('content_version')
        if not isinstance(version, str) or not version.strip():
            issue('publish_content_version_missing', 'publish.content_version')
        reviewer = publish.get('reviewer_identity')
        if not isinstance(reviewer, str) or not reviewer.strip():
            issue('reviewer_identity_missing', 'publish.reviewer_identity')
        elif BOT_PATTERNS.search(reviewer):
            issue('reviewer_not_human',
                  'reviewer identity looks automated: %r' % reviewer)
        if publish.get('reviewer_decision') not in ALLOWED_REVIEW_DECISIONS:
            issue('reviewer_decision_invalid',
                  'publish.reviewer_decision must be %s'
                  % '/'.join(ALLOWED_REVIEW_DECISIONS))
        if publish.get('package_sha256') != facts['sha256']:
            issue('publish_package_sha_mismatch',
                  'publish.package_sha256 must equal the package sha')

        audit = receipt.get('content_audit') or {}
        for check in AUDIT_KEYS:
            if audit.get(check) is not True:
                issue('content_audit_failed', check)

        evidence = receipt.get('evidence_files') or []
        if not isinstance(evidence, list) or not evidence:
            issue('evidence_files_missing',
                  'import log and screenshot evidence required')
        else:
            root = Path(evidence_root) if evidence_root else \
                Path(receipt_path).resolve().parent
            for entry in evidence:
                if not isinstance(entry, dict):
                    issue('evidence_entry_invalid', repr(entry)[:60])
                    continue
                rel = entry.get('path')
                claimed = entry.get('sha256')
                if not isinstance(rel, str) or not rel \
                        or Path(rel).is_absolute():
                    issue('evidence_path_invalid', repr(rel)[:60])
                    continue
                if not isinstance(claimed, str) or not SHA.fullmatch(claimed):
                    issue('evidence_sha_invalid', rel)
                    continue
                path = (root / rel).resolve()
                if not path.is_relative_to(root.resolve()) \
                        or not path.is_file():
                    issue('evidence_file_missing', rel)
                    continue
                if sha256_file(path) != claimed:
                    issue('evidence_sha_mismatch', rel)

    passed = not issues
    report = {
        'status': 'PHASE7_IMPORTER_ACCEPTANCE_%s'
                  % ('PASS' if passed else 'BLOCKED'),
        'package_sha256': facts['sha256'],
        'pinned_schema_sha256': schema_sha,
        'receipt_present': receipt is not None,
        'package_facts': {k: facts[k] for k in
                          ('question_count', 'type_counts', 'media_count',
                           'answer_count')},
        'issues': issues,
        'limits': [
            'A PASS verifies the receipt only: complete, internally '
            'consistent and consistent with the package bytes',
            'The receipt must come from the actual inspected website '
            'importer and staging environment; this tool cannot prove '
            'a receipt truthful',
            'Phase 7 imports without publishing; any production '
            'publish claim fails this gate',
        ],
    }
    if report_path:
        out = Path(report_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                       + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True,
                        help='the verified site V2 import package')
    parser.add_argument('--schema', required=True,
                        help='the pinned canonical V2 question schema')
    parser.add_argument('--receipt',
                        help='import receipt from the actual importer; '
                             'omit to record the blocked state')
    parser.add_argument('--evidence-root',
                        help='directory holding the receipt evidence files')
    parser.add_argument('--report', required=True)
    args = parser.parse_args(argv)
    report = verify(args.package, args.schema, args.receipt,
                    args.evidence_root, args.report)
    print(json.dumps({'status': report['status'],
                      'issue_count': len(report['issues']),
                      'receipt_present': report['receipt_present']}))
    return 0 if report['status'].endswith('PASS') else 1


if __name__ == '__main__':
    sys.exit(main())
