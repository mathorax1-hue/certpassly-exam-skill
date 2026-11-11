"""Optional read-only MCP interface; install `.[mcp]` to enable.

This is NOT a privileged GitHub or release tool. Writes require explicitly
reviewed CLI operations and separate GitHub Actions permissions.
"""
from __future__ import annotations

from pathlib import Path

from .doctor import inspect
from .evidence import audit_file
from .pipeline import inside
from .checkpoints import Checkpoints


def serve():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise SystemExit("Install optional MCP dependency: pip install -e '.[mcp]'") from exc

    server = FastMCP("CertPassly Skill - Read Only")
    root = Path.cwd().resolve()

    @server.tool()
    def environment_doctor() -> dict:
        """Return installed tools and Python readiness (no secrets)."""
        return inspect()

    @server.tool()
    def checkpoint_status() -> dict:
        """Inspect local checkpoint progress in the current workspace."""
        db_path = inside(root, ".certpassly/checkpoints.sqlite3")
        if not db_path.is_file():
            return {"stages": [], "message": "No stages run yet"}
        with Checkpoints(db_path) as db:
            return {"stages": db.list()}

    @server.tool()
    def evidence_status(relative_json_path: str) -> dict:
        """Inspect local evidence structure; cannot approve a release."""
        p = inside(root, relative_json_path)
        if not p.is_file():
            return {"status": "blocked", "error": "File missing"}
        report = audit_file(p)
        return {"status": report["status"], "exam_code": report["exam_code"],
                "question_count": report["question_count"], "media_count": report["media_count"],
                "blocker_count": report["blocker_count"], "blockers": report["blockers"],
                "warning": report["warning"]}

    server.run(transport="stdio")


if __name__ == "__main__":
    serve()
