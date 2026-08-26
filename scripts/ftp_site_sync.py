#!/usr/bin/env python3
"""Back up, deploy, and verify a static site over explicit FTPS.

Credentials are read from a hidden terminal prompt and are never written to disk.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import ssl
from ftplib import CRLF, FTP_TLS, Error, error_perm


class CompatibleFTP_TLS(FTP_TLS):
    """FTP_TLS variant tolerant of shared hosts that omit TLS close_notify."""

    def _finish_data_tls(self, connection: object) -> None:
        if isinstance(connection, ssl.SSLSocket):
            try:
                connection.unwrap()
            except ssl.SSLError:
                # The complete payload has already been received. WEDOS closes
                # the data socket without close_notify, which is harmless here.
                pass

    def retrlines(self, cmd: str, callback=None) -> str:
        if callback is None:
            callback = print
        self.sendcmd("TYPE A")
        with self.transfercmd(cmd) as connection, connection.makefile(
            "r", encoding=self.encoding
        ) as stream:
            while True:
                line = stream.readline(self.maxline + 1)
                if len(line) > self.maxline:
                    raise Error(f"got more than {self.maxline} bytes")
                if not line:
                    break
                if line[-2:] == CRLF:
                    line = line[:-2]
                elif line[-1:] == "\n":
                    line = line[:-1]
                callback(line)
            self._finish_data_tls(connection)
        return self.voidresp()

    def retrbinary(self, cmd: str, callback, blocksize=8192, rest=None) -> str:
        self.voidcmd("TYPE I")
        with self.transfercmd(cmd, rest) as connection:
            while data := connection.recv(blocksize):
                callback(data)
            self._finish_data_tls(connection)
        return self.voidresp()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def connect(host: str, user: str) -> CompatibleFTP_TLS:
    password = getpass.getpass("FTP password: ")
    context = ssl.create_default_context()
    ftp = CompatibleFTP_TLS(context=context, timeout=60)
    ftp.connect(host, 21)
    ftp.login(user, password)
    # Keep credentials and control commands under TLS. The WEDOS shared-hosting
    # endpoint closes protected data sockets incorrectly, so public site files
    # use clear data channels (PROT C) for interoperability.
    ftp.prot_c()
    return ftp


def remote_path(root: str, relative: PurePosixPath | str = "") -> str:
    base = PurePosixPath(root)
    suffix = PurePosixPath(relative)
    return str(base / suffix) if str(suffix) != "." else str(base)


def entries(ftp: FTP_TLS, directory: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    try:
        # Some shared hosts implement MLSD but reject the optional OPTS MLST
        # command that ftplib sends when a facts list is supplied.
        for name, facts in ftp.mlsd(directory):
            if name not in {".", ".."}:
                result.append((name, facts.get("type", "file")))
        return sorted(result)
    except (error_perm, AttributeError):
        current = ftp.pwd()
        ftp.cwd(directory)
        names = ftp.nlst()
        for name in names:
            if name in {".", ".."}:
                continue
            kind = "file"
            try:
                ftp.cwd(name)
                ftp.cwd("..")
                kind = "dir"
            except error_perm:
                pass
            result.append((name, kind))
        ftp.cwd(current)
        return sorted(result)


def walk_remote(
    ftp: FTP_TLS, root: str, relative: PurePosixPath = PurePosixPath()
) -> tuple[list[PurePosixPath], list[PurePosixPath]]:
    directories: list[PurePosixPath] = []
    files: list[PurePosixPath] = []
    for name, kind in entries(ftp, remote_path(root, relative)):
        child = relative / name
        if kind in {"dir", "cdir", "pdir"}:
            directories.append(child)
            child_dirs, child_files = walk_remote(ftp, root, child)
            directories.extend(child_dirs)
            files.extend(child_files)
        else:
            files.append(child)
    return directories, files


def cmd_list(args: argparse.Namespace) -> None:
    with connect(args.host, args.user) as ftp:
        directories, files = walk_remote(ftp, args.remote_root)
        print(json.dumps({
            "remote_root": args.remote_root,
            "directories": [str(p) for p in directories],
            "files": [str(p) for p in files],
        }, indent=2, ensure_ascii=False))


def cmd_backup(args: argparse.Namespace) -> None:
    destination = Path(args.destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with connect(args.host, args.user) as ftp:
        directories, files = walk_remote(ftp, args.remote_root)
        for directory in directories:
            (destination / Path(*directory.parts)).mkdir(parents=True, exist_ok=True)
        manifest_files: list[dict[str, object]] = []
        for relative in files:
            local = destination / Path(*relative.parts)
            local.parent.mkdir(parents=True, exist_ok=True)
            with local.open("wb") as handle:
                ftp.retrbinary(f"RETR {remote_path(args.remote_root, relative)}", handle.write)
            manifest_files.append({
                "path": relative.as_posix(),
                "bytes": local.stat().st_size,
                "sha256": digest(local),
            })
    manifest = {
        "format": "cbdc-site-backup-v1",
        "remote_root": args.remote_root,
        "files": manifest_files,
    }
    (destination / "backup_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "destination": str(destination),
        "files": len(manifest_files),
        "bytes": sum(int(item["bytes"]) for item in manifest_files),
    }, indent=2))


def ensure_directory(ftp: FTP_TLS, directory: str) -> None:
    parts = PurePosixPath(directory).parts
    current = "/" if directory.startswith("/") else ftp.pwd()
    for part in parts:
        if part == "/":
            continue
        candidate = str(PurePosixPath(current) / part)
        try:
            ftp.mkd(candidate)
        except error_perm as exc:
            if not str(exc).startswith("550"):
                raise
        current = candidate


def cmd_deploy(args: argparse.Namespace) -> None:
    source = Path(args.source).resolve()
    if not source.is_dir():
        raise SystemExit(f"Source directory does not exist: {source}")
    allowed_roots = {
        PurePosixPath("/www"),
        PurePosixPath("/domains/cbdcdataset.org"),
    }
    if PurePosixPath(args.remote_root) not in allowed_roots:
        raise SystemExit("Refusing destructive mirror outside the approved CBDC website roots")

    preserve = {PurePosixPath(item) for item in args.preserve}
    local_files = {
        PurePosixPath(path.relative_to(source).as_posix()): path
        for path in source.rglob("*")
        if path.is_file()
    }
    local_directories = {
        PurePosixPath(path.relative_to(source).as_posix())
        for path in source.rglob("*")
        if path.is_dir()
    }

    with connect(args.host, args.user) as ftp:
        remote_directories, remote_files = walk_remote(ftp, args.remote_root)
        for relative in sorted(local_directories, key=lambda p: len(p.parts)):
            ensure_directory(ftp, remote_path(args.remote_root, relative))
        for relative, local in sorted(local_files.items(), key=lambda item: str(item[0])):
            ensure_directory(ftp, str(PurePosixPath(remote_path(args.remote_root, relative)).parent))
            with local.open("rb") as handle:
                ftp.storbinary(f"STOR {remote_path(args.remote_root, relative)}", handle)

        removed_files = 0
        for relative in sorted(remote_files, key=lambda p: len(p.parts), reverse=True):
            if relative not in local_files and relative not in preserve:
                ftp.delete(remote_path(args.remote_root, relative))
                removed_files += 1
        removed_directories = 0
        for relative in sorted(remote_directories, key=lambda p: len(p.parts), reverse=True):
            if relative not in local_directories and relative not in preserve:
                try:
                    ftp.rmd(remote_path(args.remote_root, relative))
                    removed_directories += 1
                except error_perm:
                    pass
    print(json.dumps({
        "uploaded_files": len(local_files),
        "removed_files": removed_files,
        "removed_directories": removed_directories,
        "preserved": sorted(p.as_posix() for p in preserve),
    }, indent=2))


def cmd_verify(args: argparse.Namespace) -> None:
    source = Path(args.source).resolve()
    local_files = {
        PurePosixPath(path.relative_to(source).as_posix()): {
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        }
        for path in source.rglob("*")
        if path.is_file()
    }
    mismatches: list[dict[str, object]] = []
    with connect(args.host, args.user) as ftp:
        _, remote_files = walk_remote(ftp, args.remote_root)
        for relative, expected in sorted(local_files.items(), key=lambda item: str(item[0])):
            value = hashlib.sha256()
            size = 0

            def consume(chunk: bytes) -> None:
                nonlocal size
                size += len(chunk)
                value.update(chunk)

            ftp.retrbinary(f"RETR {remote_path(args.remote_root, relative)}", consume)
            actual = {"bytes": size, "sha256": value.hexdigest()}
            if actual != expected:
                mismatches.append({
                    "path": relative.as_posix(),
                    "expected": expected,
                    "actual": actual,
                })
    report = {
        "format": "cbdc-site-remote-verification-v1",
        "remote_root": args.remote_root,
        "verified_files": len(local_files),
        "mismatches": mismatches,
    }
    output = Path(args.report).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), **report}, indent=2))
    if mismatches:
        raise SystemExit(1)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--host", required=True)
    result.add_argument("--user", required=True)
    result.add_argument("--remote-root", default="/www")
    commands = result.add_subparsers(dest="command", required=True)

    commands.add_parser("list")
    backup = commands.add_parser("backup")
    backup.add_argument("--destination", required=True)
    deploy = commands.add_parser("deploy")
    deploy.add_argument("--source", required=True)
    deploy.add_argument("--preserve", action="append", default=[])
    verify = commands.add_parser("verify")
    verify.add_argument("--source", required=True)
    verify.add_argument("--report", required=True)
    return result


def main() -> None:
    args = parser().parse_args()
    {
        "list": cmd_list,
        "backup": cmd_backup,
        "deploy": cmd_deploy,
        "verify": cmd_verify,
    }[args.command](args)


if __name__ == "__main__":
    main()
