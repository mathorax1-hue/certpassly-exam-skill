# Read-only CertPassly MCP server

Install optional dependency `pip install -e '.[mcp]'` and launch with `certpassly-mcp` from the skill repository root. This runs a local **stdio** MCP server. Integrating it into a specific ChatGPT/Claude/VS Code client is a separate, user-authorized configuration step.

Current tools:

- `environment_doctor`: installed tooling report.
- `checkpoint_status`: local pipeline completion report.
- `evidence_status(relative_json_path)`: structural blockers for a JSON document inside the current working directory.

Design policy: no arbitrary subprocess execution from MCP, no GitHub Actions dispatch, no credential reads, no mutation, and no release approval. An eventual authenticated control server would expose an allowlisted `start_exam`, `job_status`, `retry_stage`, and `request_review` with per-repository permissions, idempotency keys, auditing and an independent human-approval workflow.

The optional `mcp` dependency is not installed or exercised by baseline public CI. Before deploying, add and pin an MCP integration test in a controlled environment.
