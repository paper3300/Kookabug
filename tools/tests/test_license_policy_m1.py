"""M1 라이선스 정책 변경: 허용형 SPDX 추가, 패키지별 WITH 예외, LicenseRef (구현 계획 M1 2.1)."""

import pytest

import license_audit as la
import native_audit as na
from kb_testing.audit_fixtures import POLICY_BASE, policy, run_audit, scan_item

GCC = "GPL-3.0-or-later WITH GCC-exception-3.1"
OPENBLAS = f"BSD-3-Clause AND BSD-3-Clause-Open-MPI AND {GCC}"


def _judge(name: str, lic: str, pol: la.Policy | None = None) -> la.LicenseVerdict:
    return la.judge_package(la.canonicalize_name(name), lic, pol or policy())


def test_numpy_gcc_exception_allowed_only_for_numpy() -> None:
    assert _judge("numpy", GCC).ok
    assert _judge("numpy", OPENBLAS).ok
    other = _judge("scipy", GCC)
    assert not other.ok
    assert "금지" in other.detail
    assert not _judge("some-blas", OPENBLAS).ok

    # 감사 전체에서도 같다: 같은 식이 다른 패키지면 실패
    result = run_audit(
        "numpy==2.5.4\nfakeblas==1.0\n",
        [scan_item("numpy", "2.5.4", OPENBLAS), scan_item("fakeblas", "1.0", OPENBLAS)],
    )
    assert [p for p in result.problems if "numpy" in p] == []
    assert any("fakeblas" in p and "금지" in p for p in result.problems)


def test_with_exception_checked_before_denied_pattern_only_when_listed() -> None:
    pol = policy()
    numpy = la.canonicalize_name("numpy")
    # 목록에 있는 조합은 거부 패턴(^A?GPL)보다 먼저 허용된다
    assert la.classify_license(GCC, pol, package=numpy)[0] is la.Status.ALLOWED
    # 같은 패키지라도 목록 밖 조합·WITH 없는 GPL은 금지 그대로
    for expr in (
        "GPL-3.0-or-later",
        "GPL-3.0-or-later WITH Classpath-exception-2.0",
        "GPL-2.0-or-later WITH GCC-exception-3.1",
        f"MIT AND {GCC} AND LGPL-2.1-only",
    ):
        assert la.classify_license(expr, pol, package=numpy)[0] is la.Status.DENIED, expr
    # 패키지를 주지 않으면(다른 판정 경로) 예외가 없다
    assert la.classify_license(GCC, pol)[0] is la.Status.DENIED

    # 예외 표에 없는 패키지 이름이면 같은 식도 금지
    no_with = la.load_policy({**POLICY_BASE, "package_with": {}})
    assert la.classify_license(GCC, no_with, package=numpy)[0] is la.Status.DENIED


def test_package_with_requires_reason_and_with_form() -> None:
    with pytest.raises(la.AuditInputError, match="이유"):
        la.load_policy({**POLICY_BASE, "package_with": {"numpy": {GCC: " "}}})
    with pytest.raises(la.AuditInputError, match="WITH"):
        la.load_policy({**POLICY_BASE, "package_with": {"numpy": {"GPL-3.0-or-later": "x"}}})


@pytest.mark.parametrize("spdx", ["Zlib", "CC0-1.0", "BSD-3-Clause-Open-MPI", "BSL-1.0", "TCL"])
def test_new_permissive_spdx_allowed(spdx: str) -> None:
    assert la.classify_license(spdx, policy())[0] is la.Status.ALLOWED
    assert _judge("pkg", f"MIT AND {spdx}").ok


def test_numpy_pypi_expression_allowed() -> None:
    expr = "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0"
    verdict = _judge("numpy", expr)
    assert verdict.ok
    assert verdict.license == expr
    # 한 부분이라도 허용 밖이면 실패 (AND)
    assert not _judge("numpy", "BSD-3-Clause AND 0BSD AND Foo-1.0").ok


def test_licenseref_requires_native_entry() -> None:
    pol = policy()
    # 패키지 메타데이터의 LicenseRef는 허용하지 않는다
    assert not _judge("vendor-pkg", "LicenseRef-MS-VC-Redist").ok
    assert la.classify_license("LicenseRef-MS-VC-Redist", pol)[0] is la.Status.UNKNOWN

    # 네이티브 표에 정의한 LicenseRef만 그 표의 항목에서 허용한다
    entry = {
        "glob": "vendor/runtime.dll",
        "package": "vendor-pkg",
        "license": "LicenseRef-MS-VC-Redist",
        "reason": "수정 없이 재배포",
    }
    ref = {"name": "VC++", "source": "https://example.invalid/terms", "reason": "재배포 허용"}
    defined = na.load_native_table(
        {"native": [entry], "licenseref": {"LicenseRef-MS-VC-Redist": ref}}
    )
    undefined = na.load_native_table({"native": [entry]})
    native_entry = defined.entries[0]
    assert na.judge_entry(native_entry, defined, pol)[0] is la.Status.ALLOWED
    assert na.judge_entry(native_entry, undefined, pol)[0] is la.Status.UNKNOWN

    # LicenseRef 정의에는 원문 위치와 처리 근거가 있어야 한다
    with pytest.raises(la.AuditInputError, match="source"):
        na.load_native_table({"licenseref": {"LicenseRef-X": {"name": "x", "reason": "y"}}})
    with pytest.raises(la.AuditInputError, match="LicenseRef-"):
        na.load_native_table({"licenseref": {"VC": ref}})
