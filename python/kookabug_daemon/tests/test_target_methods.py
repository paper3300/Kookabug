"""target 편집 메서드 (M2 계획 2.4·2.9, T6). 헤드리스: 정지 화면은 PNG(`target.load_image`).

저장 실패·경쟁 검사는 실패 뒤에 기존 target을 다시 읽어 JSON·이미지 바이트와 같은 정지 화면의
매칭 결과가 그대로인지 매번 본다. 순서는 저장소 훅(같은 프로세스)과 고장 주입 지점(하위 프로세스
daemon kill)으로 강제한다.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np
import pytest
from helpers.cli import cli_env
from helpers.daemon_targets import (
    CAPTURES,
    PATTERN,
    PATTERN_AT,
    PATTERN_AT2,
    START_BUTTON,
    Editor,
    locked_file,
    same_frame_match,
    snapshot,
    target_workspace,
)
from helpers.graphs import GraphBuilder, target
from helpers.runner import RUNNER_CMD

from kb_testing.daemon import DaemonProcess, ThreadDaemon, daemon_env
from kb_testing.proc import Spawned, faults_env, wait_until
from kookabug_cli import target_cmd
from kookabug_core.service import WorkspaceService
from kookabug_core.supervisor import Supervisor
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.image_cache import NAME
from kookabug_daemon.session import read_session
from kookabug_platform.dpi import normalized_to_pixels, pixels_to_normalized
from kookabug_platform.frames import decode_image
from kookabug_platform.vision import FrameMeta, Vision, load_target_file

pytestmark = pytest.mark.process

SAMPLE: Final = "targets/title/start_button.target.json"
OTHER_RECT: Final = (380, 360, 260, 100)
"""시작 버튼을 둘러싼 더 큰 영역 (시작 버튼과 다른 바이트의 자른 영역)."""
TITLE_TEXT: Final = (312, 150, 400, 80)
PREVIEW_KEYS: Final = {
    "found",
    "match",
    "best",
    "threshold",
    "expected_scale",
    "search",
    "candidates",
    "elapsed_ms",
    "search_rect_px",
    "seq",
    "peaks",  # M4 T11 같은 모양 N곳 (target test --json에는 없다)
}
OWNERSHIP: Final = ".kookabug/editor-images.json"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return target_workspace(tmp_path)


@contextmanager
def editor(root: Path, **kwargs: Any) -> Iterator[tuple[ThreadDaemon, Editor]]:
    with ThreadDaemon(root, **kwargs) as d, d.client() as client:
        yield d, Editor(client)


def failure(fn: Callable[[], Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        fn()
    return caught.value


def crop_png(root: Path, rect: tuple[int, int, int, int], source: str = "title.png") -> bytes:
    """daemon이 같은 자른 영역으로 만드는 것과 같은 PNG 바이트."""
    x, y, w, h = rect
    pixels = decode_image((root / CAPTURES / source).read_bytes())[y : y + h, x : x + w]
    ok, data = cv2.imencode(".png", np.ascontiguousarray(pixels))
    assert ok
    return data.tobytes()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def owned(root: Path) -> list[dict[str, Any]]:
    path = root / OWNERSHIP
    if not path.exists():
        return []
    return json.loads(path.read_text("utf-8"))["images"]


def write_target(root: Path, rel: str, image: str, **extra: Any) -> None:
    body = {"format": "kookabug.target/0", "image": image, **extra}
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")


def old_mtime(path: Path) -> int:
    ns = 1_600_000_000 * 10**9
    os.utime(path, ns=(ns, ns))
    return ns


def keep_state(root: Path, ed: Editor, frame: dict[str, Any], rel: str) -> Callable[[], None]:
    """지금 target의 JSON·이미지 바이트와 같은 정지 화면 매칭 결과를 기억한다. 돌려준 함수가 그대로
    인지 확인한다."""
    opened = ed.open(rel)
    image = root / Path(rel).parent / opened["spec"]["image"]
    json_bytes, image_bytes = (root / rel).read_bytes(), image.read_bytes()
    match = same_frame_match(ed, frame, rel)

    def check() -> None:
        assert (root / rel).read_bytes() == json_bytes
        assert image.read_bytes() == image_bytes
        assert same_frame_match(ed, frame, rel) == match

    return check


# ---------------------------------------------------------------- 정지 화면


def test_load_image_frame_meta(root: Path) -> None:
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        assert (frame["width"], frame["height"]) == (1024, 640)
        assert frame["client_size"] == [1024, 640] and frame["dpi"] == 96
        assert frame["image"] == {"cache": f"{frame['frame_id']}.png", "width": 1024, "height": 640}
        cached = root / ".kookabug" / "cache" / "editor" / frame["image"]["cache"]
        source = decode_image((root / CAPTURES / "title.png").read_bytes())
        assert np.array_equal(decode_image(cached.read_bytes()), source)

        assert failure(lambda: ed.load(f"{CAPTURES}/missing.png")).kind == "not_found"
        assert failure(lambda: ed.load(".kookabug/x.png")).kind == "private_path"
        assert failure(lambda: ed.load("../x.png")).kind == "path_outside_workspace"
        assert failure(lambda: ed.load("kookabug.json")).code == -32602
        (root / CAPTURES / "broken.png").write_bytes(b"not a png")
        assert failure(lambda: ed.load(f"{CAPTURES}/broken.png")).kind == "target_image_invalid"


def test_frame_expired_after_16(root: Path) -> None:
    with editor(root) as (_, ed):
        frames = [ed.load(f"{CAPTURES}/title.png") for _ in range(17)]
        error = failure(lambda: ed.preview(frames[0], crop=(frames[0], START_BUTTON)))
        assert error.kind == "frame_expired"
        assert error.data["diagnostics"][0]["code"] == "frame_expired"
        assert ed.preview(frames[-1], crop=(frames[1], START_BUTTON))["found"] is True
        # 저장의 crop도 같은 규칙
        error = failure(lambda: ed.save("targets/x/a.target.json", frames[0], START_BUTTON))
        assert error.kind == "frame_expired"
        assert not (root / "targets" / "x").exists()


def test_cache_png_served_paths_only_in_cache(root: Path) -> None:
    cache = root / ".kookabug" / "cache" / "editor"
    cache.mkdir(parents=True)
    (cache / "f_old.png").write_bytes(b"old")
    with editor(root) as (_, ed):
        assert not (cache / "f_old.png").exists()  # 시작 때 비운다
        names = [ed.load(f"{CAPTURES}/{n}.png")["image"]["cache"] for n in ("title", "login")]
        for name in names:
            assert NAME.match(name)
            path = (cache / name).resolve()
            assert path.parent == cache.resolve() and path.is_file()
        assert sorted(p.name for p in cache.iterdir()) == sorted(names)
        # 기존 target의 이미지는 캐시가 아니라 워크스페이스 경로로 준다 (.kookabug/ 밖)
        image = ed.open(SAMPLE)["image"]
        assert image == {"workspace": "targets/title/start_button.png", "width": 200, "height": 64}


# ---------------------------------------------------------------- 미리보기


def test_preview_matches_target_cmd_json_fields(root: Path, tmp_path: Path) -> None:
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        opened = ed.open(SAMPLE)
        result = ed.preview(frame, opened["spec"], image="start_button.png", base=SAMPLE, seq=5)
    args = argparse.Namespace(
        target=str(root / SAMPLE),
        image=str(root / CAPTURES / "title.png"),
        window=None,
        hwnd=None,
        out=str(tmp_path / "preview.png"),
        json=True,
        all_scales=False,
    )
    out, err = io.StringIO(), io.StringIO()
    assert target_cmd.run(args, out, err) == target_cmd.EXIT_FOUND, err.getvalue()
    report = json.loads(out.getvalue())
    assert set(result) == PREVIEW_KEYS
    for key in PREVIEW_KEYS - {"elapsed_ms", "search_rect_px", "seq", "peaks"}:
        assert result[key] == report[key], key
    assert result["search_rect_px"] == report["search"] and result["seq"] == 5
    assert result["match"]["rect"] == list(START_BUTTON)


def test_preview_unsaved_spec_threshold_change(root: Path) -> None:
    with editor(root) as (_, ed):
        before = snapshot(root)
        one = ed.load(f"{CAPTURES}/pattern_one.png")
        faded = ed.load(f"{CAPTURES}/pattern_faded.png")
        rect = (*PATTERN_AT, *PATTERN)
        spec: dict[str, Any] = {"match": {"methods": ["template"], "rgb": False, "threshold": 0.99}}
        strict = ed.preview(faded, spec, crop=(one, rect))
        assert strict["found"] is False and strict["threshold"] == 0.99
        score = strict["best"]["score"]
        assert 0.3 < score < 0.99
        spec["match"]["threshold"] = round(score - 0.05, 2)
        loose = ed.preview(faded, spec, crop=(one, rect))
        assert loose["found"] is True and loose["threshold"] == spec["match"]["threshold"]
        assert loose["match"]["score"] == score and loose["match"]["rect"] == list(rect)
        assert snapshot(root) == before  # 미리보기는 파일을 쓰지 않는다


def test_preview_two_different_unsaved_crops_give_different_results(root: Path) -> None:
    with editor(root) as (_, ed):
        before = snapshot(root)
        frame = ed.load(f"{CAPTURES}/title.png")
        first = ed.preview(frame, crop=(frame, START_BUTTON))
        second = ed.preview(frame, crop=(frame, TITLE_TEXT))
        assert first["found"] and second["found"]
        assert first["match"]["rect"] == list(START_BUTTON)
        assert second["match"]["rect"] == list(TITLE_TEXT)
        assert snapshot(root) == before


def test_preview_seq_echoed(root: Path) -> None:
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        for seq in (0, 7, 2**53 - 1):
            assert ed.preview(frame, crop=(frame, START_BUTTON), seq=seq)["seq"] == seq
        # 늦게 온 응답을 버릴 수 있게 요청마다 그 요청의 seq를 돌려준다 (다른 영역이어도)
        rects = (START_BUTTON, TITLE_TEXT)
        results = [ed.preview(frame, crop=(frame, r), seq=i) for i, r in enumerate(rects)]
        assert [r["seq"] for r in results] == [0, 1]
        assert [r["match"]["rect"] for r in results] == [list(r) for r in rects]


@pytest.mark.parametrize("case", ["two", "one", "none"])
def test_preview_found_and_best_score(root: Path, case: str) -> None:
    with editor(root) as (_, ed):
        one = ed.load(f"{CAPTURES}/pattern_one.png")
        frame = ed.load(f"{CAPTURES}/pattern_{case}.png")
        result = ed.preview(frame, crop=(one, (*PATTERN_AT, *PATTERN)))
    # 결과 문구 = 찾음/못 찾음 + (최고) 점수. 화면 안 개수 같은 필드는 없다
    assert set(result) == PREVIEW_KEYS
    best = result["best"]
    assert best is not None
    if case == "none":
        assert result["found"] is False and result["match"] is None
        assert best["accepted"] is False and best["score"] < result["threshold"]
    else:
        match = result["match"]
        assert result["found"] is True and match["score"] >= result["threshold"]
        assert best["score"] == match["score"]
        spots = [[*PATTERN_AT, *PATTERN], [*PATTERN_AT2, *PATTERN]]
        assert match["rect"] in (spots if case == "two" else spots[:1])


# ---------------------------------------------------------------- 저장: 바로 매칭


def test_saved_target_matches_same_frame_immediately(root: Path) -> None:
    rel = "targets/editor/start.target.json"
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        saved = ed.save(rel, frame, START_BUTTON, {"match": {"threshold": 0.9}})
        preview = saved["preview"]
        assert preview["found"] is True and preview["threshold"] == 0.9
        assert preview["match"]["rect"] == list(START_BUTTON)
        assert preview["match"]["scale"] == 1.0 and preview["match"]["score"] >= 0.9
        assert saved["image"] == "targets/editor/start.png" and saved["warnings"] == []
        opened = ed.open(rel)
        assert opened["revision"] == saved["revision"] and opened["diagnostics"] == []
        assert opened["spec"]["recorded"] == {"client_size": [1024, 640], "dpi": 96}
    # 저장한 파일을 다시 읽어 찾아도 같다 (데몬 밖)
    target = load_target_file(root / rel)
    pixels = decode_image((root / CAPTURES / "title.png").read_bytes())
    found = Vision().find(pixels, FrameMeta.of_image(pixels), target)
    assert found.match is not None and found.match.rect == START_BUTTON
    assert (root / "targets/editor/start.png").read_bytes() == crop_png(root, START_BUTTON)
    assert [i["path"] for i in owned(root)] == ["targets/editor/start.png"]


def test_saved_target_with_repeated_pattern_found_only(root: Path) -> None:
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/pattern_two.png")
        saved = ed.save("targets/pat/p.target.json", frame, (*PATTERN_AT, *PATTERN))
    preview = saved["preview"]
    assert preview["found"] is True and preview["match"]["score"] >= preview["threshold"]


def test_saved_target_used_in_graph_run_passes(root: Path, tmp_path: Path) -> None:
    env = cli_env(tmp_path)
    service = WorkspaceService(
        root, environ=env, supervisor=Supervisor(runner_cmd=RUNNER_CMD, env=env)
    )
    rel = "targets/editor/start.target.json"
    graph = (
        GraphBuilder()
        .entry("n_launch")
        .node(
            "n_launch",
            "core.app.launch",
            inputs={"path": "SampleRPG", "window_title": "SampleRPG", "timeout_ms": 5000},
            next={"attached": "n_wait"},
        )
        .node(
            "n_wait",
            "core.image.wait",
            inputs={"target": target(rel), "timeout_ms": 5000},
            next={"found": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    graph.write(root, "tests/editor_target.graph.json")
    daemon = ThreadDaemon(root, service=service, platform_fake=root / "fake-platform.json")
    with daemon as d, d.client() as client:
        ed = Editor(client)
        frame = ed.load(f"{CAPTURES}/title.png")
        ed.save(rel, frame, START_BUTTON)
        started = client.call("run.start", {"path": "tests/editor_target.graph.json"})
        status = wait_until(
            lambda: (
                (s := client.call("run.status", {"run_id": started["run_id"]}))["state"] == "ended"
                and s
            ),
            timeout=90,
            interval=0.2,
        )
    assert status["outcome"]["verdict"] == "pass", status


# ---------------------------------------------------------------- 정규화 검색 범위


def test_region_roundtrip_pixels_exact(root: Path) -> None:
    rng = random.Random(20261031)
    sizes = [(1, 1), (7, 3), (1024, 640), (1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)]
    sizes += [(rng.randint(1, 8000), rng.randint(1, 8000)) for _ in range(30)]
    for cw, ch in sizes:
        for _ in range(40):
            x, y = rng.randint(0, cw - 1), rng.randint(0, ch - 1)
            w, h = rng.randint(1, cw - x), rng.randint(1, ch - y)
            region = pixels_to_normalized((x, y, w, h), (cw, ch))
            assert all(0 <= v <= 1 and round(v, 6) == v for v in region), region
            assert normalized_to_pixels(region, (cw, ch)) == (x, y, w, h), (cw, ch, region)
    # 저장: 렌더러가 보낸 정규화 값(픽셀 / 크기)을 같은 픽셀로 돌아오는 6자리 값으로 저장한다
    rect = (307, 313, 411, 177)  # 시작 버튼을 담는 범위 (저장한 대상은 바로 매칭돼야 한다)
    given = [rect[0] / 1024, rect[1] / 640, rect[2] / 1024, rect[3] / 640]
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        saved = ed.save(
            "targets/r/a.target.json", frame, START_BUTTON, {"search": {"region": given}}
        )
        assert saved["preview"]["search_rect_px"] == list(rect)
        assert saved["preview"]["match"]["rect"] == list(START_BUTTON)
    stored = json.loads((root / "targets/r/a.target.json").read_text("utf-8"))["search"]["region"]
    assert all(round(v, 6) == v for v in stored)
    assert normalized_to_pixels(tuple(stored), (1024, 640)) == rect


def test_save_existing_target_preserves_unknown_keys(root: Path) -> None:
    rel = "targets/keys/a.target.json"
    (root / "targets/keys").mkdir(parents=True)
    (root / "targets/keys/a.png").write_bytes(crop_png(root, START_BUTTON))
    write_target(
        root,
        rel,
        "a.png",
        sensitive=True,
        match={"color_tolerance": 25, "threshold": 0.85},
        click={"anchor": "top_left", "offset": [3, -2]},
        recorded={"client_size": [1024, 640], "dpi": 96},
    )
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        # 고치지 않고 같은 영역으로 저장: 같은 이름·같은 바이트 이미지를 재사용, JSON 원문 그대로
        mtime = old_mtime(root / rel)
        original = (root / rel).read_bytes()
        opened = ed.open(rel)
        same = ed.save(rel, frame, START_BUTTON, opened["spec"], opened["revision"])
        assert same["revision"] == opened["revision"]
        assert (root / rel).read_bytes() == original and (root / rel).stat().st_mtime_ns == mtime
        # 임계값만 바꿈: 손대지 않은 키는 그대로
        spec = opened["spec"]
        spec["match"]["threshold"] = 0.8
        ed.save(rel, frame, START_BUTTON, spec, opened["revision"])
    value = json.loads((root / rel).read_text("utf-8"))
    assert value["sensitive"] is True and value["match"] == {
        "color_tolerance": 25,
        "threshold": 0.8,
    }
    assert value["click"] == {"anchor": "top_left", "offset": [3, -2]} and value["image"] == "a.png"
    assert owned(root) == []  # 재사용한 파일은 소유가 아니다


# ---------------------------------------------------------------- 검수 H2: 실패한 저장
# 기존 target을 바꾸지 않는다


def test_stale_revision_rejected_before_any_write(root: Path) -> None:
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        stale = ed.open(SAMPLE)["revision"]
        body = json.loads((root / SAMPLE).read_text("utf-8"))
        body["match"] = {"threshold": 0.8}
        (root / SAMPLE).write_text(json.dumps(body), encoding="utf-8")
        check = keep_state(root, ed, frame, SAMPLE)
        before = snapshot(root)
        error = failure(lambda: ed.save(SAMPLE, frame, OTHER_RECT, body, stale))
        assert error.kind == "revision_conflict"
        assert error.data["revision"] == ed.open(SAMPLE)["revision"] != stale
        assert snapshot(root) == before  # 이미지 폴더 파일 목록·바이트 변화 없음
        assert owned(root) == []
        check()


def test_json_write_failure_keeps_old_target(root: Path) -> None:
    with editor(root) as (d, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        check = keep_state(root, ed, frame, SAMPLE)
        before = snapshot(root)
        opened = ed.open(SAMPLE)

        def broken(info: dict[str, Any]) -> None:
            raise OSError("주입한 쓰기 실패")

        d.daemon.targets.hooks["json_write"] = broken
        error = failure(
            lambda: ed.save(SAMPLE, frame, OTHER_RECT, opened["spec"], opened["revision"])
        )
        assert error.kind == "io_error"
        assert snapshot(root) == before  # 새로 만든 PNG도 되돌렸다
        assert owned(root) == []
        check()


def _connect(root: Path) -> DaemonClient:
    info = wait_until(lambda: read_session(root), timeout=30)
    assert info is not None
    return DaemonClient.connect(info.port, info.token)


def _kill_during_save(
    root: Path, tmp_path: Path, spawned: Spawned, point: str, code: int
) -> tuple[dict[str, Any], DaemonProcess]:
    """`point`에서 daemon이 죽는 저장 하나 (기존 target을 OTHER_RECT로).
    (그 전 open 결과, 프로세스)."""
    rules = [{"point": point, "role": "supervisor", "action": f"exit:{code}"}]
    env = faults_env(rules, daemon_env(tmp_path))
    proc = DaemonProcess.start(spawned, root, tmp_path / "d", env=env)
    assert proc.first_line()["status"] == "started", proc.output()
    with _connect(root) as client:
        ed = Editor(client)
        frame = ed.load(f"{CAPTURES}/title.png")
        opened = ed.open(SAMPLE)
        with pytest.raises(Exception):  # noqa: B017 (연결이 끊긴다)
            ed.save(SAMPLE, frame, OTHER_RECT, opened["spec"], opened["revision"])
    assert proc.wait() == code, proc.output()
    return opened, proc


def test_killed_after_image_write_leaves_only_orphan(
    root: Path, tmp_path: Path, spawned: Spawned
) -> None:
    before = snapshot(root)
    _kill_during_save(root, tmp_path, spawned, "target.before_commit", 91)
    after = snapshot(root)
    new = sorted(set(after) - set(before))
    png = crop_png(root, OTHER_RECT)
    assert new == [f"targets/title/start_button-{sha(png)[:8]}.png"]  # 고아 하나만
    assert {k: v for k, v in after.items() if k not in new} == before
    assert [i["path"] for i in owned(root)] == new  # 기록된 뒤에 죽었다
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        result = same_frame_match(ed, frame, SAMPLE)
        assert result["found"] and result["match"]["rect"] == list(START_BUTTON)


def test_shared_png_never_modified_other_target_unchanged(root: Path) -> None:
    folder = root / "targets/shared"
    folder.mkdir()
    (folder / "shared.png").write_bytes(crop_png(root, START_BUTTON))
    write_target(root, "targets/shared/a.target.json", "shared.png")
    write_target(root, "targets/shared/b.target.json", "shared.png")
    mtime = old_mtime(folder / "shared.png")
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        check_b = keep_state(root, ed, frame, "targets/shared/b.target.json")
        opened = ed.open("targets/shared/a.target.json")
        saved = ed.save(
            "targets/shared/a.target.json", frame, OTHER_RECT, opened["spec"], opened["revision"]
        )
        assert saved["image"] == "targets/shared/a.png"
        check_b()
    assert (folder / "shared.png").read_bytes() == crop_png(root, START_BUTTON)
    assert (folder / "shared.png").stat().st_mtime_ns == mtime


def test_image_only_external_change_is_conflict(root: Path) -> None:
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        opened = ed.open(SAMPLE)
        json_part = opened["revision"].split(":")[0]
        (root / "targets/title/start_button.png").write_bytes(crop_png(root, TITLE_TEXT))
        now = ed.open(SAMPLE)["revision"]
        assert now != opened["revision"] and now.split(":")[0] == json_part
        json_before = (root / SAMPLE).read_bytes()
        error = failure(
            lambda: ed.save(SAMPLE, frame, OTHER_RECT, opened["spec"], opened["revision"])
        )
        assert error.kind == "revision_conflict" and error.data["revision"] == now
        assert (root / SAMPLE).read_bytes() == json_before
        assert not list((root / "targets/title").glob("start_button-*.png"))


def test_new_target_existing_file_exists_error(root: Path) -> None:
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        before = snapshot(root)
        error = failure(lambda: ed.save(SAMPLE, frame, OTHER_RECT))
        assert error.kind == "exists" and error.data["revision"] == ed.open(SAMPLE)["revision"]
        assert snapshot(root) == before


def test_identical_png_reused_no_write_not_owned(root: Path) -> None:
    folder = root / "targets/reuse"
    folder.mkdir()
    (folder / "r.png").write_bytes(crop_png(root, START_BUTTON))
    mtime = old_mtime(folder / "r.png")
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        saved = ed.save("targets/reuse/r.target.json", frame, START_BUTTON)
    assert saved["image"] == "targets/reuse/r.png" and saved["preview"]["found"]
    assert (folder / "r.png").stat().st_mtime_ns == mtime
    assert sorted(p.name for p in folder.iterdir()) == ["r.png", "r.target.json"]
    assert owned(root) == []


# ---------------------------------------------------------------- 2차 검수 N2: 경쟁


class Gate:
    """저장소 훅 장벽: 처음 `count`번 지나는 호출을 멈춰 세운다."""

    def __init__(self, count: int = 1) -> None:
        self.count = count
        self.calls: list[dict[str, Any]] = []
        self.arrived = threading.Event()
        self.release = threading.Event()

    def __call__(self, info: dict[str, Any]) -> None:
        self.calls.append(info)
        if len(self.calls) <= self.count:
            self.arrived.set()
            assert self.release.wait(30), "장벽이 풀리지 않았다"


def run_in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, dict[str, Any]]:
    box: dict[str, Any] = {}

    def body() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=body)
    thread.start()
    return thread, box


@pytest.mark.parametrize("same_crop", [False, True], ids=["다른 crop", "같은 crop"])
def test_two_saves_same_new_target_race(root: Path, same_crop: bool) -> None:
    rel = "targets/race/a.target.json"
    rect_b = START_BUTTON if same_crop else OTHER_RECT
    with ThreadDaemon(root) as d, d.client() as ca, d.client() as cb:
        a, b = Editor(ca), Editor(cb)
        fa, fb = a.load(f"{CAPTURES}/title.png"), b.load(f"{CAPTURES}/title.png")
        checks: list[dict[str, Any]] = []
        d.daemon.targets.hooks["checks"] = checks.append
        gate = Gate()
        d.daemon.targets.hooks["publish"] = gate  # A를 이름 선택 지점에 세운다
        ta, ra = run_in_thread(lambda: a.save(rel, fa, START_BUTTON))
        assert gate.arrived.wait(30)
        tb, rb = run_in_thread(lambda: b.save(rel, fb, rect_b))
        # B는 잠금을 기다린다: 검사에도 이름 선택에도 들어가지 못한다
        threading.Event().wait(0.5)
        assert len(checks) == 1 and len(gate.calls) == 1
        gate.release.set()
        ta.join(30)
        tb.join(30)
        assert "error" not in ra, ra
        error = rb.get("error")
        assert isinstance(error, DaemonError) and error.kind == "exists", rb
        png = crop_png(root, START_BUTTON)
        assert (root / "targets/race/a.png").read_bytes() == png
        assert sorted(p.name for p in (root / "targets/race").iterdir()) == [
            "a.png",
            "a.target.json",
        ]
        result = same_frame_match(a, fa, rel)
        assert result["found"] and result["match"]["rect"] == list(START_BUTTON)
        assert [i["path"] for i in owned(root)] == ["targets/race/a.png"]


def test_external_file_created_between_check_and_publish_not_overwritten(root: Path) -> None:
    folder = root / "targets/ext"
    with editor(root) as (d, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        made: list[Path] = []

        def external(info: dict[str, Any]) -> None:
            if not made:  # 첫 후보 이름을 밖의 프로세스가 먼저 만든다
                path: Path = info["path"]
                path.write_bytes(b"external bytes")
                made.append(path)

        d.daemon.targets.hooks["publish"] = external
        saved = ed.save("targets/ext/a.target.json", frame, START_BUTTON)
        png = crop_png(root, START_BUTTON)
        assert [p.resolve() for p in made] == [(folder / "a.png").resolve()]
        assert (folder / "a.png").read_bytes() == b"external bytes"
        assert saved["image"] == f"targets/ext/a-{sha(png)[:8]}.png" and saved["preview"]["found"]
        assert (root / saved["image"]).read_bytes() == png


type Hook = Callable[[dict[str, Any]], None]


def _conflict_on_commit(root: Path, rel: str, extra: Hook | None = None) -> Hook:
    """커밋 직전에 밖에서 target JSON을 바꾸는(없으면 만드는) 훅 (`extra`는 그 전에 할 일)."""

    def hook(info: dict[str, Any]) -> None:
        if extra is not None:
            extra(info)
        path = root / rel
        body: dict[str, Any] = {"format": "kookabug.target/0", "image": "external.png"}
        if path.exists():
            body = json.loads(path.read_text("utf-8"))
        body["sensitive"] = True
        path.write_text(json.dumps(body), encoding="utf-8")

    return hook


def test_conflict_rollback_deletes_only_own_created_file(root: Path) -> None:
    folder = root / "targets/rb"
    rel = "targets/rb/a.target.json"
    with editor(root) as (d, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        first = ed.save(rel, frame, START_BUTTON)  # a.png: 에디터가 만든 파일
        (folder / "user.png").write_bytes(crop_png(root, TITLE_TEXT))  # 사용자 파일
        (folder / "b.png").write_bytes(crop_png(root, TITLE_TEXT))
        write_target(root, "targets/rb/b.target.json", "b.png")  # 다른 target이 가리키는 파일
        (folder / "c.png").write_bytes(crop_png(root, OTHER_RECT))  # 재사용될 파일
        keep = {n: (folder / n).read_bytes() for n in ("a.png", "user.png", "b.png", "c.png")}
        opened = ed.open(rel)
        created = f"targets/rb/a-{sha(crop_png(root, OTHER_RECT))[:8]}.png"
        seen: list[str] = []
        d.daemon.targets.hooks["before_commit"] = _conflict_on_commit(
            root, rel, lambda info: seen.append(info["image"])
        )
        error = failure(lambda: ed.save(rel, frame, OTHER_RECT, opened["spec"], opened["revision"]))
        assert error.kind == "revision_conflict"
        assert seen == [created] and not (root / created).exists()  # 직접 만든 파일만 지웠다
        assert json.loads((root / rel).read_text("utf-8"))["sensitive"] is True  # 밖의 변경 그대로
        # 새 target + 재사용한 파일: 충돌해도 재사용한 c.png는 남는다
        d.daemon.targets.hooks["before_commit"] = _conflict_on_commit(
            root, "targets/rb/c.target.json"
        )
        error = failure(lambda: ed.save("targets/rb/c.target.json", frame, OTHER_RECT))
        assert error.kind == "exists"
        assert {n: (folder / n).read_bytes() for n in keep} == keep
        assert [i["path"] for i in owned(root)] == [first["image"]]


def test_rollback_skips_file_now_referenced_by_other_target(root: Path) -> None:
    rel = "targets/rb/a.target.json"
    with editor(root) as (d, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        ed.save(rel, frame, START_BUTTON)
        opened = ed.open(rel)

        def point_other(info: dict[str, Any]) -> None:
            write_target(root, "targets/rb/other.target.json", info["image"].rsplit("/", 1)[1])

        d.daemon.targets.hooks["before_commit"] = _conflict_on_commit(root, rel, point_other)
        error = failure(lambda: ed.save(rel, frame, OTHER_RECT, opened["spec"], opened["revision"]))
        assert error.kind == "revision_conflict"
        created = root / f"targets/rb/a-{sha(crop_png(root, OTHER_RECT))[:8]}.png"
        assert created.read_bytes() == crop_png(root, OTHER_RECT)  # 가리키는 target이 있어 남김
        assert [i["path"] for i in owned(root)] == ["targets/rb/a.png"]  # 그 기록 항목은 정리


def test_rollback_skips_file_changed_after_write(root: Path) -> None:
    rel = "targets/rb/a.target.json"
    with editor(root) as (d, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        ed.save(rel, frame, START_BUTTON)
        opened = ed.open(rel)

        def touch_image(info: dict[str, Any]) -> None:
            (root / info["image"]).write_bytes(b"changed by a person")

        d.daemon.targets.hooks["before_commit"] = _conflict_on_commit(root, rel, touch_image)
        error = failure(lambda: ed.save(rel, frame, OTHER_RECT, opened["spec"], opened["revision"]))
        assert error.kind == "revision_conflict"
        created = root / f"targets/rb/a-{sha(crop_png(root, OTHER_RECT))[:8]}.png"
        assert created.read_bytes() == b"changed by a person"
        assert [i["path"] for i in owned(root)] == ["targets/rb/a.png"]


def test_write_failure_mid_png_removes_only_that_file(root: Path) -> None:
    with editor(root) as (d, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        check = keep_state(root, ed, frame, SAMPLE)
        before = snapshot(root)
        opened = ed.open(SAMPLE)
        written: list[Path] = []

        def broken(info: dict[str, Any]) -> None:
            written.append(info["path"])
            assert info["path"].exists()  # 이 요청이 만든 파일이 있는 상태에서 실패한다
            raise OSError("주입한 쓰기 실패")

        d.daemon.targets.hooks["image_write"] = broken
        error = failure(
            lambda: ed.save(SAMPLE, frame, OTHER_RECT, opened["spec"], opened["revision"])
        )
        assert error.kind == "io_error" and len(written) == 1
        assert not written[0].exists()
        assert snapshot(root) == before and owned(root) == []
        check()


# ---------------------------------------------------------------- 2차 검수 N1: 사용자 PNG 보존


def test_user_png_never_deleted_when_target_repointed(root: Path) -> None:
    folder = root / "targets/user"
    folder.mkdir()
    (folder / "source.png").write_bytes(crop_png(root, START_BUTTON))
    write_target(root, "targets/user/a.target.json", "source.png")
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        opened = ed.open("targets/user/a.target.json")
        saved = ed.save(
            "targets/user/a.target.json", frame, OTHER_RECT, opened["spec"], opened["revision"]
        )
    assert saved["image"] == "targets/user/a.png" and saved["warnings"] == []
    # 이제 어떤 target도 source.png를 가리키지 않지만 사용자 파일이라 남는다
    assert (folder / "source.png").read_bytes() == crop_png(root, START_BUTTON)


def test_other_tool_source_png_kept(root: Path) -> None:
    folder = root / "targets/tool"
    folder.mkdir()
    (folder / "raw.png").write_bytes((root / CAPTURES / "title.png").read_bytes())
    raw = snapshot(folder)
    captures = snapshot(root / CAPTURES)
    with editor(root) as (_, ed):
        frame = ed.load("targets/tool/raw.png")  # 정지 화면으로 쓴 원본 (target 밖 용도)
        rel = "targets/tool/t.target.json"
        ed.save(rel, frame, START_BUTTON)
        opened = ed.open(rel)
        ed.save(rel, frame, OTHER_RECT, opened["spec"], opened["revision"])
    assert {k: v for k, v in snapshot(folder).items() if k == "raw.png"} == raw
    assert snapshot(root / CAPTURES) == captures


def test_shared_png_kept_when_one_target_repointed(root: Path) -> None:
    rel = "targets/sh/a.target.json"
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        ed.save(rel, frame, START_BUTTON)  # 에디터가 만든 a.png
        write_target(root, "targets/sh/b.target.json", "a.png")  # 다른 target도 가리킨다
        opened = ed.open(rel)
        ed.save(rel, frame, OTHER_RECT, opened["spec"], opened["revision"])
        assert (root / "targets/sh/a.png").read_bytes() == crop_png(root, START_BUTTON)
        assert same_frame_match(ed, frame, "targets/sh/b.target.json")["found"]
    assert "targets/sh/a.png" in [i["path"] for i in owned(root)]


def test_editor_created_unreferenced_image_cleaned(root: Path) -> None:
    rel = "targets/clean/a.target.json"
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        ed.save(rel, frame, START_BUTTON)
        opened = ed.open(rel)
        saved = ed.save(rel, frame, OTHER_RECT, opened["spec"], opened["revision"])
    new = f"targets/clean/a-{sha(crop_png(root, OTHER_RECT))[:8]}.png"
    assert saved["image"] == new and saved["warnings"] == []
    assert not (root / "targets/clean/a.png").exists()
    assert [i["path"] for i in owned(root)] == [new]


def test_editor_created_but_modified_by_user_kept(root: Path) -> None:
    rel = "targets/mod/a.target.json"
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        ed.save(rel, frame, START_BUTTON)
        (root / "targets/mod/a.png").write_bytes(crop_png(root, TITLE_TEXT))  # 사람이 바꿈
        opened = ed.open(rel)
        ed.save(rel, frame, OTHER_RECT, opened["spec"], opened["revision"])
    assert (root / "targets/mod/a.png").read_bytes() == crop_png(root, TITLE_TEXT)


@pytest.mark.parametrize("record", [b"not json", b'{"format": "other", "images": []}'])
def test_corrupt_ownership_record_means_no_cleanup(root: Path, record: bytes) -> None:
    rel = "targets/corrupt/a.target.json"
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        ed.save(rel, frame, START_BUTTON)
        (root / OWNERSHIP).write_bytes(record)
        opened = ed.open(rel)
        saved = ed.save(rel, frame, OTHER_RECT, opened["spec"], opened["revision"])
    assert (root / "targets/corrupt/a.png").exists()  # 소유를 증명할 수 없어 남긴다
    assert [i["path"] for i in owned(root)] == [saved["image"]]  # 기록은 새로 썼다


def test_killed_before_record_orphan_never_auto_deleted(
    root: Path, tmp_path: Path, spawned: Spawned
) -> None:
    before = snapshot(root)
    _kill_during_save(root, tmp_path, spawned, "target.before_record", 92)
    orphan = f"targets/title/start_button-{sha(crop_png(root, OTHER_RECT))[:8]}.png"
    assert sorted(set(snapshot(root)) - set(before)) == [orphan]
    assert owned(root) == []  # 기록하기 전에 죽었다
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        opened = ed.open(SAMPLE)
        saved = ed.save(SAMPLE, frame, TITLE_TEXT, opened["spec"], opened["revision"])
        opened = ed.open(SAMPLE)
        ed.save(SAMPLE, frame, START_BUTTON, opened["spec"], opened["revision"])
    assert (root / orphan).read_bytes() == crop_png(root, OTHER_RECT)  # 자동으로 지우지 않는다
    assert not (root / saved["image"]).exists()  # 에디터가 만들고 기록한 파일은 정리된다


def test_without_platform_package_platform_unavailable(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """daemon은 kookabug-platform을 의존성으로 두지 않는다 (CLI와 같은 선택 설치). 없으면 target
    메서드는 `platform_unavailable`이고 아무것도 쓰지 않는다."""
    with editor(root) as (_, ed):
        before = snapshot(root)
        monkeypatch.setitem(sys.modules, "kookabug_platform.vision", None)
        calls: list[Callable[[], Any]] = [
            lambda: ed.load(f"{CAPTURES}/title.png"),
            lambda: ed.open(SAMPLE),
            lambda: ed.client.call("windows.list", {}),
        ]
        for call in calls:
            assert failure(call).kind == "platform_unavailable"
        assert snapshot(root) == before


# ---------------------------------------------------------------- T6 검수 1
# 참조를 다 못 읽으면 지우지 않는다


@pytest.mark.parametrize("how", ["잠김", "JSON 아님"])
def test_unreadable_other_target_keeps_shared_image(root: Path, how: str) -> None:
    rel = "targets/lock/a.target.json"
    other = root / "targets/lock/b.target.json"
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        first = ed.save(rel, frame, START_BUTTON)  # 에디터가 만든 a.png
        shared = root / first["image"]
        shared_bytes = shared.read_bytes()
        write_target(root, "targets/lock/b.target.json", shared.name)  # b도 a.png를 가리킨다
        if how == "JSON 아님":
            other.write_bytes(b'{"format": "kookabug.target/0", "image": "a.png"')  # 쓰는 중
            saved = ed.save(rel, frame, OTHER_RECT, base_revision=first["revision"])
        else:
            with locked_file(other):
                saved = ed.save(rel, frame, OTHER_RECT, base_revision=first["revision"])
        # 저장은 성공하지만 b의 참조를 확인할 수 없으므로 a.png를 지우지 않고 알린다
        assert saved["image"] != first["image"]
        assert shared.read_bytes() == shared_bytes
        assert len(saved["warnings"]) == 1 and "b.target.json" in saved["warnings"][0]
        assert first["image"] in [i["path"] for i in owned(root)]  # 기록도 남는다
        # 다 읽을 수 있게 되고 b가 더는 a.png를 가리키지 않으면 다음 저장이 정리한다
        other.unlink()
        opened = ed.open(rel)
        ed.save(rel, frame, START_BUTTON, opened["spec"], opened["revision"])
        assert not (root / saved["image"]).exists()


def _two_owned_old_images(
    root: Path, ed: Editor, frame: dict[str, Any], rel: str
) -> dict[str, Any]:
    """a가 만든 이미지 두 개(옛 이미지 + 같은 target의 기록된 고아)를 남긴 저장 결과.

    첫 저장(a.png)을 b가 가리키게 해 두 번째 저장의 정리가 a.png를 남기게 한 뒤 b를 지운다."""
    first = ed.save(rel, frame, START_BUTTON)
    write_target(root, "targets/two/b.target.json", Path(first["image"]).name)
    second = ed.save(rel, frame, OTHER_RECT, base_revision=first["revision"])
    (root / "targets/two/b.target.json").unlink()
    paths = sorted(i["path"] for i in owned(root))
    assert paths == sorted([first["image"], second["image"]])
    return second


@pytest.mark.parametrize("change", ["참조 추가", "읽기 실패"])
def test_reference_change_between_cleanup_candidates(root: Path, change: str) -> None:
    """정리는 후보마다 지우기 직전에 참조를 다시 읽는다 (T6 2차 검수). 앞 후보를 지운 사이에 밖에서
    뒤 후보를 가리키는 target이 생기면 그 후보를 남기고, 참조를 읽지 못하게 되면 그 뒤를 멈춘다."""
    rel = "targets/two/a.target.json"
    with editor(root) as (d, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        second = _two_owned_old_images(root, ed, frame, rel)
        old = [root / i["path"] for i in owned(root)]
        before = {p: p.read_bytes() for p in old}
        deleted: list[Path] = []

        def after_first_delete(info: dict[str, Any]) -> None:
            deleted.append(info["path"])
            if len(deleted) > 1:
                return
            survivor = next(p for p in old if p.resolve() != info["path"].resolve())
            body = survivor.name if change == "참조 추가" else None
            if body is not None:
                write_target(root, "targets/two/c.target.json", body)  # 밖의 프로세스처럼
            else:
                (root / "targets/two/c.target.json").write_bytes(b'{"format": ')  # 쓰는 중

        d.daemon.targets.hooks["deleted"] = after_first_delete
        third = ed.save(rel, frame, TITLE_TEXT, base_revision=second["revision"])
        assert len(deleted) == 1  # 하나만 지웠다
        survivor = next(p for p in old if p.resolve() != deleted[0].resolve())
        assert survivor.read_bytes() == before[survivor]
        recorded = [i["path"] for i in owned(root)]
        assert third["image"] in recorded and len(recorded) == 2  # 남은 이미지 기록도 그대로
        if change == "읽기 실패":
            assert len(third["warnings"]) == 1 and "c.target.json" in third["warnings"][0]
        else:
            assert third["warnings"] == []


def test_rollback_with_unreadable_other_target_keeps_created_file(root: Path) -> None:
    rel = "targets/lock/a.target.json"
    other = root / "targets/lock/z.target.json"
    with editor(root) as (d, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        ed.save(rel, frame, START_BUTTON)
        write_target(root, "targets/lock/z.target.json", "unrelated.png")
        opened = ed.open(rel)
        d.daemon.targets.hooks["before_commit"] = _conflict_on_commit(root, rel)
        with locked_file(other):
            error = failure(
                lambda: ed.save(rel, frame, OTHER_RECT, opened["spec"], opened["revision"])
            )
        assert error.kind == "revision_conflict"  # 원래 실패를 그대로 돌려준다
        created = f"targets/lock/a-{sha(crop_png(root, OTHER_RECT))[:8]}.png"
        assert (root / created).read_bytes() == crop_png(root, OTHER_RECT)  # 지우지 않았다
        assert created in [i["path"] for i in owned(root)]  # 다음 저장의 정리가 다시 본다


# ---------------------------------------------------------------- T6 검수 2·3: 실패는 쓰기 전에


def test_large_click_offset_rejected_before_any_write(root: Path) -> None:
    rel = "targets/big/a.target.json"
    spec = {"click": {"offset": [1e20, 0]}}
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        first = ed.save(rel, frame, START_BUTTON)
        before = snapshot(root)
        record = (root / OWNERSHIP).read_bytes()
        error = failure(lambda: ed.save(rel, frame, OTHER_RECT, spec, first["revision"]))
        # 응답 검사(-32603)까지 가지 않고 사양 오류, 파일·기록은 그대로
        assert error.kind == "target_invalid" and error.data["diagnostics"]
        assert snapshot(root) == before and (root / OWNERSHIP).read_bytes() == record
        assert ed.open(rel)["revision"] == first["revision"]
        # 새 target도 같다 (폴더도 만들지 않는다)
        error = failure(lambda: ed.save("targets/big2/a.target.json", frame, START_BUTTON, spec))
        assert error.kind == "target_invalid" and not (root / "targets/big2").exists()
        # 미리보기도 같은 사양 오류로 답한다
        error = failure(lambda: ed.preview(frame, spec, crop=(frame, START_BUTTON)))
        assert error.kind == "target_invalid"


def test_crop_not_found_with_spec_rejected_before_write(root: Path) -> None:
    rel = "targets/miss/a.target.json"
    outside = {"search": {"region": [0, 0, 0.1, 0.1]}}  # 시작 버튼이 없는 범위
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        before = snapshot(root)
        error = failure(lambda: ed.save(rel, frame, START_BUTTON, outside))
        assert error.kind == "target_invalid" and "찾지 못한다" in error.message
        assert snapshot(root) == before and not (root / "targets/miss").exists()
        # 기존 target도 그대로 (JSON·이미지·같은 정지 화면 매칭)
        check = keep_state(root, ed, frame, SAMPLE)
        opened = ed.open(SAMPLE)
        spec = {**opened["spec"], **outside}
        error = failure(lambda: ed.save(SAMPLE, frame, OTHER_RECT, spec, opened["revision"]))
        assert error.kind == "target_invalid"
        assert not list((root / "targets/title").glob("start_button-*.png"))
        check()


def test_cleanup_failure_after_commit_is_warning(root: Path) -> None:
    rel = "targets/warn/a.target.json"
    with editor(root) as (d, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        first = ed.save(rel, frame, START_BUTTON)

        def broken(*args: Any) -> list[str]:
            raise OSError("주입한 정리 실패")

        setattr(d.daemon.targets, "_cleanup", broken)  # noqa: B010 (비공개 단계를 바꿔 끼운다)
        saved = ed.save(rel, frame, OTHER_RECT, base_revision=first["revision"])
        assert saved["preview"]["found"] and saved["warnings"]
        assert "주입한 정리 실패" in saved["warnings"][0]
        assert ed.open(rel)["revision"] == saved["revision"]  # 커밋은 됐다
        assert (root / first["image"]).exists()


# ---------------------------------------------------------------- crop 없는 저장 (조율자 결정)


def save_spec_only(
    ed: Editor, path: str, spec: dict[str, Any], base_revision: str | None
) -> dict[str, Any]:
    params = {"path": path, "spec": spec, "base_revision": base_revision}
    return ed.client.call("target.save", params)


def test_save_without_crop_keeps_image_bytes_changes_json_only(root: Path) -> None:
    folder = root / "targets/title"
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        images = {p.name: p.read_bytes() for p in folder.glob("*.png")}
        image_mtime = old_mtime(folder / "start_button.png")
        opened = ed.open(SAMPLE)
        spec = opened["spec"]
        # 렌더러가 보낸 recorded·image는 쓰지 않는다 (지금 파일 값 그대로)
        spec["recorded"] = {"client_size": [10, 10], "dpi": 300}
        spec["image"] = "other.png"
        spec["match"] = {"threshold": 0.7}
        spec["search"] = {"region": [412 / 1024, 380 / 640, 200 / 1024, 64 / 640]}
        saved = save_spec_only(ed, SAMPLE, spec, opened["revision"])
        assert saved["preview"] is None and saved["warnings"] == []
        assert saved["image"] == "targets/title/start_button.png"
        value = json.loads((root / SAMPLE).read_text("utf-8"))
        assert value["image"] == "start_button.png"
        assert value["recorded"] == {"client_size": [1024, 640], "dpi": 96}
        assert value["match"] == {"threshold": 0.7}
        region = tuple(value["search"]["region"])
        assert normalized_to_pixels(region, (1024, 640)) == (412, 380, 200, 64)
        assert all(round(v, 6) == v for v in region)
        # 이미지 파일은 하나도 바뀌지 않았다 (바이트·mtime·목록)
        assert {p.name: p.read_bytes() for p in folder.glob("*.png")} == images
        assert (folder / "start_button.png").stat().st_mtime_ns == image_mtime
        assert owned(root) == []
        reopened = ed.open(SAMPLE)
        assert saved["revision"] == reopened["revision"]
        assert reopened["revision"].split(":")[1] == opened["revision"].split(":")[1]
        result = same_frame_match(ed, frame, SAMPLE)
        assert result["found"] and result["threshold"] == 0.7
        # 같은 사양으로 다시 저장하면 쓰지 않는다
        mtime = old_mtime(root / SAMPLE)
        again = save_spec_only(ed, SAMPLE, reopened["spec"], reopened["revision"])
        assert again["revision"] == reopened["revision"]
        assert (root / SAMPLE).stat().st_mtime_ns == mtime


def test_save_without_crop_missing_image_is_error(root: Path) -> None:
    with editor(root) as (_, ed):
        # 지금 이미지가 없다: 아무것도 쓰지 않고 target_invalid
        (root / "targets/title/start_button.png").unlink()
        opened = ed.open(SAMPLE)
        assert opened["revision"].endswith(":missing")
        before = snapshot(root)
        error = failure(lambda: save_spec_only(ed, SAMPLE, opened["spec"], opened["revision"]))
        assert error.kind == "target_invalid"
        assert error.data["diagnostics"][0]["pointer"] == "/image"
        # 이미지가 아닌 파일
        (root / "targets/title/start_button.png").write_bytes(b"not a png")
        opened = ed.open(SAMPLE)
        error = failure(lambda: save_spec_only(ed, SAMPLE, opened["spec"], opened["revision"]))
        assert error.kind == "target_invalid"
        assert {k: v for k, v in snapshot(root).items() if not k.endswith(".png")} == {
            k: v for k, v in before.items() if not k.endswith(".png")
        }
        # 새 target은 crop이 있어야 한다, 낡은 revision은 그대로 충돌
        new = failure(lambda: save_spec_only(ed, "targets/n/new.target.json", {}, None))
        assert new.kind == "target_invalid" and not (root / "targets/n").exists()
        stale = failure(lambda: save_spec_only(ed, SAMPLE, opened["spec"], "0" * 64 + ":missing"))
        assert stale.kind == "revision_conflict"
        assert owned(root) == []


# ---------------------------------------------------------------- 경로


def test_save_path_rules(root: Path) -> None:
    with editor(root) as (_, ed):
        frame = ed.load(f"{CAPTURES}/title.png")
        before = snapshot(root)
        assert failure(lambda: ed.save("tests/a.target.json", frame, START_BUTTON)).code == -32602
        assert failure(lambda: ed.save("targets/a.json", frame, START_BUTTON)).code == -32602
        assert failure(lambda: ed.save(".kookabug/a.target.json", frame, START_BUTTON)).kind == (
            "private_path"
        )
        assert failure(lambda: ed.save("../a.target.json", frame, START_BUTTON)).kind == (
            "path_outside_workspace"
        )
        bad = failure(lambda: ed.save("targets/a.target.json", frame, (1000, 600, 100, 100)))
        assert bad.kind == "target_invalid"
        bad = failure(
            lambda: ed.save("targets/a.target.json", frame, START_BUTTON, {"match": {"rgb": 1}})
        )
        assert bad.kind == "target_invalid" and bad.data["diagnostics"]
        assert snapshot(root) == before
