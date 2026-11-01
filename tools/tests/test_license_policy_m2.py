"""M2 라이선스 정책: 글꼴 파일 한정 OFL-1.1, 데스크톱 앱 prod 의존성 감사 (구현 계획 M2 2.2·U6)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import license_audit as la
from kb_testing.audit_fixtures import (
    POLICY_BASE,
    WIN_314,
    policy,
    run_audit,
    scan_item,
    write_tree,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP = REPO_ROOT / "apps" / "desktop"
# 앱 번들(app.asar)에 들어가지 않는 빌드·검사 도구 (devDependencies)
BUILD_TOOLS = {
    "electron",
    "vite",
    "@vitejs/plugin-react",
    "esbuild",
    "vitest",
    "@playwright/test",
    "playwright",
    "fast-check",
    "typescript",
    # 설치 파일 빌드 (T13). 앱 번들에는 들어가지 않는다
    "electron-builder",
}
# 실행 파일이 없는 패키지(타입 선언 등)의 파일 끝. 번들에 들어갈 코드가 없다
TYPE_ONLY_SUFFIXES = (".d.ts", ".d.mts", ".d.cts", ".js.flow", ".json", ".md")

FONT_FILES = {
    "package.json": '{"name": "@fontsource/x"}',
    "LICENSE": "SIL OPEN FONT LICENSE Version 1.1",
    "README.md": "x",
    "index.css": "@font-face { src: url(./files/x-400.woff2) }",
    "index.d.css.ts": "export {};",
    "scss/metadata.scss": "$x: 1;",
    "files/x-400.woff2": b"wOF2",
    "files/x-400.woff": b"wOFF",
}


def _js(name: str, lic: str, path: Path | None) -> dict[str, Any]:
    paths = [str(path)] if path is not None else []
    return {lic: [{"name": name, "versions": ["1.0.0"], "paths": paths, "license": lic}]}


def _js_problems(name: str, lic: str, path: Path | None) -> list[str]:
    result = run_audit("", [], js=_js(name, lic, path))
    return result.problems


def test_ofl_allowed_only_for_font_files(tmp_path: Path) -> None:
    # 글꼴과 그 선언·메타데이터만 든 패키지는 허용
    fonts = write_tree(tmp_path / "fonts", FONT_FILES)
    assert _js_problems("@fontsource/x", "OFL-1.1", fonts) == []
    result = run_audit("", [], js=_js("@fontsource/x", "OFL-1.1", fonts))
    assert result.js_rows == [("@fontsource/x", "1.0.0", "OFL-1.1")]
    assert "@fontsource/x 1.0.0" in result.notices
    assert "SIL OPEN FONT LICENSE" in result.notices

    # 실행 코드가 하나라도 있으면 실패
    for extra in ("index.js", "lib/loader.mjs", "bin/tool.exe", "native.node", "x.wasm"):
        pkg = write_tree(tmp_path / extra.replace("/", "_"), {**FONT_FILES, extra: "code"})
        problems = _js_problems("ofl-with-code", "OFL-1.1", pkg)
        assert len(problems) == 1, extra
        assert "글꼴이 아닌 파일" in problems[0] and Path(extra).name in problems[0], problems

    # 글꼴이 없는 OFL 패키지, 파일을 확인할 수 없는 패키지도 실패
    no_fonts = write_tree(tmp_path / "nofont", {"package.json": "{}", "index.css": ""})
    assert "글꼴 파일이 없다" in _js_problems("ofl-css", "OFL-1.1", no_fonts)[0]
    assert "확인할 수 없다" in _js_problems("ofl-missing", "OFL-1.1", None)[0]
    assert "확인할 수 없다" in _js_problems("ofl-gone", "OFL-1.1", tmp_path / "없음")[0]

    # 다른 라이선스와 함께 쓴 식은 글꼴 한정 규칙을 타지 않는다 (허용 목록 밖)
    assert _js_problems("mixed", "OFL-1.1 AND MIT", fonts) != []
    # Python 패키지·네이티브 판정에서는 OFL이 허용 목록 밖 그대로
    py = run_audit("fontpkg==1.0\n", [scan_item("fontpkg", "1.0", "OFL-1.1")])
    assert any("fontpkg" in p and "허용 목록 밖" in p for p in py.problems), py.problems
    assert la.classify_license("OFL-1.1", policy())[0] is la.Status.UNKNOWN
    # 정책에서 글꼴 한정 표를 빼면 같은 글꼴 패키지도 실패
    no_rule = la.load_policy({k: v for k, v in POLICY_BASE.items() if k != "font_only"})
    assert run_audit("", [], js=_js("@fontsource/x", "OFL-1.1", fonts), pol=no_rule).problems


def test_font_only_policy_requires_licenses_and_suffixes() -> None:
    with pytest.raises(la.AuditInputError, match="font_only"):
        la.load_policy({**POLICY_BASE, "font_only": {"licenses": ["OFL-1.1"]}})
    with pytest.raises(la.AuditInputError, match="font_only"):
        la.load_policy({**POLICY_BASE, "font_only": {"licenses": [], "font_suffixes": [".woff2"]}})
    rule = policy().font_only
    assert rule is not None
    assert rule.licenses == frozenset({"OFL-1.1"})


# ---------------------------------------------------------------- 실제 데스크톱 앱


def _pnpm() -> str:
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        pytest.fail("pnpm이 PATH에 없다 (desktop_build 검사는 CI desktop 잡·로컬에서 돈다)")
    return pnpm


def _run(cmd: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False
    )
    assert proc.returncode == 0, f"{cmd}: {proc.stdout}\n{proc.stderr}"
    return proc.stdout


def _prod_licenses() -> list[la.ScannedPackage]:
    """감사 파이프라인과 같은 명령 (`license_pipeline.py` 4단계)."""
    out = _run([_pnpm(), "licenses", "list", "--prod", "--json"], REPO_ROOT)
    return la.parse_pnpm_licenses(json.loads(out))


def _desktop_manifest() -> dict[str, Any]:
    return json.loads((DESKTOP / "package.json").read_text("utf-8"))


@pytest.mark.desktop_build
def test_desktop_prod_deps_in_js_audit() -> None:
    manifest = _desktop_manifest()
    scanned = _prod_licenses()
    names = {p.display_name for p in scanned}
    # 앱 번들에 들어가는 직접 의존성은 전부 감사 대상이고, 판이 package.json 고정판과 같다
    for name, version in manifest["dependencies"].items():
        assert name in names, name
        assert version in {p.version for p in scanned if p.display_name == name}, name
    # 빌드·검사 도구는 dependencies에 없고 감사 대상도 아니다
    assert not BUILD_TOOLS & set(manifest["dependencies"])
    assert BUILD_TOOLS - {"playwright"} <= set(manifest["devDependencies"])
    assert not BUILD_TOOLS & names, BUILD_TOOLS & names
    # 고정 규칙: 범위 지정 없이 정확한 판
    for section in ("dependencies", "devDependencies"):
        for name, spec in manifest[section].items():
            assert spec == "workspace:*" or spec[0].isdigit(), f"{name}: {spec}"

    # 실제 허용 목록으로 판정해 통과한다. 글꼴 패키지는 글꼴 한정 규칙으로 허용된다
    result = la.audit([], la.load_marker_env(WIN_314), {}, scanned, policy())
    assert result.problems == []
    fonts = {row[0] for row in result.js_rows if row[2] == "OFL-1.1"}
    assert fonts == {
        "@fontsource/noto-sans-kr",
        "@fontsource/jetbrains-mono",
        "@fontsource/fraunces",
    }


def _type_only(pkg: la.ScannedPackage) -> bool:
    files = [f for p in pkg.paths for f in Path(p).rglob("*") if f.is_file()]
    return bool(files) and all(
        f.name.startswith("LICENSE") or f.name.lower().endswith(TYPE_ONLY_SUFFIXES) for f in files
    )


@pytest.mark.desktop_build
def test_desktop_prod_deps_equal_bundle_inputs() -> None:
    """번들에 들어간 패키지 = prod 감사 집합 (실행 코드가 없는 타입 선언 패키지만 차이로 허용)."""
    _run([_pnpm(), "--filter", "@kookabug/desktop", "run", "build"], REPO_ROOT)
    meta = json.loads((DESKTOP / "dist" / "bundle-meta.json").read_text("utf-8"))
    bundled = {
        (p["name"], p["version"])
        for p in meta["packages"]
        if not p["name"].startswith("@kookabug/")  # 제1자 워크스페이스 코드
    }
    scanned = _prod_licenses()
    audited = {(p.display_name, p.version) for p in scanned}

    # 번들에 들어갔는데 감사되지 않은 패키지가 없다
    assert bundled - audited == set()
    # 감사했는데 번들에 없는 것은 실행 코드가 없는 패키지(@types/*, csstype)뿐이다
    extra = [p for p in scanned if (p.display_name, p.version) not in bundled]
    assert [p.display_name for p in extra if not _type_only(p)] == []
    # 직접 의존성은 전부 번들에 들어간다 (쓰지 않는 prod 의존성이 없다)
    for name, version in _desktop_manifest()["dependencies"].items():
        assert (name, version) in bundled, name
    # 글꼴 파일이 번들에 실제로 들어간다
    assets = list((DESKTOP / "dist" / "renderer" / "assets").glob("*.woff2"))
    for family in ("noto-sans-kr", "jetbrains-mono", "fraunces"):
        assert any(a.name.startswith(family) for a in assets), family
