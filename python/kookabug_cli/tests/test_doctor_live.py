"""`kookabug doctor` 데스크톱 프로필 실제 검사 (구현 계획 M1 2.11, `desktop`).

입력은 보내지 않는다 — 임시 창을 띄워 WGC 한 프레임, 정지 화면 재사용, 포그라운드 가져오기만 본다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kookabug_cli import main as cli

pytestmark = pytest.mark.desktop


def test_desktop_profile_all_pass(
    ocr_models: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    code = cli.main(["doctor", "--json"])
    body = json.loads(capsys.readouterr().out)
    failed = [c for c in body["checks"] if not c["ok"]]
    assert (code, failed) == (0, [])
    ids = {c["id"] for c in body["checks"] if c["profile"] == "desktop"}
    assert ids == {
        "desktop.input_desktop",
        "desktop.capture",
        "desktop.static_reuse",
        "desktop.foreground",
    }
