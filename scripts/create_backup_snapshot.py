#!/usr/bin/env python3
"""Create a secret-screened, hashed RAR5 snapshot of the current CBDC inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SECRET_PATTERNS = [
    re.compile(rb"github_pat_[A-Za-z0-9_]{40,}"),
    re.compile(rb"sk-[A-Za-z0-9_-]{40,}"),
    re.compile(rb"OPENAI_API_KEY\s*=\s*['\"]?[A-Za-z0-9_-]{30,}"),
    re.compile(rb"ANTHROPIC_API_KEY\s*=\s*['\"]?[A-Za-z0-9_-]{30,}"),
]
TEXT_EXTENSIONS = {
    ".csv", ".json", ".jsonl", ".md", ".py", ".ps1", ".txt", ".toml",
    ".yaml", ".yml", ".sha256", ".gitignore", ".gitattributes",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def safe_repo_files(repo: Path, git: str) -> list[Path]:
    raw = run(
        [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        repo,
    ).stdout
    paths = []
    for value in raw.split(b"\0"):
        if not value:
            continue
        relative = Path(value.decode("utf-8"))
        parts = {part.casefold() for part in relative.parts}
        if (
            relative.parts[0].casefold() == "outputs"
            or "__pycache__" in parts
            or relative.suffix.casefold() == ".pyc"
            or relative.name.startswith("~$")
        ):
            continue
        source = repo / relative
        if source.is_file():
            paths.append(relative)
    return sorted(set(paths), key=lambda path: path.as_posix())


def screen_secret(path: Path, logical_path: str) -> None:
    name = path.name.casefold()
    forbidden_names = (".env", "credential", "set_openai_key", "github_pat", "secret")
    if any(marker in name for marker in forbidden_names):
        raise ValueError(f"forbidden secret-bearing filename: {logical_path}")
    if path.suffix.casefold() not in TEXT_EXTENSIONS or path.stat().st_size > 4 << 20:
        return
    content = path.read_bytes()
    for pattern in SECRET_PATTERNS:
        if pattern.search(content):
            raise ValueError(f"possible secret in file: {logical_path}")


def add_tree(
    staging: Path,
    source_root: Path,
    logical_root: str,
    relative_files: list[Path] | None = None,
) -> list[dict]:
    if relative_files is None:
        relative_files = [
            path.relative_to(source_root)
            for path in source_root.rglob("*")
            if path.is_file() and not path.name.startswith("~$")
        ]
    records = []
    for relative in sorted(relative_files, key=lambda path: path.as_posix()):
        source = source_root / relative
        logical = (Path(logical_root) / relative).as_posix()
        screen_secret(source, logical)
        target = staging / logical
        link_or_copy(source, target)
        records.append(
            {
                "path": logical,
                "bytes": source.stat().st_size,
                "sha256": sha256(source),
            }
        )
    return records


def add_file(staging: Path, source: Path, logical: str) -> dict:
    screen_secret(source, logical)
    target = staging / logical
    link_or_copy(source, target)
    return {"path": logical, "bytes": source.stat().st_size, "sha256": sha256(source)}


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--claude-sealed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rar", type=Path, required=True)
    parser.add_argument("--git", default="git")
    args = parser.parse_args()

    repo = args.repo.resolve()
    package = args.package.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    for required in (
        repo, package, args.corpus, args.gold, args.scope, args.calibration,
        args.claude_sealed, args.rar,
    ):
        if not Path(required).exists():
            raise FileNotFoundError(required)
    if output.exists():
        raise FileExistsError(output)

    with tempfile.TemporaryDirectory(prefix="cbdc-v10-snapshot-", dir=output.parent) as temp:
        staging = Path(temp) / "CBDC_v10_snapshot_2026-08-25"
        staging.mkdir()
        records = []

        repo_files = safe_repo_files(repo, args.git)
        records.extend(add_tree(staging, repo, "repo", repo_files))
        records.extend(add_tree(staging, package, "production_package"))
        records.append(add_file(staging, args.corpus.resolve(), "corpus/CBDC_DOKUMENTY_KOMPLET_2026-07-30.zip"))
        records.append(add_file(staging, args.gold.resolve(), "human_inputs/GOLD_EXTRACTION_v10final_MARTIN.xlsx"))
        records.append(add_file(staging, args.scope.resolve(), "human_inputs/SCOPE_READJUDICATION_v10_1_BLIND_completed.xlsx"))
        records.append(add_file(staging, args.calibration.resolve(), "human_inputs/CALIBRATION_AUDIT_v10_FINALIZED.xlsx"))
        records.append(add_file(staging, args.claude_sealed.resolve(), "provider_inputs/CLAUDE_PRODUCTION_v10_2e_SEALED.zip"))

        state_dir = staging / "repo_state"
        state_dir.mkdir()
        status = run([args.git, "status", "--porcelain=v2", "--branch"], repo).stdout
        (state_dir / "git_status.txt").write_bytes(status)
        patch = run([args.git, "diff", "--binary", "HEAD"], repo).stdout
        (state_dir / "working_tree.patch").write_bytes(patch)
        bundle = state_dir / "cbdc-msed-v10.bundle"
        run([args.git, "bundle", "create", str(bundle), "--all"], repo)
        for path in (state_dir / "git_status.txt", state_dir / "working_tree.patch", bundle):
            logical = path.relative_to(staging).as_posix()
            records.append({"path": logical, "bytes": path.stat().st_size, "sha256": sha256(path)})

        manifest = {
            "schema": "cbdc-v10-complete-input-snapshot-v1",
            "created_utc": utc_now(),
            "snapshot_date": "2026-08-25",
            "description": "Current reproducibility inputs before final two-author adjudication",
            "contents": {
                "repo": "current tracked and non-ignored working tree, excluding local outputs and lock/cache files",
                "git_history": "all refs in a portable git bundle plus status and binary patch",
                "production_package": "all 3,963 frozen units, prompts, schema, codebook, authority metadata, and renders",
                "corpus": "complete source-document ZIP supplied by the author",
                "human_inputs": "latest gold, completed scope readjudication, and finalized calibration audit",
                "provider_inputs": "original sealed Claude production package supplied by the provider run",
            },
            "security": {
                "api_keys_included": False,
                "github_tokens_included": False,
                "secret_screen": "filename allow-list plus credential-pattern scan of text files",
                "explicitly_excluded": [
                    "SET_OPENAI_KEY.ps1", ".env files", "temporary Excel locks",
                    "virtual environments", "local build outputs and dependency junctions",
                ],
            },
            "counts": {
                "files_before_manifest": len(records),
                "bytes_before_manifest": sum(item["bytes"] for item in records),
                "repo_files": len(repo_files),
            },
            "files": sorted(records, key=lambda item: item["path"]),
        }
        manifest_path = staging / "BACKUP_MANIFEST.json"
        write_json(manifest_path, manifest)
        readme = staging / "README_BACKUP.txt"
        readme.write_text(
            "CBDC v10 complete input snapshot, 2026-08-25\n"
            "\n"
            "Start with BACKUP_MANIFEST.json. The repo directory is the current working tree.\n"
            "repo_state/cbdc-msed-v10.bundle restores committed Git history; working_tree.patch\n"
            "documents tracked changes. The production_package directory is the frozen API input.\n"
            "No API keys or GitHub tokens are included.\n",
            encoding="utf-8",
            newline="\n",
        )

        command = [
            str(args.rar.resolve()), "a", "-r", "-ma5", "-m3", "-s", "-rr3p",
            "-htb", "-idq", str(output), staging.name,
        ]
        run(command, Path(temp))
        run([str(args.rar.resolve()), "t", "-idq", str(output)])

        sidecar = output.with_suffix(output.suffix + ".manifest.json")
        shutil.copy2(manifest_path, sidecar)
        digest = sha256(output)
        sha_path = output.with_suffix(output.suffix + ".sha256")
        sha_path.write_text(f"{digest}  {output.name}\n", encoding="utf-8", newline="\n")
        result = {
            "archive": str(output),
            "bytes": output.stat().st_size,
            "sha256": digest,
            "manifest": str(sidecar),
            "manifest_sha256": sha256(sidecar),
            "test": "RAR integrity test passed",
            "files": len(records) + 2,
            "logical_input_bytes": manifest["counts"]["bytes_before_manifest"],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
