"""`kookabug run` 인수 해석 (구현 계획 M0b 2.11).

`--set`, 워크스페이스 찾기, 기한 우선순위, 사용법 오류 = 종료 코드 6.
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

import pytest

from kookabug_cli import main as cli
from kookabug_core.supervisor import DEFAULT_DEADLINE_MS
from kookabug_core.workspace import RunConditions, Workspace


def write(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def workspace(root: Path, **config: Any) -> Path:
    write(root / "kookabug.json", {"format": "kookabug.workspace/0", **config})
    return root


def parse(*argv: str) -> argparse.Namespace:
    return cli.build_parser().parse_args(["run", *argv])


def test_set_parses_json_then_string() -> None:
    assert cli.parse_setting("a=1") == ("a", 1)
    assert cli.parse_setting('a={"x": [1, true]}') == ("a", {"x": [1, True]})
    assert cli.parse_setting('a="1"') == ("a", "1")
    assert cli.parse_setting("a=null") == ("a", None)
    assert cli.parse_setting("game.server=Server 1") == ("game.server", "Server 1")
    assert cli.parse_setting("a=b=c") == ("a", "b=c")
    assert cli.parse_setting("a=") == ("a", "")
    assert cli.parse_setting("a=NaN") == ("a", "NaN")  # JSON 표준이 아닌 토큰은 문자열
    for bad in ("a", "=1"):
        with pytest.raises(argparse.ArgumentTypeError):
            cli.parse_setting(bad)
    args = parse("g.graph.json", "--set", "a=1", "--set", "b=x", "--set", "a=2")
    assert dict(args.settings) == {"a": 2, "b": "x"}  # 같은 키는 뒤의 값


def test_workspace_found_from_graph_path(tmp_path: Path) -> None:
    root = workspace(tmp_path / "ws")
    graph = write(root / "tests" / "deep" / "a.graph.json", {})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    # 그래프 경로(현재 폴더 기준·절대)에서 위로 찾는다
    ws, rel = cli.resolve_target(str(graph), None, cwd=elsewhere)
    assert (ws.root, rel) == (root.resolve(), "tests/deep/a.graph.json")
    ws, rel = cli.resolve_target("tests/deep/a.graph.json", None, cwd=root)
    assert (ws.root, rel) == (root.resolve(), "tests/deep/a.graph.json")
    # --workspace를 주면 워크스페이스 루트 기준 경로도 받는다
    ws, rel = cli.resolve_target("tests/deep/a.graph.json", str(root), cwd=elsewhere)
    assert (ws.root, rel) == (root.resolve(), "tests/deep/a.graph.json")

    outside = write(tmp_path / "outside" / "b.graph.json", {})
    with pytest.raises(cli.UsageError, match=r"워크스페이스 .* 밖"):
        cli.resolve_target(str(outside), str(root), cwd=elsewhere)
    with pytest.raises(cli.UsageError, match=r"kookabug\.json"):
        cli.resolve_target(str(outside), None, cwd=elsewhere)  # 위로 찾아도 없다
    with pytest.raises(cli.UsageError, match="그래프 파일이 없다"):
        cli.resolve_target("tests/none.graph.json", str(root), cwd=elsewhere)
    with pytest.raises(cli.UsageError, match=r"kookabug\.json"):
        cli.resolve_target(str(graph), str(elsewhere), cwd=elsewhere)  # 워크스페이스가 아니다


def test_deadline_precedence(tmp_path: Path) -> None:
    none = RunConditions()
    configured = RunConditions(deadline_ms=1234)
    assert cli.resolve_deadline(None, none) == DEFAULT_DEADLINE_MS == 30 * 60 * 1000
    assert cli.resolve_deadline(None, configured) == 1234
    assert cli.resolve_deadline(99, configured) == 99

    # kookabug.json의 run 블록 → StartOptions (CLI 옵션이 이긴다, 나머지 시간 값은 run 블록)
    run = {"deadline_ms": 5000, "shutdown_grace_ms": 700, "worker_cancel_grace_ms": 300}
    ws = Workspace.open(workspace(tmp_path / "ws", run=run))
    assert ws.diagnostics == []
    options = cli.start_options(parse("a.graph.json"), ws)
    assert (options.deadline_ms, options.shutdown_grace_ms) == (5000, 700)
    assert (options.worker_cancel_grace_ms, options.worker_start_timeout_ms) == (300, 30_000)
    options = cli.start_options(parse("a.graph.json", "--deadline-ms", "42"), ws)
    assert options.deadline_ms == 42

    # run 블록 형식이 틀리면 진단을 남기고 기본값을 쓴다 (실행 전 검증이 보고한다)
    bad = Workspace.open(workspace(tmp_path / "bad", run={"deadline_ms": 0}))
    assert [d.code for d in bad.diagnostics]
    assert cli.start_options(parse("a.graph.json"), bad).deadline_ms == DEFAULT_DEADLINE_MS


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param([], id="no-command"),
        pytest.param(["bogus"], id="unknown-command"),
        pytest.param(["run"], id="no-graph"),
        pytest.param(["run", "a.graph.json", "--deadline-ms", "0"], id="deadline-zero"),
        pytest.param(["run", "a.graph.json", "--deadline-ms", "x"], id="deadline-text"),
        pytest.param(["run", "a.graph.json", "--set", "novalue"], id="set-format"),
        pytest.param(["run", "a.graph.json", "--nope"], id="unknown-option"),
    ],
)
def test_usage_error_exit_6(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == cli.EXIT_USAGE == 6
    assert "오류" in capsys.readouterr().err


def test_usage_error_after_parse_exit_6(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["run", "none.graph.json"]) == cli.EXIT_USAGE
    assert "그래프 파일이 없다" in capsys.readouterr().err
    # --json이면 결과 JSON 한 개 (실행 없음)
    assert cli.main(["run", "none.graph.json", "--json"]) == cli.EXIT_USAGE
    out = json.loads(capsys.readouterr().out)
    assert out["exit_code"] == 6 and out["run_dir"] is None and "그래프 파일" in out["error"]
    assert not list(tmp_path.glob("**/runs"))


def test_dev_options_marked_in_help() -> None:
    parser = cli.build_parser()
    run = parser._subparsers._group_actions[0].choices["run"]  # type: ignore[union-attr]
    text = run.format_help()
    lines = text.splitlines()
    (at,) = [i for i, line in enumerate(lines) if line.strip().startswith("--plugin-module")]
    assert "[개발용]" in " ".join(lines[at : at + 2])  # 옵션 설명이 다음 줄로 넘어갈 수 있다
    assert "--platform-fake" not in text  # 테스트용은 도움말에 없다
    assert "--platform-fake" in {o for a in run._actions for o in a.option_strings}


def test_utf8_stdio_before_output(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Recorder(io.StringIO):
        def write(self, s: str) -> int:
            calls.append("write")
            return super().write(s)

    monkeypatch.setattr(cli, "utf8_stdio", lambda: calls.append("utf8_stdio"))
    monkeypatch.setattr("sys.stdout", Recorder())
    monkeypatch.setattr("sys.stderr", Recorder())
    with pytest.raises(SystemExit):
        cli.main(["run", "--help"])
    with pytest.raises(SystemExit):
        cli.main(["run"])  # argparse 오류 출력
    assert calls[0] == "utf8_stdio" and "write" in calls
    assert calls.index("utf8_stdio", 1) < calls.index("write", calls.index("utf8_stdio", 1))


class NullSink(io.StringIO):
    """출력을 쌓지 않는다 (보관량 검사에서 출력 버퍼를 빼려고)."""

    def write(self, s: str) -> int:
        return len(s)


def test_progress_keeps_only_open_steps(tmp_path: Path) -> None:
    # 끝난 스텝의 경로는 줄을 쓴 뒤 버린다: 보관량은 열린 스텝 수에 묶인다
    progress = cli.Progress(cli.Titles(tmp_path, "tests/t.graph.json"), NullSink())
    progress.event({"event": "step.start", "step": "s0", "path": ["n_call"]})  # 끝나지 않는 스텝
    for i in range(1, 20_001):
        progress.event({"event": "step.start", "step": f"s{i}", "path": ["n_call", "n"]})
        assert progress.open_steps == 2
        progress.event({"event": "step.end", "step": f"s{i}", "status": "success", "exit": "ok"})
    assert progress.open_steps == 1
    progress.event({"event": "step.end", "step": "s0", "status": "success", "exit": "done"})
    assert progress.open_steps == 0
    # 경로를 버린 뒤에도 줄은 그 경로로 만든다
    out = io.StringIO()
    progress = cli.Progress(cli.Titles(tmp_path, "tests/t.graph.json"), out)
    progress.event({"event": "step.start", "step": "s1", "path": ["n_a"]})
    progress.event({"event": "step.end", "step": "s1", "status": "fail", "exit": "fail"})
    assert out.getvalue() == "  [실패] n_a → fail\n" and progress.open_steps == 0
