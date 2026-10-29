"""pytest가 timeout으로 강제 종료돼도 테스트가 띄운 프로세스가 남지 않는다 (구현 계획 M0b 2.3).

별도 pytest 프로세스가 감독자 → runner → 손자 사슬을 띄우고 무한 대기하다 pytest-timeout(thread
방식, `os._exit`)으로 죽는다. 그때는 fixture 정리가 돌지 않으므로, 사슬이 끝났다면 그 pytest의
세션 Job(마지막 핸들이 닫힘)이 끝낸 것이다. 바깥 pytest는 살아 있으므로 바깥 세션 Job은 관여하지
않는다. 별도 pytest와 사슬은 venv 런처 없이 띄운다 — 런처의 자손 정리가 결과를 대신하지 않게.
"""

import textwrap
from pathlib import Path

import pytest

from kb_testing.proc import PROCS_DIR, Spawned, assert_no_live, inner_pytest, read_tree
from kookabug_core.win import ProcessId, is_alive

pytestmark = pytest.mark.process

INNER_TIMEOUT_S = 5


def hang_with_tree(tmp_path: Path, *, plugin: bool) -> tuple[list[ProcessId], str]:
    """별도 pytest가 사슬을 띄운 뒤 timeout으로 죽는다. (사슬 식별, 출력)"""
    out = tmp_path / "tree"
    out.mkdir()
    up = tmp_path / "all-up"
    test_file = tmp_path / "inner" / "test_inner_hang.py"
    test_file.parent.mkdir()
    test_file.write_text(
        textwrap.dedent(
            f"""
            import subprocess, time
            from pathlib import Path
            from kb_testing.proc import direct_env, python_cmd, read_tree, wait_until

            OUT = Path({str(out)!r})

            def test_hang():
                # 감독자(0) → runner(1) → 워커(2). 정리 픽스처를 쓰지 않는다
                cmd = python_cmd({str(PROCS_DIR / "tree.py")!r}, "--out", OUT, "--depth", "3")
                subprocess.Popen(cmd, env=direct_env())
                wait_until(lambda: len(read_tree(OUT)) == 3)
                Path({str(up)!r}).touch()
                while True:
                    time.sleep(1)
            """
        ),
        encoding="utf-8",
    )
    result = inner_pytest(test_file, f"--timeout={INNER_TIMEOUT_S}", plugin=plugin)
    detail = result.stdout + result.stderr
    assert result.returncode != 0, detail
    assert "Timeout" in detail, detail
    assert up.exists(), f"사슬이 timeout 전에 다 뜨지 않았다\n{detail}"
    tree = read_tree(out)
    assert sorted(tree) == [0, 1, 2]
    return [ProcessId(r["pid"], r["created"]) for r in tree.values()], detail


def test_pytest_timeout_leaves_no_orphans(tmp_path: Path) -> None:
    idents, _ = hang_with_tree(tmp_path, plugin=True)
    assert_no_live(idents)


def test_without_session_job_timeout_leaves_orphans(tmp_path: Path, spawned: Spawned) -> None:
    # 음성 대조: 플러그인(세션 Job) 없이는 같은 구성에서 사슬이 살아남는다. 위 검사의 통과가
    # 세션 Job에서 온다는 증거. 남은 사슬은 정리 픽스처가 끝낸다
    idents, detail = hang_with_tree(tmp_path, plugin=False)
    for ident in idents:
        spawned.track(ident)
    assert all(is_alive(i) for i in idents), detail
