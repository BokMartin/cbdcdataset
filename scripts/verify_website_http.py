#!/usr/bin/env python3
"""Verify HTTPS Basic Auth and deployed static-file bodies without logging secrets."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import uuid


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    base_url = args.url.rstrip("/") + "/"
    source = Path(args.source).resolve()
    report_path = Path(args.report).resolve()
    password = getpass.getpass("Website password: ")
    cache_buster = uuid.uuid4().hex

    def request(url: str) -> urllib.request.Request:
        separator = "&" if "?" in url else "?"
        return urllib.request.Request(
            f"{url}{separator}verify={cache_buster}",
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        )

    unauthenticated_status = None
    try:
        with urllib.request.urlopen(request(base_url), timeout=30) as response:
            unauthenticated_status = response.status
    except urllib.error.HTTPError as exc:
        unauthenticated_status = exc.code

    password_manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    password_manager.add_password(None, base_url, args.user, password)
    opener = urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(password_manager))

    mismatches = []
    verified = []
    dynamic_paths = sorted(item for item in source.rglob("*.php") if item.is_file())
    static_paths = sorted(
        item for item in source.rglob("*")
        if item.is_file() and item.suffix.lower() != ".php"
    )
    for path in static_paths:
        relative = path.relative_to(source).as_posix()
        url = urllib.parse.urljoin(base_url, relative)
        try:
            with opener.open(request(url), timeout=60) as response:
                body = response.read()
                status = response.status
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            mismatches.append({"path": relative, "status": exc.code, "error": "http_error"})
            continue
        expected = path.read_bytes()
        if status != 200 or body != expected:
            mismatches.append({
                "path": relative,
                "status": status,
                "expected_sha256": sha256(expected),
                "actual_sha256": sha256(body),
            })
        else:
            verified.append({"path": relative, "bytes": len(body), "content_type": content_type})

    dynamic_routes = []
    for path in dynamic_paths:
        relative = path.relative_to(source).as_posix()
        url = urllib.parse.urljoin(base_url, relative)
        try:
            with opener.open(request(url), timeout=30) as response:
                dynamic_routes.append({
                    "path": relative,
                    "status": response.status,
                    "final_url": response.geturl(),
                    "redirect_ok": response.status == 200 and response.geturl().endswith("contribute.html"),
                })
        except urllib.error.HTTPError as exc:
            dynamic_routes.append({
                "path": relative,
                "status": exc.code,
                "final_url": exc.geturl(),
                "redirect_ok": False,
            })

    with opener.open(request(base_url), timeout=30) as response:
        root_body = response.read()
        root_status = response.status
        root_final_url = response.geturl()
        root_headers = {
            name: response.headers.get(name)
            for name in ("Date", "Last-Modified", "ETag", "Age", "Cache-Control", "Server", "Via", "X-Cache")
            if response.headers.get(name) is not None
        }
    markers = [b"113 documents", b"3,963 page units", b"6,949", b"human audit is still in progress"]
    missing_markers = [value.decode("ascii") for value in markers if value not in root_body]

    report = {
        "schema": "cbdc-v10.2e-live-http-verification-v1",
        "base_url": base_url,
        "root_final_url": root_final_url,
        "root_headers": root_headers,
        "basic_auth": {
            "unauthenticated_status": unauthenticated_status,
            "authenticated_status": root_status,
            "protected": unauthenticated_status == 401 and root_status == 200,
        },
        "verified_files": len(verified),
        "dynamic_routes": dynamic_routes,
        "mismatches": mismatches,
        "missing_headline_markers": missing_markers,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), **report}, indent=2))
    if (
        not report["basic_auth"]["protected"]
        or mismatches
        or missing_markers
        or any(not item["redirect_ok"] for item in dynamic_routes)
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
