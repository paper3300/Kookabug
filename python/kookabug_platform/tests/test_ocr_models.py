"""OCR 모델 표·찾기·해시 확인·받기 (구현 계획 M1 2.6, T7)."""

from __future__ import annotations

import hashlib
import shutil
import socket
from pathlib import Path
from typing import Any

import pytest

import fetch_ocr_models
import native_audit as na
from kookabug_platform.errors import OCR_MODEL_CORRUPT, OCR_MODEL_MISSING, PlatformError
from kookabug_platform.ocr import models as m
from kookabug_platform.ocr.engine import Ocr, RapidOcrEngine
from kookabug_platform.vision import load_target_image

FRAMES = Path(__file__).resolve().parents[3] / "fixtures" / "sample-game" / "frames"

# 구현 계획 M1 1장 "실제로 확인한 사실": RapidOCR v3.10.0 default_models.yaml
KNOWN_DET = "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"
KNOWN_REC = "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b"


def small_manifest(det: bytes = b"det-model", rec: bytes = b"rec-model") -> m.Manifest:
    """모델 대신 작은 바이트로 만든 표 (찾기 순서·해시 검사용)."""

    def entry(role: str, data: bytes) -> dict[str, Any]:
        return {
            "role": role,
            "file": f"{role}.onnx",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "license": "Apache-2.0",
            "license_texts": ["LICENSE.txt"],
            "source": "test",
            "url": f"https://example.invalid/{role}",
        }

    text = b"license"
    return m.parse_manifest(
        {
            "model": [entry("det", det), entry("rec", rec)],
            "text": [
                {
                    "file": "LICENSE.txt",
                    "label": "test",
                    "sha256": hashlib.sha256(text).hexdigest(),
                    "size": len(text),
                    "url": "https://example.invalid/license",
                }
            ],
        }
    )


def write_models(folder: Path, det: bytes = b"det-model", rec: bytes = b"rec-model") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "det.onnx").write_bytes(det)
    (folder / "rec.onnx").write_bytes(rec)
    return folder


def test_manifest_hashes_match_known_source_values() -> None:
    manifest = m.load_manifest()
    det, rec = manifest.model("det"), manifest.model("rec")
    assert (det.file, det.sha256) == ("PP-OCRv6_det_small.onnx", KNOWN_DET)
    assert (rec.file, rec.sha256) == ("korean_PP-OCRv5_rec_mobile.onnx", KNOWN_REC)
    for spec in manifest.models:
        assert spec.license == "Apache-2.0"
        assert "/v3.10.0/" in spec.url and spec.url.startswith("https://")
        assert spec.mirrors, "보조 주소가 있어야 한다"
        assert spec.license_texts
    # 감사 도구도 같은 표를 읽는다 (근거 원문 연결 포함)
    entries = na.load_model_table_file(m.MANIFEST_PATH)
    assert {e.sha256 for e in entries} == {KNOWN_DET, KNOWN_REC}
    assert all(e.texts for e in entries)


def test_missing_model_code(tmp_path: Path) -> None:
    manifest = small_manifest()
    with pytest.raises(PlatformError) as info:
        m.find_models(manifest, dirs=[tmp_path / "없음"])
    assert info.value.code == OCR_MODEL_MISSING
    assert "fetch_ocr_models" in info.value.message

    folder = tmp_path / "models"
    folder.mkdir()
    (folder / "det.onnx").write_bytes(b"det-model")  # rec이 없다
    with pytest.raises(PlatformError) as info:
        m.find_models(manifest, dirs=[folder])
    assert info.value.code == OCR_MODEL_MISSING
    assert "rec.onnx" in info.value.message


@pytest.mark.parametrize("rec", [b"rec-modeX", b"rec-model-longer"], ids=["same-size", "size"])
def test_corrupt_model_code(tmp_path: Path, rec: bytes) -> None:
    folder = write_models(tmp_path / "models", rec=rec)
    with pytest.raises(PlatformError) as info:
        m.find_models(small_manifest(), dirs=[folder])
    assert info.value.code == OCR_MODEL_CORRUPT
    assert "rec.onnx" in info.value.message


def test_search_order_env_install_repo(tmp_path: Path) -> None:
    env, install, repo = tmp_path / "env", tmp_path / "install", tmp_path / "repo"
    assert m.candidate_dirs(env=str(env), install=install, repo=repo) == [env]
    assert m.candidate_dirs(install=install, repo=repo) == [
        install / "ocr-models",
        repo / "build" / "ocr-models",
    ]
    manifest = small_manifest()
    dirs = m.candidate_dirs(install=install, repo=repo)
    # 설치본이 없으면 레포
    write_models(repo / "build" / "ocr-models")
    assert m.find_models(manifest, dirs=dirs).folder == repo / "build" / "ocr-models"
    # 둘 다 있으면 설치본
    write_models(install / "ocr-models")
    found = m.find_models(manifest, dirs=dirs)
    assert found.folder == install / "ocr-models"
    assert found.det == install / "ocr-models" / "det.onnx"
    # 환경 변수를 주면 그 폴더만 (없으면 다른 곳으로 넘어가지 않는다)
    with pytest.raises(PlatformError) as info:
        m.find_models(manifest, dirs=m.candidate_dirs(env=str(env), install=install, repo=repo))
    assert info.value.code == OCR_MODEL_MISSING


def test_real_environment_candidates(monkeypatch: pytest.MonkeyPatch, ocr_models: Path) -> None:
    monkeypatch.setenv(m.ENV, str(ocr_models))
    assert m.find_models().folder == ocr_models
    # 레포에서 돌면 레포 루트를 알아본다
    root = m.repo_root()
    assert root is not None and (root / "python" / "kookabug_platform").is_dir()


def test_no_network_at_runtime(monkeypatch: pytest.MonkeyPatch, ocr_models: Path) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("OCR이 실행 중 네트워크를 쓰려 했다")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setenv(m.ENV, str(ocr_models))
    ocr = Ocr(RapidOcrEngine())
    result = ocr.read(load_target_image(FRAMES / "title.png").bgr, region=(300, 150, 424, 90))
    assert result.text == "SampleRPG"


def test_license_evidence_file_fetched(tmp_path: Path, ocr_models: Path) -> None:
    manifest = m.load_manifest()
    names = {t.file for t in manifest.texts}
    assert {"LICENSE-PaddleOCR.txt", "MODEL_LICENSES-RapidOCR.md"} <= names
    for model in manifest.models:
        assert set(model.license_texts) == names

    # 받기: 첫 주소가 엉뚱한 바이트를 주면 보조 주소로, 근거 원문도 받아 해시를 확인한다
    by_url: dict[str, Path] = {}
    for spec in (*manifest.models, *manifest.texts):
        by_url[spec.urls[-1]] = ocr_models / spec.file
    calls: list[str] = []

    def download(url: str, dest: Path) -> None:
        calls.append(url)
        if url not in by_url:
            dest.write_bytes(b"not the model")
            return
        shutil.copyfile(by_url[url], dest)

    dest = tmp_path / "받은 모델"
    logs: list[str] = []
    failures = fetch_ocr_models.fetch_all(
        [*manifest.models, *manifest.texts], dest, download=download, log=logs.append
    )
    assert failures == []
    for spec in (*manifest.models, *manifest.texts):
        assert m.verify_file(dest / spec.file, spec.sha256, spec.size)
    assert not list(dest.glob(".*.part"))
    for model in manifest.models:
        assert model.url in calls and model.mirrors[0] in calls  # 첫 주소 실패 → 보조 주소

    # 이미 맞으면 다시 받지 않는다 (CI 캐시)
    calls.clear()
    assert (
        fetch_ocr_models.fetch_all(manifest.texts, dest, download=download, log=logs.append) == []
    )
    assert calls == []

    # 모든 주소가 틀리면 실패이고 제 이름의 파일을 남기지 않는다
    bad = tmp_path / "bad"

    def wrong(_url: str, dest: Path) -> None:
        dest.write_bytes(b"x")

    failures = fetch_ocr_models.fetch_all(manifest.texts[:1], bad, download=wrong, log=logs.append)
    assert len(failures) == 1 and not (bad / manifest.texts[0].file).exists()

    # 감사: 모델 폴더의 근거 원문을 확인하고 NOTICES에 원문을 싣는다
    entries = na.load_model_table_file(m.MANIFEST_PATH)
    policy = na_policy()
    assert na.audit_models(entries, dest, policy) == []
    (dest / "LICENSE-PaddleOCR.txt").write_text("바뀐 원문", encoding="utf-8")
    problems = na.audit_models(entries, dest, policy)
    assert any("근거 원문 해시 불일치" in p for p in problems)
    table = na.NativeTable(entries=[], strip=[], license_refs={})
    sections = na.render_notice_sections([], table, policy, [], entries, ocr_models)
    notice = "\n".join(sections)
    assert "PaddleOCR LICENSE" in notice and "TERMS AND CONDITIONS FOR USE" in notice
    assert "RapidOCR Model License and Attribution Notice" in notice


def na_policy() -> Any:
    from license_audit import load_policy_file

    return load_policy_file(na.TOOLS_DIR / "license-allowlist.toml")
