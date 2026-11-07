"""설치 스모크 `cli.plugin`의 판정 (M6 B7 검수 H1 회귀): 플러그인 개발용 재정의를 지우고, 동봉 uv
판정은 작업 로그의 uv 실행 파일이 그 설치 루트의 `tools\\uv\\uv.exe`와 같은 파일일 때만. 설치본 없이
가짜 트리로 본다."""

from __future__ import annotations

from pathlib import Path

from installer import build, smoke


def _tree(root: Path) -> Path:
    for rel in (build.TOOLS_UV, f"{build.BIN}/{build.LAUNCHER}"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"MZ")
    return root


def _log(*exes: Path) -> str:
    lines = [f"$ {exe} pip install --no-deps x.whl\n(종료 0)" for exe in exes]
    return "\n".join(["$ C:\\Windows\\System32\\git.exe clone x y", *lines]) + "\n"


def test_bundled_uv_is_same_file_of_this_root(tmp_path: Path) -> None:
    root = _tree(tmp_path / "설치 폴더 공백 한글")
    other = _tree(tmp_path / "다른 설치")
    mine = root / build.TOOLS_UV
    assert smoke.bundled_uv_used(_log(mine), root)
    # 대소문자·확장자 표기가 달라도 같은 파일 (8.3 짧은 이름도 파일 동일성으로 같다)
    upper = Path(str(mine).upper().replace(".EXE", ".exe"))
    assert smoke.bundled_uv_used(_log(upper, mine), root)
    # 다른 설치 트리의 같은 접미사·섞임·외부 uv·uv 없음·이 루트에 uv 없음은 통과하지 않는다
    assert not smoke.bundled_uv_used(_log(other / build.TOOLS_UV), root)
    assert not smoke.bundled_uv_used(_log(mine, other / build.TOOLS_UV), root)
    external = tmp_path / "ext" / "uv.exe"
    external.parent.mkdir()
    external.write_bytes(b"MZ")
    assert not smoke.bundled_uv_used(_log(external), root)
    assert not smoke.bundled_uv_used(_log(), root)
    (root / build.TOOLS_UV).unlink()
    assert not smoke.bundled_uv_used(_log(mine), root)


def test_plugin_overrides_removed_and_checked(tmp_path: Path) -> None:
    root = _tree(tmp_path / "root")
    base = {
        "PATH": r"C:\Windows",
        "KOOKABUG_UV": str(tmp_path / "ext" / "uv.exe"),
        "kookabug_sdk_wheel": "x.whl",
        "KOOKABUG_PLUGIN_DEBUG": "1",
        "KOOKABUG_AGENT": "a",
    }
    env = smoke.python_free_env(root, base)
    assert not {k for k in env if k.upper().startswith("KOOKABUG_")} & {
        "KOOKABUG_UV",
        "KOOKABUG_SDK_WHEEL",
        "KOOKABUG_PLUGIN_DEBUG",
        "KOOKABUG_AGENT",
    }
    ok, detail = smoke.check_env(root, env)
    assert ok, detail
    # 재정의가 남은 환경이면 env.python_free가 실패한다
    ok, detail = smoke.check_env(root, {**env, "KOOKABUG_UV": "x"})
    assert not ok and "KOOKABUG_UV" in detail
