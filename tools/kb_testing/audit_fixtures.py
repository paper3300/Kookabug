"""라이선스 감사 단위 테스트용 가짜 입력."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import license_audit as la
import native_audit as na

ALLOWLIST = Path(__file__).resolve().parents[1] / "license-allowlist.toml"
POLICY_BASE: dict[str, Any] = tomllib.loads(ALLOWLIST.read_text(encoding="utf-8"))

# 감사 대상: Windows x64, CPython 3.14
WIN_314: dict[str, str] = {
    "implementation_name": "cpython",
    "implementation_version": "3.14.10",
    "os_name": "nt",
    "platform_machine": "AMD64",
    "platform_python_implementation": "CPython",
    "platform_release": "11",
    "platform_system": "Windows",
    "platform_version": "10.0.26200",
    "python_full_version": "3.14.10",
    "python_version": "3.14",
    "sys_platform": "win32",
}


def env(**overrides: str) -> dict[str, str]:
    return {**WIN_314, **overrides}


def policy(exceptions: dict[str, dict[str, str]] | None = None) -> la.Policy:
    """실제 허용 목록. exceptions를 주면 [exceptions]만 바꾼다."""
    if exceptions is None:
        return la.load_policy_file(ALLOWLIST)
    return la.load_policy({**POLICY_BASE, "exceptions": exceptions})


def scan_item(name: str, version: str, license: str = "MIT", text: str = "") -> dict[str, Any]:
    return {
        "Name": name,
        "Version": version,
        "License": license,
        "LicenseFile": "UNKNOWN",
        "LicenseText": text or f"{license} license text of {name}",
        "NoticeFile": "UNKNOWN",
        "NoticeText": "UNKNOWN",
    }


def write_tree(root: Path, files: Mapping[str, str | bytes]) -> Path:
    """상대 경로 → 내용으로 가짜 트리를 만든다."""
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return root


def write_record(site: Path, dist: str, tops: Sequence[str], extra: Sequence[str] = ()) -> None:
    """`tops` 폴더와 `<dist>.dist-info`(예: pkg-1.0) 아래 파일 전부와 `extra`로 RECORD를 쓴다."""
    info = f"{dist}.dist-info"
    rels = sorted(
        p.relative_to(site).as_posix()
        for p in site.rglob("*")
        if p.is_file() and p.relative_to(site).parts[0] in (*tops, info) and p.name != "RECORD"
    )
    lines = [f"{r},sha256=x,1" for r in [*rels, *extra]] + [f"{info}/RECORD,,"]
    record = site / info / "RECORD"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("\n".join(lines) + "\n", encoding="utf-8")


def native_table(
    native: Sequence[Mapping[str, Any]] = (),
    strip: Sequence[Mapping[str, Any]] = (),
    refs: Mapping[str, Mapping[str, str]] | None = None,
) -> na.NativeTable:
    return na.load_native_table(
        {"native": list(native), "strip": list(strip), "licenseref": dict(refs or {})}
    )


def run_audit(
    runtime: str,
    scan: list[dict[str, Any]],
    marker_env: dict[str, str] | None = None,
    js: dict[str, Any] | None = None,
    pol: la.Policy | None = None,
) -> la.AuditResult:
    return la.audit(
        la.parse_runtime(runtime),
        la.load_marker_env(marker_env or WIN_314),
        la.parse_pip_licenses(scan),
        la.parse_pnpm_licenses(js or {}),
        pol or policy(),
    )
