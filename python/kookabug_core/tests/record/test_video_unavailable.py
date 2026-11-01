"""영상 인코더를 쓸 수 없는 환경 (구현 계획 M3 2.5, T5, 검수 M9).

Media Foundation이 없는 Windows(N·KN 판, Server Core)에서도 runner·doctor는 기동하고 실행은 영상
없이 돈다. 사용 불가는 숨은 검사 설정(`KOOKABUG_VIDEO_TEST`의 `msmf`)으로 실제 코드 경로에 넣는다:
MF DLL 이름을 없는 것으로(`mf_missing`), 쓰기 백엔드 번호를 없는 것으로(`backend_missing`), MSMF가
열지 못하는 FourCC로(`encoder_open_failed`).
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest
from helpers.run import tk
from helpers.runner import RunnerHarness
from helpers.video import go, launch, write_scenario

from kb_testing.proc import Spawned, inner_pytest
from kookabug_core.record.video import INDEX_FILE, TEST_ENV, VIDEO_DIR

INJECT: dict[str, dict[str, Any]] = {
    "mf_missing": {"mf_dlls": ["kb-missing-mfplat.dll"]},
    "backend_missing": {"backend": 99_999},
    "encoder_open_failed": {"fourcc": "MJPG"},
}


def graph() -> Any:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    g.node("n_a", "core.input.key", inputs=go("a"), next={"done": "n_w"})
    g.node("n_w", "core.flow.delay", inputs={"ms": 500}, next={"done": "n_pass"})
    return g.node("n_pass", "core.test.pass")


@pytest.mark.process
@pytest.mark.parametrize("reason", sorted(INJECT))
def test_mf_load_failure_runner_passes_status_unavailable(
    tmp_path: Path, spawned: Spawned, reason: str
) -> None:
    scenario = write_scenario(tmp_path / "scenario")
    env = {TEST_ENV: json.dumps({"encoder": "msmf", "msmf": INJECT[reason]})}
    h = RunnerHarness.make(tmp_path, graph(), scenario=str(scenario), env_extra=env)
    done = h.start(spawned).finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "pass", done.run_end
    assert "omitted" not in done.run_end
    assert done.run_json is not None
    assert done.run_json["video"] == {
        "bytes": 0,
        "deleted": 0,
        "kept": 0,
        "reason": reason,
        "status": "unavailable",
    }
    index = json.loads((h.run_dir / VIDEO_DIR / INDEX_FILE).read_text(encoding="utf-8"))
    assert (index["status"], index["reason"]) == ("unavailable", reason)
    (gap,) = index["gaps"]
    assert (gap["gap"], gap["reason"]) == ("unavailable", reason)
    assert not list((h.run_dir / VIDEO_DIR).glob("seg-*"))


def test_doctor_reports_video_unavailable_without_failing_other_checks(
    tmp_path: Path, ocr_models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kookabug_platform import doctor

    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    baseline = {c.id: c.ok for c in doctor.run_checks("headless")}
    monkeypatch.setenv(TEST_ENV, json.dumps({"encoder": "msmf", "msmf": INJECT["mf_missing"]}))
    checks = {c.id: c for c in doctor.run_checks("headless")}
    video = checks["video.encoder"]
    assert video.ok is True  # 영상 없이 실행하므로 실패가 아니다
    assert "영상 사용 불가 (mf_missing)" in video.detail
    assert {k: c.ok for k, c in checks.items()} == baseline


INNER = """
import pytest
from pathlib import Path
from kookabug_core.record.video import VideoFrame
from kookabug_platform.video import MsmfFactory


@pytest.mark.media
def test_write_fails(tmp_path: Path) -> None:
    enc = MsmfFactory().open(tmp_path / "x.mp4", (64, 64))
    try:
        enc.write(VideoFrame(None, (64, 64), 0.0))  # 픽셀 없음: 인코더는 있는데 쓰기가 실패한다
    finally:
        enc.release()
"""


def test_unexpected_encode_error_not_skipped(tmp_path: Path) -> None:
    from kb_testing import media

    available, detail = media.session_probe()
    if not available:
        pytest.skip(f"이 PC에 영상 인코더가 없어 대조할 수 없다 — {detail}")
    test_file = tmp_path / "test_inner_media.py"
    test_file.write_text(textwrap.dedent(INNER), encoding="utf-8")
    proc = inner_pytest(test_file, "-rA")
    out = proc.stdout + proc.stderr
    # 인코더가 있으면 쓰기 실패는 건너뛰기가 아니라 실패다
    assert "1 failed" in out and "skipped" not in out, out
