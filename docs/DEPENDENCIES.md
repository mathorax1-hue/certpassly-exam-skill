# Installation, dependency policy and reproducible execution

The shared skill keeps the **core Python 3.11+ toolchain dependency-free**. Added source-capture, option evidence, role reconciliation, ledger preflight, nested archive extractor and registry validator use the Python standard library.

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

System tools: git for versioning and pinned checkouts; Poppler pdfinfo/pdftoppm for PDF stages; gh optionally for authorized bounded dispatch; Docker and uv are optional. Use certpassly doctor to determine availability.

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
