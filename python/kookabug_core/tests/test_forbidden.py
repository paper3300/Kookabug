"""금지 동작 판정 함수 `forbidden.judge` (M8 계획 3.7·9장 R6) — 판정 규칙 단위 검사.

daemon 제어 입력·runner 입력이 모두 이 함수를 부른다 (실제 경로 검사는 daemon `test_forbidden.py`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kookabug_core import forbidden
from kookabug_core.forbidden import Item, Unverifiable, judge


class FakeSight:
    def __init__(
        self,
        *,
        text: str = "",
        targets: dict[str, bool] | None = None,
        screens: dict[str, bool] | None = None,
        protected: str | None = None,
        ocr_error: Exception | None = None,
    ) -> None:
        self._text = text
        self._targets = targets or {}
        self._screens = screens or {}
        self._protected = protected
        self._ocr_error = ocr_error
        self.ocr_calls = 0

    def protected(self) -> str | None:
        return self._protected

    def screen_matches(self, screen_id: str) -> bool:
        if screen_id not in self._screens:
            raise Unverifiable("screen_unknown")
        return self._screens[screen_id]

    def target_visible(self, rel: str) -> bool:
        if rel not in self._targets:
            raise RuntimeError("읽을 수 없다")
        return self._targets[rel]

    def text(self) -> str:
        self.ocr_calls += 1
        if self._ocr_error is not None:
            raise self._ocr_error
        return forbidden.normalize(self._text)


TEXT = Item("text", "결제")
TARGET = Item("target", "targets/shop/pay.target.json")
SCREEN = Item("screen", "payment")


def test_empty_list_skips_check() -> None:
    assert judge((), None) is None


def test_text_visible_anywhere_refuses_space_case_insensitive() -> None:
    refusal = judge((TEXT,), FakeSight(text="정말 결 제 할까요?"))
    assert refusal is not None
    assert (refusal.code, refusal.kind, refusal.value) == ("forbidden_visible", "text", "결제")
    assert judge((Item("text", "Pay Now"),), FakeSight(text="please PAYNOW")) is not None
    assert judge((TEXT,), FakeSight(text="골드 12,345")) is None


def test_target_click_refused() -> None:
    refusal = judge((TARGET,), FakeSight(targets={TARGET.value: True}))
    assert refusal is not None and (refusal.code, refusal.kind) == ("forbidden_visible", "target")
    assert judge((TARGET,), FakeSight(targets={TARGET.value: False})) is None


def test_screen_refuses_all_input() -> None:
    refusal = judge((SCREEN,), FakeSight(screens={"payment": True}))
    assert refusal is not None and refusal.kind == "screen"
    assert judge((SCREEN,), FakeSight(screens={"payment": False})) is None


def test_screen_identify_failure_refuses() -> None:
    refusal = judge((SCREEN,), FakeSight())
    assert refusal is not None
    assert (refusal.code, refusal.reason) == ("forbidden_unverifiable", "screen_unknown")
    refusal = judge((TARGET,), FakeSight())
    assert refusal is not None and refusal.code == "forbidden_unverifiable"
    assert refusal.reason.startswith("target_unverified")


def test_ocr_unavailable_refuses() -> None:
    refusal = judge((TEXT,), FakeSight(ocr_error=Unverifiable("ocr_unavailable")))
    assert refusal is not None
    assert (refusal.code, refusal.reason) == ("forbidden_unverifiable", "ocr_unavailable")
    refusal = judge((TEXT,), FakeSight(ocr_error=OSError("모델 없음")))
    assert refusal is not None and refusal.reason == "ocr_failed:OSError"
    # 프레임이 없으면 (창 없음·캡처 실패) 확인 못 함
    refusal = judge((TEXT,), None)
    assert refusal is not None and (refusal.code, refusal.reason) == (
        "forbidden_unverifiable",
        "no_frame",
    )


def test_protected_frame_refuses() -> None:
    sight = FakeSight(text="아무 글자", protected="secret_field_unknown")
    refusal = judge((TEXT,), sight)
    assert refusal is not None
    assert (refusal.code, refusal.reason) == ("forbidden_unverifiable", "secret_field_unknown")
    assert sight.ocr_calls == 0  # 보호 화면의 글자는 읽지 않는다


def test_visible_beats_unverifiable() -> None:
    refusal = judge((SCREEN, TEXT), FakeSight(text="결제"))
    assert refusal is not None and refusal.code == "forbidden_visible"


def test_refusal_has_no_screen_text() -> None:
    secretish = "비밀문구XYZ987"
    refusal = judge((TEXT,), FakeSight(text=f"{secretish} 결제"))
    assert refusal is not None
    blob = json.dumps({"m": refusal.message(), **refusal.fields()}, ensure_ascii=False)
    assert secretish not in blob and "결제" in blob


class RecordingSink:
    """입력 액터 자리: 장면보다 먼저 받는 입력을 기록한다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def click(self, at: Any, **_: Any) -> None:
        self.calls.append(("click", f"{at.x},{at.y}"))

    def key(self, key: str, **_: Any) -> None:
        self.calls.append(("key", key))

    def press(self, key: str, **_: Any) -> None:
        self.calls.append(("press", key))

    def release(self, key: str, **_: Any) -> None:
        self.calls.append(("release", key))

    def type_text(self, text: Any, **_: Any) -> None:
        self.calls.append(("type", "?"))

    def drag(self, *_: Any, **__: Any) -> None:
        self.calls.append(("drag", ""))

    def scroll(self, *_: Any, **__: Any) -> None:
        self.calls.append(("scroll", ""))


def test_supervisor_release_not_blocked(tmp_path: Path) -> None:
    """판정은 누르기·클릭·글자 **전**에만 한다. 누르고 있기의 떼기(입력 서비스 안)와 감독자·입력
    액터의 모두 떼기·복구는 판정을 거치지 않는다 — 판정이 그 사이 거부로 바뀌어도 키가 눌린 채
    남지 않는다."""
    from helpers.graphs import make_workspace
    from helpers.m1 import ScenePlatform
    from helpers.run import tk
    from testkit import registry_with_testkit

    from kookabug_core.engine import ExecOptions, Executor, FakeClock, MemoryArtifacts
    from kookabug_core.engine.errors import EngineError
    from kookabug_core.loader import load_program

    ws = make_workspace(tmp_path)
    platform = ScenePlatform.sample()
    sink = RecordingSink()
    platform.attach_input(sink)  # type: ignore[arg-type]
    calls: list[int] = []

    def guard(window: Any) -> None:
        calls.append(len(sink.calls))
        if len(calls) > 2:
            raise EngineError("forbidden_visible", "금지 동작이 보여 입력하지 않았다")

    g = (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_tap"})
        .node("n_tap", "testkit.input.tap", inputs={"x": 512, "y": 412}, next={"done": "n_hold"})
        .node(
            "n_hold",
            "core.input.key",
            inputs={"keys": "shift", "hold_ms": 50},
            next={"done": "n_tap2"},
        )
        .node("n_tap2", "testkit.input.tap", inputs={"x": 1, "y": 1}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    g.write(ws, "tests/t.graph.json")
    program = load_program(ws, "tests/t.graph.json")
    executor = Executor(
        registry_with_testkit(), platform=platform, clock=FakeClock(), artifacts=MemoryArtifacts()
    )
    result = executor.run(program, ExecOptions(run_id="r1", input_guard=guard))
    # 판정은 탭·누르기 전 두 번, 세 번째(탭2)에서 거부 — 떼기는 판정 없이 갔다
    assert calls == [0, 1, 3]
    assert sink.calls == [("click", "512,412"), ("press", "shift"), ("release", "shift")]
    assert (result.verdict, result.code) == ("error", "forbidden_visible")


def test_protected_paths_normalized(tmp_path: Path) -> None:
    """금지 target·PNG·화면 판정 target은 쓰기 쪽과 같은 정규화로 막힌다 (`./`·대소문자)."""
    from kookabug_core.adopt import path_key

    (tmp_path / "kookabug.json").write_text(json.dumps({"format": "kookabug.workspace/0"}))
    folder = tmp_path / "targets" / "shop"
    folder.mkdir(parents=True)
    (folder / "pay.target.json").write_text(json.dumps({"image": "../img/pay.png"}))
    (tmp_path / "screens").mkdir()
    (tmp_path / "screens" / "payment.screen.json").write_text(
        json.dumps({"detect": {"all": [{"$target": "targets/shop/pay.target.json"}]}})
    )
    got = forbidden.protected_paths(
        tmp_path, (Item("target", "targets/./shop/pay.target.json"), Item("screen", "payment"))
    )
    assert path_key("targets/shop/pay.target.json") in got
    assert path_key("targets/img/pay.png") in got
    assert path_key("screens/payment.screen.json") in got


def test_load_items_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "kookabug.json").write_text(
        json.dumps({"automation": {"forbidden": [{"kind": "text"}]}}), encoding="utf-8"
    )
    with pytest.raises(forbidden.ForbiddenConfigError):
        forbidden.load_items(tmp_path)
    (tmp_path / "kookabug.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(forbidden.ForbiddenConfigError):
        forbidden.load_items(tmp_path)
    (tmp_path / "kookabug.json").write_text(
        json.dumps(
            {
                "automation": {
                    "forbidden": [
                        {"kind": "text", "value": "결제"},
                        {"kind": "target", "path": "targets/a.target.json"},
                        {"kind": "screen", "id": "payment"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    assert forbidden.load_items(tmp_path) == (
        Item("text", "결제"),
        Item("target", "targets/a.target.json"),
        Item("screen", "payment"),
    )
    (tmp_path / "kookabug.json").write_text(json.dumps({}), encoding="utf-8")
    assert forbidden.load_items(tmp_path) == ()


@pytest.mark.parametrize("native", [True, False])
def test_real_key_missing_vs_unresolvable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native: bool
) -> None:
    """없는 파일(새로 만들 파일)은 풀고, 링크 순환은 `UnresolvablePath`. `ALLOW_MISSING`이 없는
    Python의 직접 구현(`native=False`)도 같은 의미다. 정션 별칭은 실제 경로 키로 같다."""
    import os
    import subprocess

    if not native:
        monkeypatch.delattr(os.path, "ALLOW_MISSING", raising=False)
    (tmp_path / "targets" / "shop").mkdir(parents=True)
    (tmp_path / "targets" / "shop" / "buy.target.json").write_text("{}")
    loop = tmp_path / "targets" / "loop"
    alias = tmp_path / "targets" / "alias"
    for link, to in ((loop, loop), (alias, tmp_path / "targets" / "shop")):
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(to)], capture_output=True
        )
        assert made.returncode == 0, made.stderr
    try:
        assert (
            forbidden.real_key(tmp_path, "targets/new/a.target.json") == "targets/new/a.target.json"
        )
        assert forbidden.real_key(tmp_path, "targets/alias/buy.target.json") == (
            "targets/shop/buy.target.json"
        )
        assert forbidden.real_key(tmp_path, "targets/alias/new.target.json") == (
            "targets/shop/new.target.json"
        )
        for rel in ("targets/loop/pay.target.json", "targets/loop"):
            with pytest.raises(forbidden.UnresolvablePath):
                forbidden.real_key(tmp_path, rel)
        with pytest.raises(forbidden.UnresolvablePath):
            forbidden.real_key(loop, "a.json")  # 루트 해석도 같은 정책
        with pytest.raises(forbidden.UnresolvablePath):
            forbidden.real_key(tmp_path, "../outside.json")
    finally:
        os.rmdir(loop)
        os.rmdir(alias)


def test_protected_paths_unreadable_target_fails_closed(tmp_path: Path) -> None:
    """금지 target·화면 파일을 읽지 못하면 보호 목록을 비우지 않는다. 목록이 비면 빈 집합."""
    (tmp_path / "kookabug.json").write_text(json.dumps({"format": "kookabug.workspace/0"}))
    with pytest.raises(forbidden.UnresolvablePath):
        forbidden.protected_paths(tmp_path, (Item("target", "targets/none.target.json"),))
    (tmp_path / "targets").mkdir()
    (tmp_path / "targets" / "bad.target.json").write_text("[1]")
    with pytest.raises(forbidden.UnresolvablePath):
        forbidden.protected_paths(tmp_path, (Item("target", "targets/bad.target.json"),))
    assert forbidden.protected_paths(tmp_path, ()) == set()


def test_single_run_entry_point() -> None:
    """실행 시작(감독자 `start`)은 공용 진입점 `WorkspaceService.start_decided` 한 곳에서만 부른다 —
    CLI·daemon·제어·검증 실행이 모두 거기서 주체별 금지 목록을 받는다 (옆 경로 없음)."""
    import ast

    from kb_testing.packaging import REPO_ROOT

    found: list[str] = []
    for path in sorted((REPO_ROOT / "python").glob("*/src/**/*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "start"
            ):
                continue
            owner = node.func.value  # `x.supervisor.start(...)`·`supervisor.start(...)` 꼴
            name = (
                owner.attr
                if isinstance(owner, ast.Attribute)
                else owner.id
                if isinstance(owner, ast.Name)
                else ""
            )
            if "supervisor" in name.casefold():
                found.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}")
    assert len(found) == 1 and found[0].startswith(
        "python/kookabug_core/src/kookabug_core/service.py:"
    ), found
