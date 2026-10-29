"""라이선스 감사 단위 테스트용 가짜 입력."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import license_audit as la

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
