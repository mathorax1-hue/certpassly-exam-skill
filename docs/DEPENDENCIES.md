# Installation, dependency policy and reproducible execution

The shared skill keeps the **core Python 3.11+ toolchain dependency-free**. Added source-capture, offline receipt verifier, option evidence, role reconciliation, ledger preflight, nested archive extractor and registry validator use the Python standard library.

## Supported execution targets

- Linux GitHub Actions: ubuntu-24.04 with Python 3.11.
- Developer workstation: Python 3.11+, Git, standard command line.
- Windows: PowerShell and Python 3.11+. The Bash helper requires Git Bash or WSL.
- Public CI runs synthetic fixtures only. Original exams and snapshots stay private.

## Core installation

    python -m venv .venv

Activate the virtual environment and run:

    python -m pip install -e .
    certpassly doctor --json
    python scripts/verify_tool_registry.py
    python -m unittest discover -s tests -v

Alternatively, from the repository root without installation:

    PYTHONPATH=src python -m certpassly.cli doctor --json

The syntax above works in a Unix shell. In PowerShell, assign PYTHONPATH with: $env:PYTHONPATH = "src"

## Optional dependencies (declared in pyproject.toml)

| Extra | Purpose | Install | Status |
| --- | --- | --- | --- |
| pdf | PyMuPDF PDF extraction and inspection | python -m pip install -e ".[pdf]" | Optional; not answer approval |
| visual | Pillow and OpenCV pixel comparison | python -m pip install -e ".[visual]" | Optional; not semantic verification |
| browser | Playwright for page rendering | python -m pip install -e ".[browser]" | Optional; browser install may be required |
| mcp | Read-only MCP diagnostic server | python -m pip install -e ".[mcp]" | Optional; no automatic ChatGPT connector |
| dev | pytest and Ruff | python -m pip install -e ".[dev]" | Optional; unittest needs no third party package |
| phase1 | Phase 1 PDF extraction toolkit (PyMuPDF, Pillow, numpy, jsonschema) | python -m pip install -e ".[phase1]" | Optional; strictly local, no release authority |

System tools: git for versioning and pinned checkouts; Poppler pdfinfo/pdftoppm for PDF stages; gh optionally for authorized bounded dispatch; Docker and uv are optional. Use certpassly doctor to determine availability.

## Phase 1 extraction toolkit dependencies (pinned ranges)

| Package | Allowed range | Why |
| --- | --- | --- |
| PyMuPDF | >=1.24,<2 | geometry/text/image pass (validated on 1.26.7) |
| Pillow | >=10,<13 | image decode, contact sheets |
| numpy | >=1.26,<3 | pixel comparisons |
| jsonschema | >=4.20,<5 | structured/v1 schema validation |

System prerequisites (not pip): Poppler `pdftohtml` (engine used by the pinned
external upstream extractor) and Tesseract (visual drafts). Git LFS only for
private repositories that store source PDFs in LFS. The upstream checkout stays
pinned at `13dea6bab662ab1c4bbf87017e912e519907c8bc` via
`scripts/bootstrap_upstream.sh`; it is an external read-only dependency and is
never vendored (its root has no confirmed redistributable LICENSE). Update
policy: dependency-range changes require a reviewed PR, registry/doc updates
and a full synthetic test run; never `pip install -U` unpinned in a working
environment. Install once per commit and reuse the venv/pip cache; see
[PHASE1-EXTRACTION.md](PHASE1-EXTRACTION.md#installation-once-per-commit-caching-and-reuse).

## Persistent developer environments and reusable installation (owner directive, 2026-11-12)

**Goal:** Install once when the environment is correct, then reuse it. Git tracks **source, manifests, commands, tests and provenance**, not a copied Python virtual environment or system binaries. The developer's existing secure workstation/VM/server is the primary build and synthetic-test environment. GitHub Actions is optional for synthetic corroboration; protected checks remain required where the release contract calls for them.

### First run versus every later session

1. **First run**: clone the public skill, create a Python 3.11+ virtual environment in that checkout, install the editable package with only the extras actually needed, run \`certpassly doctor --json\`, registry verification and synthetic tests. Install Git/Poppler/Tesseract only if absent. Record interpreter version, package versions, OS and exact Git SHA.
2. **Later sessions**: return to the same checkout and activate the **existing** \`.venv\`. Do not delete/recreate it. Run \`certpassly doctor --json\` (if available), \`python scripts/verify_tool_registry.py\`, and only the tests relevant to changed code, plus full synthetic tests before acceptance.
3. **Only repair what changed**: rerun \`python -m pip install -e .\` only when the package/dependency metadata or environment has changed, when a package is missing, or when verification fails. Source edits in an already editable checkout normally do not require reinstalling. Avoid unconditional \`pip install -U\` or switching to unreviewed latest upstream.
4. **Preserve package download caches locally**: pip maintains its own cache (inspect with \`python -m pip cache dir\`); \`uv\` may also cache interpreters/packages when installed. Reuse those trusted local caches without checking them into Git. Keep project virtual environments isolated, particularly the legacy upstream's dependencies versus this newer skill's optional extras.
5. **Retain the upstream checkout**: \`scripts/bootstrap_upstream.sh\` already downloads the approved legacy revision into an ignored \`vendor/\` location and refuses to overwrite an existing destination. Call it only when the checkout is absent. On later sessions inspect \`git -C vendor/certpassly-exam-pipeline rev-parse HEAD\` and confirm \`13dea6bab662ab1c4bbf87017e912e519907c8bc\`. If missing/wrong, stop and report; do not silently update or delete a checkout.
6. **Rebuild when necessary**: if OS, architecture, interpreter ABI, pinned dependency set, Python version or the reviewed upstream revision changes, create a **new** isolated environment and verify it. Never copy \`.venv\` from one incompatible machine to another to simulate reproducibility.
7. **Diagnose without leaking secrets**: record sanitized versions, \`python -m pip check\`, \`certpassly doctor --json\`, package/test results and manifest hashes. Do not publish an entire raw environment dump with tokens, home paths, private package indexes, user names or private URL credentials.

### Useful session commands (Bash; existing compatible checkout)

\`\`\`bash
cd /path/to/certpassly-exam-skill
source .venv/bin/activate                    # create only if absent
python --version
python -m pip check                          # inspect dependency consistency
certpassly doctor --json
python scripts/verify_tool_registry.py
PYTHONPATH=src python -m unittest discover -s tests -v  # full pre-merge check
git -C vendor/certpassly-exam-pipeline rev-parse HEAD    # if pinned checkout exists
\`\`\`

PowerShell: \`.\.venv\Scripts\Activate.ps1\`; use \`$env:PYTHONPATH="src"\` for tests. If a virtual environment is not present, follow **Core installation** above. Keep shell activation paths and private workspaces outside public tracked output.

### Source-controlled reproducibility (what we retain in the public skill)

| Retain in this PUBLIC repository | Keep installed or cached locally (never commit) |
| --- | --- |
| Reusable \`scripts/\` and \`src/certpassly/\` implementations, reviewed with synthetic tests | \`.venv/\`, Python distributions, compiled wheels, \`__pycache__/\`, local \`uv\` / pip caches |
| \`pyproject.toml\` extras and reviewed package/version policies; an approved constraints/lock artifact **if later created and tested** | Third-party installed site-packages, browser binaries, OS packages, Docker images |
| \`config/tool-registry.json\`: command, owner, dependency and side-effect contract for every shared tool | Local \`vendor/\` checkout of the external proprietary runtime; do not vendor its source |
| \`config/repositories.json\` and reviewed upstream commit pins, bootstrap commands, synthetic fixtures and CI definitions | Original exam PDFs, answer keys, screenshots, private official-page captures, credentials, full local workspaces |
| \`docs/DEPENDENCIES.md\`, \`docs/TOOL-HUB.md\`, \`knowledge/ENGINEERING-HISTORY.md\` and sanitized installation failure/recovery notes | Secrets in \`.env\`, temporary output, proprietary packages and confidential logs |

The current \`pyproject.toml\` specifies dependency **ranges**, not a reviewed cross-platform lockfile. Never claim bit-for-bit reproducibility from ranges alone. Before creating a lock/constraints file, the developer must propose a scoped dependency change, compare existing manifests and registry, review licensing and security, run synthetic tests across supported targets, describe rollback, and request director/owner approval. Do not commit an unreviewed \`pip freeze\` from a personal workstation as a canonical lock.

### How the developer adds a reusable capability (no duplicate tools)

1. Search \`config/tool-registry.json\`, \`scripts/\`, \`src/certpassly/\`, the public \`exam\` processor, and \`docs/TOOL-HUB.md\` **before** writing anything.
2. Extend an existing tool where possible. Otherwise propose a reusable general-purpose implementation in this skill, with synthetic test(s), a registry entry, precise dependencies and known writes/side effects.
3. Add only necessary optional dependencies to \`pyproject.toml\`; **do not install all optional extras** by default. Keep the core standard-library-only when feasible.
4. Validate locally and preserve exact test commands/outcomes; then use owner-public synthetic CI only when warranted. Explain why a new dependency or script is needed instead of reusing a listed tool.
5. Keep private exam-specific configuration, evidence and generated artifacts in \`raw-exam\`; keep independent release validation in \`ready-exams\`. No public owner data, credentials, proprietary binary dumps or automatic promotion.
6. Record tested tool changes and troubleshooting in the tool registry, this file and sanitized engineering history; show commit and test evidence to the director in the private GitHub discussion before proposing private integration.

**Current task boundary:** This documents the reusable setup policy. It does **not** authorize the developer to alter runtime pins, introduce new dependency locks or bootstrap code, change Actions/secrets, publish or process real exams under a read-only audit order. Such work needs its own scoped developer order and review.

## Version and supply-chain rules

1. Python requirement is >=3.11. Prefer standard-library tooling for new core scripts.
2. Optional dependency ranges live in pyproject.toml. An exact dependency lockfile has **not yet** been reviewed or produced; do not claim lockfile reproducibility.
3. External legacy pipeline stays a separate Git checkout pinned to commit 13dea6bab662ab1c4bbf87017e912e519907c8bc in config/repositories.json and scripts/bootstrap_upstream.sh. The private raw workflow may still use that revision. It is a compatibility dependency, not the canonical new skill.
4. The former upstream repository lacked a visible root LICENSE at last review. Do not wholesale copy its code into this public repo without permission. Integrate through a pinned checkout or implement clean independent equivalents.
5. GitHub release credentials belong only in protected private settings. Never write PATs into config, repo files, logs, or public CI.
6. Review transitive dependencies, version changes, licenses, regression tests, and rollout before enabling additional packages.
7. Enabling visual, browser, PDF, or MCP extras does not confer approval or permit promotion.

## Dependency change checklist

For a new library, record why existing tools cannot perform the task, registry search performed, version constraints, package license, security review, Linux/Windows tests, workflow permissions, and rollback procedure. Update pyproject.toml, this guide and synthetic tests; adjust private code pins only when reviewed.

## Resource and privacy controls

Do not run the entire private exam catalog to test a script. Use public synthetic tests. Launch at most one deliberately selected private exam job when a complete verified batch warrants testing. The source-capture helper uses bounded downloads and an explicit allowlisted HTTPS hostname; original question images, answer keys and official page snapshots remain private.

## Current limitations

The shared repository is a skill-engineering foundation, not an independent human review service or live site importer. Complete release still requires original owner evidence, verified current official sources, every answer option and visual inspected, and independent proof and reviewer gates.
