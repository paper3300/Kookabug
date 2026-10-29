"""라이선스 판정 단위 테스트 (실제 tools/license-allowlist.toml을 쓴다)."""

import json
from pathlib import Path

import pytest
from packaging.utils import canonicalize_name

import license_audit as la
from kb_testing.audit_fixtures import (
    ALLOWLIST,
    POLICY_BASE,
    WIN_314,
    policy,
    run_audit,
    scan_item,
)

N = canonicalize_name("somepkg")


@pytest.mark.parametrize(
    "license_text",
    [
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "ISC",
        "PSF-2.0",
        "Python-2.0",
        "0BSD",
        "Unlicense",
        # 스캐너가 주는 분류자 이름
        "MIT License",
        "Apache Software License",
        "BSD License",
        "Python Software Foundation License",
        # 식
        "MIT OR GPL-3.0-only",
        "Apache-2.0 AND BSD-3-Clause",
        "(MIT OR Apache-2.0) AND ISC",
        "Apache-2.0 WITH LLVM-exception",
        "Apache Software License; BSD License",
    ],
)
def test_allows_permissive_licenses(license_text: str) -> None:
    verdict = la.judge_package(N, license_text, policy())
    assert verdict.ok, verdict


@pytest.mark.parametrize(
    "license_text",
    [
        "GPL-3.0",
        "GPL-3.0-only",
        "GPL-2.0-or-later",
        "LGPL-2.1",
        "LGPL-2.1-only",
        "AGPL-3.0",
        "AGPL-3.0-or-later",
        "SSPL-1.0",
        "GNU General Public License v3 (GPLv3)",
        "GNU Lesser General Public License v2 or later (LGPLv2+)",
        "GNU Affero General Public License v3",
        "MIT AND GPL-3.0-only",
        "MIT License; GNU General Public License v2 (GPLv2)",
    ],
)
def test_rejects_gpl_family(license_text: str) -> None:
    assert not la.judge_package(N, license_text, policy()).ok
    # 이름별 예외로도 풀리지 않는다
    verdict = la.judge_package(
        N, license_text, policy({"somepkg": {"license": "MIT", "reason": "시험"}})
    )
    assert not verdict.ok
    assert "금지" in verdict.detail


@pytest.mark.parametrize("license_text", ["UNKNOWN", "", "Proprietary", "Custom License v1"])
def test_rejects_unknown_license_without_exception(license_text: str) -> None:
    assert not la.judge_package(N, license_text, policy()).ok

    with_exc = policy({"somepkg": {"license": "MIT", "reason": "저장소 LICENSE 확인"}})
    verdict = la.judge_package(N, license_text, with_exc)
    assert verdict.ok
    assert verdict.license == "MIT"

    # 예외에 적은 라이선스도 허용 목록 밖이면 실패
    bad_exc = policy({"somepkg": {"license": "Proprietary", "reason": "x"}})
    assert not la.judge_package(N, license_text, bad_exc).ok


@pytest.mark.parametrize(
    "license_text",
    [
        "MIT WITH LicenseRef-Unreviewed",  # 검토하지 않은 예외
        "MIT WITH GPL-3.0-only",  # 예외 자리에 라이선스
        "MIT WITH OR",  # 문법 오류
        "MIT WITH",
        "MIT WITH (Apache-2.0)",
        "(MIT OR ISC) WITH LLVM-exception",  # WITH는 단일 식별자에만
        "Apache-2.0 WITH LLVM-exception WITH Other-exception",
        "BSD-3-Clause WITH LLVM-exception",  # 검토한 예외라도 조합이 다르면 미상
    ],
)
def test_with_requires_reviewed_combination(license_text: str) -> None:
    verdict = la.judge_package(N, license_text, policy())
    assert not verdict.ok, verdict
    # 실제 감사 경로에서도 실패한다
    result = run_audit("probe==1.0\n", [scan_item("probe", "1.0", license_text)])
    assert not result.ok
    assert any("[라이선스] probe" in p for p in result.problems)


@pytest.mark.parametrize(
    "license_text",
    [
        "Apache-2.0 WITH LLVM-exception",
        "(Apache-2.0 WITH LLVM-exception) OR GPL-3.0-only",
        "MIT AND Apache-2.0 WITH LLVM-exception",
        "MIT OR GPL-3.0-only",
    ],
)
def test_reviewed_with_combination_and_or_alternatives_allowed(license_text: str) -> None:
    assert la.judge_package(N, license_text, policy()).ok
    assert run_audit("probe==1.0\n", [scan_item("probe", "1.0", license_text)]).ok


def test_with_does_not_unlock_denied_license() -> None:
    pol = la.load_policy(
        {**POLICY_BASE, "allowed_with": ["GPL-2.0-only WITH Classpath-exception-2.0"]}
    )
    verdict = la.judge_package(N, "GPL-2.0-only WITH Classpath-exception-2.0", pol)
    assert not verdict.ok
    assert "금지" in verdict.detail


@pytest.mark.parametrize("entry", ["MIT", "MIT WITH", "MIT AND ISC", "(MIT) WITH X"])
def test_allowed_with_entry_format(entry: str) -> None:
    with pytest.raises(la.AuditInputError):
        la.load_policy({**POLICY_BASE, "allowed_with": [entry]})


def test_mpl_requires_named_exception() -> None:
    for text in ("MPL-2.0", "Mozilla Public License 2.0 (MPL 2.0)"):
        verdict = la.judge_package(N, text, policy())
        assert not verdict.ok
        assert "예외" in verdict.detail

    named = policy({"somepkg": {"license": "MPL-2.0", "reason": "수정 없이 사용"}})
    assert la.judge_package(N, "MPL-2.0", named).ok
    # 다른 패키지 이름의 예외로는 풀리지 않는다
    assert not la.judge_package(canonicalize_name("otherpkg"), "MPL-2.0", named).ok

    # 이유 없는 예외는 설정 오류
    with pytest.raises(la.AuditInputError):
        policy({"somepkg": {"license": "MPL-2.0"}})


def test_notices_file_lists_every_runtime_package() -> None:
    runtime = "alpha==1.0\nbeta-pkg==2.0\n    # via alpha\ngamma==3.0 ; sys_platform == 'win32'\n"
    scan = [
        scan_item("alpha", "1.0", "MIT", "ALPHA LICENSE TEXT"),
        scan_item("beta_pkg", "2.0", "Apache-2.0", "BETA LICENSE TEXT"),
        {**scan_item("gamma", "3.0", "BSD-3-Clause"), "NoticeText": "GAMMA NOTICE"},
    ]
    js = {"MIT": [{"name": "left-pad", "versions": ["1.3.0"], "paths": [], "license": "MIT"}]}
    result = run_audit(runtime, scan, js=js)
    assert result.ok, result.problems
    for needle in (
        "alpha 1.0",
        "ALPHA LICENSE TEXT",
        "beta-pkg 2.0",
        "BETA LICENSE TEXT",
        "gamma 3.0",
        "GAMMA NOTICE",
        "left-pad 1.3.0",
    ):
        assert needle in result.notices
    assert [r[0] for r in result.python_rows] == ["alpha", "beta-pkg", "gamma"]


def test_js_license_is_judged() -> None:
    js = {"GPL-3.0": [{"name": "copyleft-lib", "versions": ["1.0.0"], "license": "GPL-3.0"}]}
    result = run_audit("", [], js=js)
    assert not result.ok
    assert any("copyleft-lib" in p for p in result.problems)


def test_cli_exit_codes(tmp_path: Path) -> None:
    runtime, env_file, py_json = (
        tmp_path / "runtime.txt",
        tmp_path / "env.json",
        tmp_path / "py.json",
    )
    notices = tmp_path / "out" / "NOTICES.txt"
    runtime.write_text("alpha==1.0\n", encoding="utf-8")
    env_file.write_text(json.dumps(WIN_314), encoding="utf-8")
    args = [
        "--runtime",
        str(runtime),
        "--marker-env",
        str(env_file),
        "--python",
        str(py_json),
        "--allowlist",
        str(ALLOWLIST),
        "--notices-out",
        str(notices),
    ]

    py_json.write_text(json.dumps([scan_item("alpha", "1.0")]), encoding="utf-8")
    assert la.main(args) == 0
    assert "alpha 1.0" in notices.read_text("utf-8")

    py_json.write_text(json.dumps([scan_item("alpha", "1.0", "GPL-3.0")]), encoding="utf-8")
    assert la.main(args) == 1

    py_json.write_text("not json", encoding="utf-8")
    assert la.main(args) == 2
