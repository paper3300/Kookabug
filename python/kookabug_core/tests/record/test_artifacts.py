"""파일 artifacts와 `Recorder` 저장 (계획 2.9 "파일 artifacts")."""

import copy
import re
from pathlib import Path

from kookabug_core.engine import MemoryArtifacts
from kookabug_core.record.artifacts import ArtifactStore, FileArtifacts, Recorder
from kookabug_core.record.policy import RecordPolicy
from kookabug_sdk import Secret
from kookabug_sdk.types import Image

PNG = b"\x89PNG\r\n\x1a\nfake"


def source_png(tmp_path: Path, name: str = "frame.png") -> Path:
    path = tmp_path / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG)
    return path


def test_copy_image_path_keeps_extension(tmp_path: Path) -> None:
    store = FileArtifacts(tmp_path / "run")
    rel = store.save("s2", Image(path=source_png(tmp_path)), "before")
    assert rel == "steps/s2_before.png"
    assert (tmp_path / "run" / rel).read_bytes() == PNG
    # 이름이 이미 그 확장자로 끝나면 두 번 붙이지 않는다
    assert store.save("s2", Image(path=source_png(tmp_path)), "after.png") == "steps/s2_after.png"


def test_writes_data_bytes(tmp_path: Path) -> None:
    store = FileArtifacts(tmp_path / "run")
    rel = store.save("s1", Image(width=2, height=1, data=b"\x01\x02\x03"), "raw")
    assert rel == "steps/s1_raw"
    assert (tmp_path / "run" / rel).read_bytes() == b"\x01\x02\x03"


def _same_saves(store: ArtifactStore, png: Path) -> list[str]:
    return [
        store.save("s1", Image(path=png), "before"),
        store.save("s1", Image(path=png), "before"),  # 같은 이름 → -2
        store.save("s1", Image(data=b"x"), "raw"),
        store.save("s3", Image(path=png), "../../escape"),  # 경로 문자 → _
        store.save_text("s3", "ocr.txt", "글자"),
        store.save_text("s3", "ocr.txt", "글자"),
    ]


def test_paths_match_memory_artifacts_shape(tmp_path: Path) -> None:
    png = source_png(tmp_path)
    files = _same_saves(FileArtifacts(tmp_path / "run"), png)
    memory = _same_saves(MemoryArtifacts(), png)
    assert (
        files
        == memory
        == [
            "steps/s1_before.png",
            "steps/s1_before-2.png",
            "steps/s1_raw",
            "steps/s3_escape.png",
            "steps/s3_ocr.txt",
            "steps/s3_ocr-2.txt",
        ]
    )
    for rel in files:
        assert re.fullmatch(r"steps/s[1-9][0-9]*_[A-Za-z0-9._-]+", rel)
        assert (tmp_path / "run" / rel).is_file()
    assert not (tmp_path / "escape.png").exists()


def test_text_record_masks_secret(tmp_path: Path) -> None:
    recorder = Recorder(FileArtifacts(tmp_path))
    recorder.open_step("s1", RecordPolicy())
    structured = recorder.text("s1", "values.json", {"pw": Secret("hunter2"), "n": [1, "a"]})
    plain = recorder.text("s1", "pw.txt", Secret("hunter2"))
    artifacts, omitted = recorder.close_step("s1")
    assert artifacts == [structured, plain]
    assert omitted == []
    assert '"pw": "***"' in (tmp_path / structured).read_text(encoding="utf-8")
    assert (tmp_path / plain).read_text(encoding="utf-8") == "***"
    for path in (tmp_path / "steps").iterdir():
        assert b"hunter2" not in path.read_bytes()


def test_recorder_omits_without_touching_store(tmp_path: Path) -> None:
    store = MemoryArtifacts()
    recorder = Recorder(store)
    recorder.open_step("s1", RecordPolicy().layer({"screenshots": "off"}, "g#/record"))
    assert recorder.screenshot("s1", Image(path=source_png(tmp_path)), "before") is None
    assert store.saved == {}
    assert recorder.close_step("s1") == (
        [],
        [{"kind": "screenshot", "name": "before", "reason": "policy_off", "source": "g#/record"}],
    )


def test_capture_id_per_capture_survives_copy(tmp_path: Path) -> None:
    # 바이트만 있고 frame·path가 없는 같은 이미지도 캡처마다 다른 번호, 복사해도 번호가 남는다
    store = MemoryArtifacts()
    recorder = Recorder(store)
    raw = Image(data=b"pixels")
    recorder.open_step("s1", RecordPolicy().layer({"screenshots": "off"}, "g#/record"))
    first = recorder.captured("s1", raw)
    recorder.close_step("s1")
    recorder.open_step("s2", RecordPolicy())
    second = recorder.captured("s2", raw)
    assert raw.capture_id is None
    assert (first.capture_id, second.capture_id) == (1, 2)
    assert first == second == raw  # 값 비교에는 들지 않는다
    assert recorder.screenshot("s2", copy.deepcopy(first), "old") is None
    assert recorder.screenshot("s2", copy.deepcopy(second), "new") == "steps/s2_new"
    assert recorder.close_step("s2") == (
        ["steps/s2_new"],
        [{"kind": "screenshot", "name": "old", "reason": "capture_policy", "source": "g#/record"}],
    )
