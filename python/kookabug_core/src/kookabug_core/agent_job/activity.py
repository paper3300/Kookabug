"""작업 활동 목록 `.kookabug/jobs/<작업>/activity.jsonl` (UX1 U3).

Agent가 작업 토큰 연결로 부른 Kookabug 도구(`kb_*`) 한 번이 한 줄이다: 시각·도구·결과(`ok` 또는
오류 코드)·짧은 대상. 사람 화면(보고함·마법사 9단계)이 "Init이 지금 무엇을 하는지" 보는 데만 쓴다.

- 대상은 정해 둔 인자 키(경로·ID·실행·사건·창 제목)의 짧은 글만 남긴다. 글 값(`text`·`query`·
  `note`)·연산 묶음·비밀값 키는 쓰지 않는다. 줄바꿈·제어 문자가 있거나 길면(120자) 버린다
- 쓰기 직전 `agent.log`와 같은 가림 대상(작업 토큰·워크스페이스 비밀값)이 들어 있으면 `[가림]`,
  가림 값을 확인하지 못하면 대상을 비운다 (`mask_target`). 퍼센트 인코딩(`%`)이나 NFKC로 바뀌는
  글자(전각 등)가 있는 대상은 비운다. `+`·경로 구분자 표현은 같은 값으로 본다. daemon은 그 작업의
  토큰 원문이 이미 없으면(끝난 작업) 대상을 비운다
- 쓰기는 `jobdir.job_path`(`filetx.plain` — 링크·정션·워크스페이스 밖이면 거부) 경계를 지난다
- `agent.log` 꼬리는 runner가 이미 비밀값을 가려 쓴 파일의 마지막 줄들이다
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import unquote

from kookabug_core import filetx
from kookabug_core.agent_job import jobdir
from kookabug_core.knowledge.formats import normalize

__all__ = [
    "ACTIVITY_FILE",
    "LOG_TAIL_LINES",
    "MASKED",
    "append",
    "log_tail",
    "mask_target",
    "read",
    "short_target",
]

ACTIVITY_FILE: Final = "activity.jsonl"
LOG_TAIL_LINES: Final = 200
LOG_TAIL_BYTES: Final = 256 * 1024
"""꼬리를 찾을 때 읽는 파일 끝 크기 (agent.log는 20 MB까지 자란다)."""
READ_LIMIT: Final = 500
"""한 번에 돌려주는 줄 수 (화면은 `after`로 이어 읽는다)."""
TARGET_MAX: Final = 120
ACTIVITY_MAX_BYTES: Final = 4 * 1024 * 1024
"""활동 파일 상한. 넘으면 더 쓰지 않는다 (작업 하나의 도구 호출은 예산으로 묶여 보통 훨씬 작다)."""

_TARGET_KEYS: Final = ("path", "file", "id", "run", "case", "key", "job")
"""대상으로 남길 인자 키 (짧은 식별자만 — 글 값·연산·비밀값 키는 넣지 않는다)."""
_WINDOW_METHODS: Final = frozenset({"control.click", "control.key", "control.type"})
"""권한 인자가 창 제목인 메서드 (창 제목은 판정·감사 기록에도 남는 값이다). 입력 글·키는
남기지 않는다."""
_SAFE: Final = re.compile(rf"[^\x00-\x1f\x7f]{{1,{TARGET_MAX}}}")

_lock = threading.Lock()


def short_target(method: str, params: Mapping[str, Any], arg: str = "") -> str:
    """활동 한 줄의 대상. 정해 둔 키의 짧은 글 하나, 아니면 빈 글."""
    if method in _WINDOW_METHODS:
        value: Any = params.get("window", arg)
    else:
        value = next((params[k] for k in _TARGET_KEYS if isinstance(params.get(k), str)), "")
    text = str(value).strip() if isinstance(value, str) else ""
    return text if _SAFE.fullmatch(text) else ""


MASKED: Final = "[가림]"


_DECODE_ROUNDS: Final = 3


def _fold(text: str) -> str:
    """비교용 정규화: 경로 구분자 통일(`\\`→`/`) + 글자 검사기 `normalize`(NFKC·공백·대소문자).
    NFKC가 만든 `\\`(전각 역슬래시 등)도 통일하도록 정규화 뒤에 한 번 더 바꾼다 (UX1 검수 3 H1)."""
    return normalize(text.replace("\\", "/")).replace("\\", "/")


def _target_forms(target: str) -> set[str] | None:
    """대상의 후보 표현 (정규화 전): 원문, 퍼센트 디코딩(바뀌지 않을 때까지 최대 3번), `+`→공백.
    세 번 풀어도 아직 풀리면(더 깊게 감싼 표현) `None` — 확인하지 못한 것으로 본다."""
    # 디코딩마다 NFKC를 먼저 한다: 전각 퍼센트(U+FF05)처럼 NFKC가 새로 만드는 퍼센트 표현도
    # 같은 한도 안에서 푼다 (UX1 검수 4 H1 — 전각 퍼센트 72…, `%EF%BC%8572…`)
    forms = {target}
    for start in (target, target.replace("+", " ")):
        text = start
        forms.add(text)
        for _ in range(_DECODE_ROUNDS):
            text = unicodedata.normalize("NFKC", text)
            forms.add(text)
            decoded = unquote(text)
            if decoded == text:
                break
            text = decoded
            forms.add(text)
        else:
            text = unicodedata.normalize("NFKC", text)
            if unquote(text) != text:
                return None
    return forms | {form.replace("+", " ") for form in forms}


def mask_target(target: str, values: Iterable[str] | None) -> str:
    """쓰기 직전 비밀값 검사 (`agent.log`와 같은 가림 대상). 대상의 후보 표현(원문·퍼센트 디코딩·
    `+`→공백·경로 구분자 통일) 가운데 하나라도 비밀값을 품으면 `[가림]`. 가림 값을 확인하지
    못했으면(`None`) 또는 표현을 다 풀지 못하면 빈 글 — `agent.log`의 "가림 불가로 생략"과
    같은 원칙."""
    if not target or values is None:
        return ""
    if "%" in target or unicodedata.normalize("NFKC", target) != target:
        # 퍼센트 인코딩·호환 글자(전각 등)가 섞인 대상은 표현 조합을 다 따라가지 않고 비운다
        # (UX1 검수 5: NFKC·디코딩·`+` 조합 우회를 막는 보수적 정책 — 화면 줄의 대상만 빠진다)
        return ""
    forms = _target_forms(target)
    if forms is None:
        return ""
    folded = {_fold(form) for form in forms}
    for value in values:
        found = _fold(value) if value else ""
        if found and (value in target or any(found in form for form in folded)):
            return MASKED
    return target


def _now() -> str:
    at = datetime.now(UTC)
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{at.microsecond // 1000:03d}Z"


def append(root: Path, job_id: str, tool: str, result: str, target: str) -> None:
    """한 줄 더한다. 작업 폴더가 없거나 경계 밖이면 `filetx.TxError`·`OSError`(호출자가 삼킨다)."""
    line = {"at": _now(), "tool": tool, "result": result, "target": target}
    data = (json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    with _lock:
        path = jobdir.job_path(root, job_id, ACTIVITY_FILE)
        if not path.parent.is_dir():
            return  # 작업 폴더는 agent-job이 만든다 — 없으면 남기지 않는다
        if path.is_file() and path.stat().st_size + len(data) > ACTIVITY_MAX_BYTES:
            return
        with path.open("ab") as f:
            f.write(data)


def read(root: Path, job_id: str, after: int = 0) -> list[dict[str, Any]]:
    """`after`번째 줄 뒤의 줄들 (seq = 1부터 줄 번호, 최대 `READ_LIMIT`). 깨진 줄은 건너뛴다
    (번호는 센다)."""
    try:
        path = jobdir.job_path(root, job_id, ACTIVITY_FILE)
        raw = path.read_bytes()
    except OSError, filetx.TxError:
        return []
    out: list[dict[str, Any]] = []
    for seq, line in enumerate(raw.splitlines(), start=1):
        if seq <= after:
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if not isinstance(value, dict):
            continue
        out.append(
            {
                "seq": seq,
                "at": str(value.get("at", "")),
                "tool": str(value.get("tool", "")),
                "result": str(value.get("result", "")),
                "target": str(value.get("target", "")),
            }
        )
        if len(out) >= READ_LIMIT:
            break
    return out


def log_tail(root: Path, job_id: str, lines: int = LOG_TAIL_LINES) -> list[str]:
    """`agent.log`의 마지막 줄들 (가린 뒤의 글 그대로). 없으면 빈 목록."""
    try:
        path = jobdir.job_path(root, job_id, "agent.log")
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - LOG_TAIL_BYTES))
            data = f.read()
    except OSError, filetx.TxError:
        return []
    text = data.decode("utf-8", errors="replace")
    parts = text.splitlines()
    if size > LOG_TAIL_BYTES and parts:
        parts = parts[1:]  # 잘린 첫 줄은 버린다
    return parts[-lines:]
