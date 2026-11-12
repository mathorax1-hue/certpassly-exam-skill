#!/usr/bin/env python3
"""Capture a bounded official HTML/text page with exact-byte SHA-256 evidence.

No answer inference, automatic key correction, human approval or publication.
Use ONLY within a private workspace for real vendor pages. Standard library only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

MAX_BYTES = 8 * 1024 * 1024
SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,100}$")


def validate_url(url: str, allowed_hosts: list[str]) -> str:
    """Exact hostname/subdomain match, no credentials, URL IPs, non-HTTPS or ports."""
    if not isinstance(url, str) or any(ord(c) < 32 for c in url):
        raise ValueError("invalid URL")
    p = urlsplit(url)
    host = (p.hostname or "").lower().rstrip(".")
    allowed = [(h or "").strip().lower().rstrip(".") for h in allowed_hosts]
    if (p.scheme != "https" or not host or p.username or p.password
            or p.port not in (None, 443) or not allowed):
        raise ValueError("HTTPS URL, allowlisted host and no credentials required")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("IP-literal URL forbidden")
    if not any(host == h or host.endswith("." + h) for h in allowed if "." in h):
        raise ValueError("URL host is not on the official-vendor allowlist")
    return url


class SafeRedirects(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: list[str]):
        self.allowed_hosts = allowed_hosts
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "template", "svg", "noscript"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "template", "svg", "noscript"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def normalized_text(blob: bytes, content_type: str) -> str:
    text = blob.decode("utf-8-sig", errors="replace")
    if content_type == "text/html":
        parser = VisibleText()
        parser.feed(text)
        text = " ".join(parser.parts)
    return " ".join(text.split())


def receipt_from_bytes(url: str, blob: bytes, quote: str, allowed_hosts: list[str],
                       *, content_type: str = "text/html", mode: str = "downloaded") -> dict:
    validate_url(url, allowed_hosts)
    if content_type not in ("text/html", "text/plain"):
        raise ValueError("not an HTML or plain-text source")
    if not blob or len(blob) > MAX_BYTES:
        raise ValueError("source must be nonempty and within size limit")
    if not quote or not quote.strip() or len(quote) > 250:
        raise ValueError("a short verbatim proof quote is required")
    found = " ".join(quote.split()) in normalized_text(blob, content_type)
    if not found:
        raise ValueError("provided quote does not appear in source visible text")
    if mode not in ("downloaded", "local_file_unverified_origin"):
        raise ValueError("invalid capture mode")
    return {
        "source_url": url,
        "sha256": hashlib.sha256(blob).hexdigest(),
        "bytes": len(blob),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "content_type": content_type,
        "capture_mode": mode,
        "quote": quote,
        "quote_present_in_saved_content": found,
        "official_domain_allowlist": allowed_hosts,
        "answer_correctness_approved": False,
        "human_review_approved": False,
        "note": "Source existence and quote match only; not proof a selected option is correct.",
    }


def download(url: str, allowed_hosts: list[str], timeout: int = 20) -> tuple[bytes, str, str]:
    validate_url(url, allowed_hosts)
    opener = build_opener(SafeRedirects(allowed_hosts))
    req = Request(url, headers={"User-Agent": "CertPasslyEvidenceCapture/1.0", "Accept-Encoding": "identity"})
    with opener.open(req, timeout=timeout) as response:
        final_url = response.geturl()
        validate_url(final_url, allowed_hosts)
        content_type = response.headers.get_content_type().lower()
        if content_type not in ("text/html", "text/plain"):
            raise ValueError("source is not HTML or plain text")
        blob = response.read(MAX_BYTES + 1)
        if len(blob) > MAX_BYTES:
            raise ValueError("source exceeded size limit")
        return blob, content_type, final_url


def save_private_capture(output_dir: Path, identifier: str, blob: bytes, receipt: dict) -> Path:
    if not SAFE_ID.fullmatch(identifier):
        raise ValueError("unsafe evidence identifier")
    output_dir.mkdir(parents=True, exist_ok=True)
    extension = ".html" if receipt["content_type"] == "text/html" else ".txt"
    page = output_dir / (identifier + extension)
    manifest = output_dir / (identifier + ".source.json")
    if page.exists() or manifest.exists():
        raise ValueError("evidence record already exists; do not overwrite a snapshot")
    page.write_bytes(blob)
    receipt = {**receipt, "saved_content_path": page.name}
    manifest.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Current official vendor HTTPS page")
    parser.add_argument("--allow-host", action="append", required=True, help="Exact official hostname, repeatable")
    parser.add_argument("--id", required=True, help="Safe unique evidence ID")
    parser.add_argument("--quote", required=True, help="Short exact passage found in saved page visible text")
    parser.add_argument("--private-output-dir", type=Path, required=True)
    parser.add_argument("--offline-file", type=Path, help="Locally supplied bytes; does NOT assert download provenance")
    args = parser.parse_args(argv)
    try:
        validate_url(args.url, args.allow_host)
        if args.offline_file:
            blob = args.offline_file.read_bytes()
            content_type = "text/html" if args.offline_file.suffix.lower() in (".html", ".htm") else "text/plain"
            mode = "local_file_unverified_origin"
            final_url = args.url
        else:
            blob, content_type, final_url = download(args.url, args.allow_host)
            mode = "downloaded"
        receipt = receipt_from_bytes(final_url, blob, args.quote, args.allow_host,
                                     content_type=content_type, mode=mode)
        result = save_private_capture(args.private_output_dir, args.id, blob, receipt)
        print(json.dumps({"status": "captured_not_answer_approved", "receipt_path": str(result)}))
        return 0
    except (ValueError, OSError, HTTPError, URLError) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
