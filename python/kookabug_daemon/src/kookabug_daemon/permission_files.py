"""권한 파일 읽기·쓰기 (M5 계획 3.6 "쓰기 규칙"): `permissions.get/set`, "항상 허용"의 규칙 추가.

- 계층: 사용자 `settings.json`(`KOOKABUG_USER_CONFIG_DIR` 또는 `%APPDATA%\\Kookabug`), 프로젝트
  `.kookabug/local.json`. 팀 `kookabug.json`은 읽기만 한다(UI에서 고치지 않음)
- revision = 파일 바이트의 sha256 hex (없으면 null). 쓰기 직전에 다시 읽어 기준과 다르면
  `revision_conflict`
- 쓰기: `utf-8-sig`로 읽고 → `permissions` 키만 바꾸고(다른 키와 순서는 그대로) → 같은 폴더 임시
  파일 + `os.replace`. JSON이 아니거나 바꾼 뒤에도 파일 형식이 틀리면 고치지 않고 `settings_invalid`
- daemon 안의 쓰기는 잠금 하나로 직렬이다(`permissions.set`과 "항상 허용"이 겹쳐도 하나씩)
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from kookabug_core.canonical import loads_strict
from kookabug_core.documents import DocumentError, write_atomic
from kookabug_core.permissions import LayerName, Policy
from kookabug_core.schema import check_shape
from kookabug_core.schema.shape import SchemaKind
from kookabug_core.service import WorkspaceService
from kookabug_core.workspace import LOCAL_FILE, WORKSPACE_FILE
from kookabug_daemon.protocol import RequestFailed

__all__ = ["EditableLayer", "PermissionFiles", "revision_of"]

type EditableLayer = Literal["user", "project"]


def revision_of(raw: bytes | None) -> str | None:
    return None if raw is None else hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class _File:
    layer: LayerName
    path: Path | None
    kind: SchemaKind
    format: str


def _read(path: Path | None) -> bytes | None:
    if path is None:
        return None
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        text = f"{path}을(를) 읽을 수 없다: {exc}"
        raise RequestFailed("io_error", text, message=text) from exc


def _parse(raw: bytes, shown: str) -> dict[str, Any] | None:
    try:
        value = loads_strict(raw.decode("utf-8-sig"))
    except UnicodeDecodeError, ValueError:
        return None
    return value if isinstance(value, dict) else None


class PermissionFiles:
    def __init__(self, root: Path, service: WorkspaceService) -> None:
        self.root = root
        self.service = service
        self._lock = threading.Lock()

    def _file(self, layer: LayerName) -> _File:
        if layer == "project":
            return _File(
                "project", self.root.joinpath(*LOCAL_FILE.split("/")), "local", "kookabug.local/0"
            )
        if layer == "user":
            path = self.service.user_settings_path()
            return _File("user", path, "user-settings", "kookabug.user-settings/0")
        return _File("team", self.root / WORKSPACE_FILE, "workspace", "kookabug.workspace/0")

    # ---------------------------------------------------------------- 읽기

    def layers(self, policy: Policy) -> list[dict[str, Any]]:
        """`permissions.get`의 계층 목록 (프로젝트 → 사용자 → 팀)."""
        out: list[dict[str, Any]] = []
        by_layer = {p.layer: p for p in policy.layers}
        for layer in ("project", "user", "team"):
            file = self._file(layer)
            raw = _read(file.path)
            data = None if raw is None else _parse(raw, str(file.path))
            permissions = None if data is None else data.get("permissions")
            out.append(
                {
                    "layer": layer,
                    "source": None if file.path is None else str(file.path),
                    "permissions": permissions if isinstance(permissions, dict) else None,
                    "revision": revision_of(raw),
                    "diagnostics": [d.to_dict() for d in by_layer[layer].diagnostics],
                    "editable": layer != "team" and file.path is not None,
                }
            )
        return out

    # ---------------------------------------------------------------- 쓰기

    def set(
        self, layer: EditableLayer, permissions: Mapping[str, Any], base_revision: str | None
    ) -> str:
        """그 계층의 `permissions`를 바꾼다. 새 revision을 돌려준다 (막히는 호출)."""
        problems = check_shape(dict(permissions), self._file(layer).kind, ref="#/$defs/Permissions")
        if problems:
            raise RequestFailed(
                "validation_failed",
                "permissions 형식이 틀렸다",
                diagnostics=[d.to_dict() for d in problems],
            )
        with self._lock:
            return self._write(layer, base_revision, lambda _old: dict(permissions))

    def add_rule(self, layer: EditableLayer, rule: str) -> str:
        """그 계층 `permissions.rules`에 `{rule, verdict: allow}`를 더한다 ("항상 허용"). 같은
        규칙이 이미 있으면 그대로 둔다."""

        def change(old: Any) -> dict[str, Any]:
            current: dict[str, Any] = dict(old) if isinstance(old, dict) else {}
            rules = list(current.get("rules") or [])
            entry = {"rule": rule, "verdict": "allow"}
            if entry not in rules:
                rules.append(entry)
            current["rules"] = rules
            return current

        with self._lock:
            return self._write(layer, None, change, check_revision=False)

    # ---------------------------------------------------------------- 에이전트 목록 (M5 B5)

    def read_agents(self) -> dict[str, Any]:
        """`agents.get`: 사용자 설정의 `agents`·`default_agent`와 파일 revision."""
        file = self._file("user")
        raw = _read(file.path)
        out: dict[str, Any] = {
            "agents": [],
            "default_agent": None,
            "revision": revision_of(raw),
            "source": None if file.path is None else str(file.path),
            "problem": None,
        }
        if raw is None:
            return out
        data = _parse(raw, str(file.path))
        problems = [] if data is None else check_shape(data, file.kind, file=str(file.path))
        if data is None or problems:
            out["problem"] = (
                "JSON 객체가 아니다" if data is None else f"형식이 틀렸다: {problems[0].message}"
            )
            return out
        out["agents"] = list(data.get("agents") or [])
        default = data.get("default_agent")
        out["default_agent"] = default if isinstance(default, str) else None
        return out

    def set_agents(
        self, agents: list[Any], default_agent: str | None, base_revision: str | None
    ) -> str:
        """`agents.set`: 사용자 설정의 `agents`·`default_agent`만 바꾼다 (`permissions.set`과
        같은 쓰기 규칙 — revision 비교, 다른 키·순서 보존, 형식이 틀린 파일은 그대로)."""

        def mutate(data: dict[str, Any]) -> None:
            data["agents"] = list(agents)
            if default_agent is None:
                data.pop("default_agent", None)
            else:
                data["default_agent"] = default_agent

        with self._lock:
            return self._write_data("user", base_revision, mutate)

    def _write(
        self,
        layer: EditableLayer,
        base_revision: str | None,
        change: Any,
        *,
        check_revision: bool = True,
    ) -> str:
        def mutate(data: dict[str, Any]) -> None:
            data["permissions"] = change(data.get("permissions"))

        return self._write_data(layer, base_revision, mutate, check_revision=check_revision)

    def _write_data(
        self,
        layer: EditableLayer,
        base_revision: str | None,
        mutate: Any,
        *,
        check_revision: bool = True,
    ) -> str:
        file = self._file(layer)
        if file.path is None:
            raise RequestFailed(
                "io_error", "사용자 설정 폴더를 정할 수 없다", message="APPDATA가 없다"
            )
        shown = str(file.path)
        raw = _read(file.path)
        current = revision_of(raw)
        if check_revision and current != base_revision:
            raise RequestFailed(
                "revision_conflict", f"{shown}이(가) 그 사이 바뀌었다", revision=current
            )
        if raw is None:
            data: dict[str, Any] = {"format": file.format}
        else:
            parsed = _parse(raw, shown)
            if parsed is None:
                raise RequestFailed(
                    "settings_invalid",
                    f"{shown}이(가) JSON 객체가 아니라 고치지 않는다 (먼저 손으로 고친다)",
                )
            data = parsed
            # 바꾸기 전에 원본 전체를 본다: 기존 permissions가 틀린 파일도 고치지 않는다 (B3 H3)
            problems = check_shape(data, file.kind, file=shown)
            if problems:
                raise RequestFailed(
                    "settings_invalid",
                    f"{shown}의 형식이 틀려 고치지 않는다 (먼저 손으로 고친다): "
                    f"{problems[0].message}",
                )
        mutate(data)
        problems = check_shape(data, file.kind, file=shown)
        if problems:
            raise RequestFailed(
                "settings_invalid",
                f"{shown}의 형식이 틀려 고치지 않는다: {problems[0].message}",
            )
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        # BOM 없이 쓴다 (정책 읽기는 utf-8 — BOM이 있던 파일은 그 전에도 정책 오류였다)
        body = text.encode("utf-8")
        path = file.path

        def unchanged() -> None:
            # 임시 파일 fsync 뒤 os.replace 바로 앞에서 다시 읽는다: 읽은 뒤 daemon 밖에서
            # 바뀌었으면 늦은 쪽(이 쓰기)을 거부하고 임시 파일은 write_atomic이 지운다 (B3 H4)
            now = revision_of(_read(path))
            if now != current:
                raise RequestFailed(
                    "revision_conflict", f"{shown}이(가) 그 사이 바뀌었다", revision=now
                )

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(path, body, before_replace=unchanged)
        except (OSError, DocumentError) as exc:
            text = f"{shown}에 쓸 수 없다: {exc}"
            raise RequestFailed("io_error", text, message=text) from exc
        written = revision_of(body)
        assert written is not None
        return written
