# Canonical conversation-history archiving: private, append-only

Read this guide before every CertPassly AI-session handover. This does not install automatic ChatGPT logging, access invisible conversations, or train model weights. It saves the information genuinely available to the operator with traceable provenance.

## The two locations for ONE master

- ChatGPT Library master: /CertPassly/Conversation Archives/certpassly_conversation_context_2026-11-12.json
- Private GitHub mirror: mathorax1-hue/raw-exam/docs/conversation-history/certpassly_conversation_context_2026-11-12.json
- Public skill: mathorax1-hue/certpassly-exam-skill. Only generic code, synthetic fixtures and sanitized instructions are permitted here.

The private master was updated to Library version 3 on 2026-11-12 and byte-identically mirrored to private raw-exam at commit feb0cf502f55729636b74fe7ea1ad9befaade68f. Verified blob SHA-1: 68ead2041581e4fa02017f34f2a4c2bef1528d2b. Original JSON SHA-256: 61deda93b827efd50421a7f5bfd9369dadcaec78c8fef0ae3da515e21a73df7b. These are checkpoint hashes; compare live files after future changes.

The master retains an embedded 3MB-plus private workflow evidence package and prior accessible conversation summaries. It is NOT a verbatim account-wide ChatGPT export; some historical voice turns were marked skipped and are inaccessible. Never invent any unavailable turn or overstate completeness.

## Required operator/AI behavior

1. Read the current existing private history JSON and raw-exam/docs/AI-SESSION-HANDOVER.md, plus public skill AGENTS.md, SKILL.md, docs/AI-SESSION-RECOVERY.md and knowledge/ENGINEERING-HISTORY.md.
2. Search tool-registry.json before writing new utilities. Put tested, generic scripts and their synthetic tests in the PUBLIC canonical skill, not in a scratch folder. Keep real original exam PDFs, question text, answers, screenshots, source snapshots and any personal/private conversation history in PRIVATE raw-exam only.
3. Capture confirmed actions: user and assistant messages actually available, exact file and command paths, decisions, failure cause, fix, CI run, commit SHA, source-proof URL/SHA, remaining questions, review blockers and next steps. Label exact quotations as verbatim and other descriptions as summaries. Label inaccessible turns as unavailable.
4. Append new events to the SAME private master JSON using the reusable updater below. Do not reset older entries, discard the original embedded source archive, or create duplicate conflicting masters.
5. Save the same master back into private raw-exam; verify the git commit and blob SHA. If ChatGPT Library is writable, independently overwrite the SAME Library file and read back its version/size/hash. GitHub does not automatically sync ChatGPT Library, or vice versa.
6. Continue item-specific review JSON in raw-exam/exams/AB-900/evidence/active-question-review-ledger.json as a SEPARATE record. Never alter the original owner PDF or counterfeit reviewer approvals.
7. Do not claim global background archiving without a real deployed authorization and verification. This protocol is explicitly manual.

## Generic tool and event schema

The script is scripts/append_conversation_history.py and its synthetic tests are tests/test_append_conversation_history.py. It requires only Python 3.11+ standard library; the public tool registry indexes it. It previews by default, and --apply atomically updates the existing private master file only. It prevents duplicate IDs, credential-like text, unsourced event claims and release-review self-approval. It does not fetch earlier chats by itself.

An operator prepares the event batch in a private temporary workspace:

    {
      "batch_source": "authorized accessible conversation or export, date and scope",
      "events": [
        {
          "id": "20261112.session1.turn001",
          "role": "user",
          "origin": "visible_chat",
          "source_reference": "exact visible turn or authorized export ref",
          "verbatim": true,
          "text": "SYNTHETIC EXAMPLE ONLY"
        },
        {
          "id": "20261112.session1.event002",
          "role": "assistant",
          "origin": "manual_summary",
          "source_reference": "checked private commit or run",
          "verbatim": false,
          "text": "SYNTHETIC SUMMARY"
        }
      ]
    }

Do not use verbatim=true for a summary. Include complete exact messages only if they are available. The script will not fill inaccessible gaps.

## Commands for future sessions

    git clone https://github.com/mathorax1-hue/certpassly-exam-skill.git
    cd certpassly-exam-skill
    python scripts/verify_tool_registry.py
    PYTHONPATH=src python -m unittest discover -s tests -v

    # Preview changes (read-only):
    python scripts/append_conversation_history.py --private-master /secure/raw-exam/docs/conversation-history/certpassly_conversation_context_2026-11-12.json --event-batch /secure/new-events.json

    # Explicit in-place append after reviewing source and privacy:
    python scripts/append_conversation_history.py --private-master /secure/raw-exam/docs/conversation-history/certpassly_conversation_context_2026-11-12.json --event-batch /secure/new-events.json --apply

    # From the PRIVATE raw-exam checkout:
    git status --short
    git add docs/conversation-history/certpassly_conversation_context_2026-11-12.json docs/AI-SESSION-HANDOVER.md
    git commit -m "archive: append confirmed conversation recovery checkpoint"
    git push origin main
    git rev-parse HEAD
    git hash-object docs/conversation-history/certpassly_conversation_context_2026-11-12.json
    sha256sum docs/conversation-history/certpassly_conversation_context_2026-11-12.json

On Windows, use Python via PowerShell and Get-FileHash -Algorithm SHA256 when needed. Do not paste tokens in chat or commits. A private CI run is not necessary for a master JSON-only append; prefer checked source and synthetic skill tests.

## Failures and claims to prevent

- A blocked Library approval dialog does NOT prove a saved update; check returned version and content.
- Missing GitHub repo write access is NOT fixed by checking out code through Actions.
- Green pipeline tests, page screenshots or private archive hashes do NOT prove every answer correct.
- Owner-highlighted answer keys are unverified until every selection and distractor is independently checked.
- Pixel matching is not semantic screenshot review; reviewer answer-reference files never belong in learner media.
- AI checking official URLs and quotes is not actual independent human review.
- A repo file provides explicit future context if read; it does not automatically retrain or permanently remember everything.
- Existing legacy runtime pins remain separate and must not be changed without approval and end-to-end compatibility proof.

Report exactly what was appended, original evidence integrity, Library version, GitHub SHA, missing turns and remaining blocks. Never promise that inaccessible conversations are fully archived.
