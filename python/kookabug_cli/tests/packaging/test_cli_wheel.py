"""CLI wheel을 레포 밖 깨끗한 venv에 설치해 그래프를 실행한다 (구현 계획 M0b T11).

sdk·nodes·core·cli wheel만 설치하고(서드파티 의존성은 인덱스), 워크스페이스도 레포 밖에 만든다.
플랫폼 `none`의 순수 그래프라 입력·캡처·플러그인이 필요 없다.
"""

import json
from pathlib import Path

import pytest

from kb_testing import packaging as pk
from kookabug_core.record import read_run

PYTHON = pk.REPO_ROOT / "python"

GRAPH = {
    "format": "kookabug.graph/0",
    "kind": "test",
    "nodes": {
        "n_entry": {"next": {"start": "n_log"}, "type": "core.graph.entry", "version": 1},
        "n_log": {
            "in": {"text": "설치본에서 실행"},
            "next": {"done": "n_pass"},
            "title": "로그 남기기",
            "type": "core.log.message",
            "version": 1,
        },
        "n_pass": {"type": "core.test.pass", "version": 1},
    },
    "plugins": {"core": "0.1.0"},
}


@pytest.mark.packaging
def test_cli_installed_runs_graph_outside_repo(tmp_path: Path) -> None:
    wheels = [
        pk.build_dists(PYTHON / name, tmp_path / f"dist-{name}").wheel
        for name in ("kookabug_sdk", "kookabug_nodes", "kookabug_core", "kookabug_cli")
    ]
    py = pk.make_clean_venv(tmp_path / "venv")
    pk.install(py, *wheels)
    kookabug = py.parent / "kookabug.exe"
    assert kookabug.is_file()

    ws = tmp_path / "ws"
    (ws / "tests").mkdir(parents=True)
    (ws / "kookabug.json").write_text('{"format": "kookabug.workspace/0"}', encoding="utf-8")
    (ws / "tests" / "a.graph.json").write_text(json.dumps(GRAPH), encoding="utf-8")
    pk.assert_outside_repo(ws)

    done = pk.run([kookabug, "run", "tests/a.graph.json", "--json"], cwd=ws, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    out = json.loads(done.stdout)
    assert (out["verdict"], out["code"], out["exit_code"]) == ("pass", "test_pass", 0)
    run_dir = Path(out["run_dir"])
    assert run_dir.parent == ws.resolve() / "runs"
    view = read_run(run_dir)
    assert view.run_end is not None and view.run_end["finalized_by"] == "runner"
    assert [e["message"] for e in view.events if e["event"] == "log"] == ["설치본에서 실행"]
    run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_json["status"] == "finished" and run_json["verdict"] == "pass"
    # 설치된 runner가 스냅샷에서 실행했고 오류 출력이 없다
    assert (run_dir / "snapshot" / "tests" / "a.graph.json").is_file()
    assert not (run_dir / "logs" / "runner.stderr.log").read_text(encoding="utf-8").strip()
