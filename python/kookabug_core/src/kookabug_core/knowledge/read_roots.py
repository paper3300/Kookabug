"""Agent 읽기 허용 폴더 (UX3) — 원본(기획 근거)과 따로, 실행·환경 확인용 파일을 Agent가 읽는 곳.
엄격: 경계·비밀값.

- 설정은 이 PC `.kookabug/local.json` `settings."agent.read_roots"`(폴더 절대 경로 목록)뿐이다. 팀
  설정에는 두지 않는다. 저장은 사람 전용 `local.settings.set`(같은 검사)만 한다
- 자동 포함: 실효 `game.executable`의 폴더(`read:game`)와 실효 `game.cwd`(`read:game_cwd`, 실행 파일
  폴더와 다를 때만). 설정 파일에 쓰지 않고 읽을 때마다 계산한다
- 허용하지 않는 폴더(`refusal`)는 저장할 때와 읽을 때 둘 다 거부한다: 드라이브 루트, 사용자 프로필
  폴더 자체와 그 바로 아래 `AppData`, Windows 폴더(그 아래 전부), Program Files 루트, 워크스페이스를
  품는 폴더(워크스페이스 자체 포함), 워크스페이스 파생 경로, 민감한 이름 폴더. 지정 경로와 실경로
  둘 다 본다. 자동 포함 폴더가 걸리면 빼고(`refused`) 화면에 경고한다
- 읽기 허용 폴더 안에서는 민감한 이름(`sensitive_name`)을 읽지도 목록에 보이지도 않는다. 단순
  이름 목록(Low 강도)이라 완전한 차단이 아니다 — 설명에 "비밀값은 가리지만 민감한 폴더는 넣지
  말라"고 쓴다
- 읽기 허용 폴더의 파일은 `source` 근거가 아니다(ref가 `read:<id>#<경로>` — `verify_basis`는
  `basis_unknown`). 기획 근거가 필요하면 원본으로 등록한다(`sources.add` 제안)
"""

from __future__ import annotations

import contextlib
import fnmatch
import ipaddress
import os
import re
import socket
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_core.knowledge.sources import (
    DERIVED_DIRS,
    DERIVED_FILES,
    _derived,  # pyright: ignore[reportPrivateUsage]
    _derived_route,  # pyright: ignore[reportPrivateUsage]
)
from kookabug_core.workspace import RunOptions, Workspace

__all__ = [
    "AUTO_TITLE",
    "KEY",
    "MAX_ROOTS",
    "PREFIX",
    "admin_share",
    "canonical",
    "check_root",
    "configured",
    "derived_path",
    "device_path",
    "normalize",
    "odd_part",
    "read_roots",
    "refusal",
    "resolved_parts",
    "sensitive",
]

KEY: Final = "agent.read_roots"
"""`local.json` settings 키 (이 PC)."""
PREFIX: Final = "read:"
"""`kb_source_list`·`kb_source_read`의 읽기 허용 폴더 ID 머리 (원본 ID에는 `:`가 없다)."""
MAX_ROOTS: Final = 20
AUTO_TITLE: Final = "게임 실행 파일 폴더(자동)"
AUTO_CWD_TITLE: Final = "게임 작업 폴더(자동)"

SENSITIVE_DIRS: Final = frozenset({".ssh", ".gnupg", ".aws", ".azure", ".git"})
SENSITIVE_FILES: Final = (
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "*.kdbx",
    ".env",
    ".env.*",
    "id_rsa*",
    "id_ed25519*",
    "credentials*",
    "*.keystore",
    "*.jks",
)
"""읽기 허용 폴더 안에서 읽지 않는 이름 (대소문자 무시). 단순 목록 — 완전한 차단이 아니다."""

REASONS: Final = {
    "not_absolute": "읽기 허용 폴더는 절대 경로여야 한다",
    "missing": "그 폴더가 없다",
    "drive_root": "드라이브 루트는 읽기 허용 폴더로 쓸 수 없다",
    "user_profile": "사용자 프로필 폴더 자체는 읽기 허용 폴더로 쓸 수 없다",
    "app_data": "사용자 프로필의 AppData 폴더 자체는 읽기 허용 폴더로 쓸 수 없다",
    "windows": "Windows 폴더는 읽기 허용 폴더로 쓸 수 없다",
    "program_files": "Program Files 루트는 읽기 허용 폴더로 쓸 수 없다",
    "contains_workspace": (
        "워크스페이스를 품는 폴더(워크스페이스 자체 포함)는 읽기 허용 폴더로 쓸 수 없다"
    ),
    "workspace_derived": (
        "워크스페이스 파생 경로(knowledge·wiki·.kookabug 등)는 읽기 허용 폴더로 쓸 수 없다"
    ),
    "sensitive_name": "민감한 이름의 폴더(.ssh·.git 등)는 읽기 허용 폴더로 쓸 수 없다",
    "device_path": "확장·장치 경로(\\\\?\\·\\\\.\\ 등)는 읽기 허용 폴더로 쓸 수 없다",
    "odd_name": "점·공백으로 끝나는 경로 조각은 쓸 수 없다",
    "admin_share": "관리 공유($로 끝나는 공유)나 이 PC를 가리키는 네트워크 경로는 쓸 수 없다",
}
"""거부 이유 → 사람에게 보이는 글 (경로 값은 넣지 않는다)."""


_DEVICE: Final = re.compile(r"^(?:[\\/]{2}[?.][\\/]|[\\/]\?\?[\\/])")
"""확장·장치 경로 접두사 `\\\\?\\`·`\\\\.\\`·`\\??\\`(구분자 `/` 변형 포함) — 검수 1 H1."""


def device_path(path: str) -> bool:
    """확장·장치 경로 접두사가 있는가. 이런 값은 입구에서 거부한다(`device_path`)."""
    return _DEVICE.match(path.strip()) is not None


def odd_part(part: str) -> bool:
    """Windows가 다른 이름으로 푸는 조각(끝 `.`·끝 공백, `.`·`..` 자체는 뺌) — 검수 1 H2."""
    return part not in (".", "..") and part != "" and part.endswith((".", " "))


_IPV6_LITERAL: Final = ".ipv6-literal.net"


def _loopback_ip(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped is not None and mapped.is_loopback


def _this_pc(host: str, env: Mapping[str, str]) -> bool:
    """UNC 호스트가 이 PC인가: localhost·루프백 IP(`127.*`·`::1`·`[::1]`·`0:…:1`·IPv4 매핑)·`.`·
    이 PC 이름(`COMPUTERNAME`, `<이름>.<도메인>`)·`*.ipv6-literal.net` 루프백."""
    low = host.casefold()
    if low in ("localhost", ".", "") or low.startswith("127.") or _loopback_ip(low):
        return True
    if low.endswith(_IPV6_LITERAL):
        literal = low[: -len(_IPV6_LITERAL)].split("s", 1)[0].replace("-", ":")
        if _loopback_ip(literal):
            return True
    names = {n.casefold() for n in (env.get("COMPUTERNAME"), socket.gethostname()) if n}
    return any(low == n or low.startswith(n + ".") for n in names)


def admin_share(path: str, *, env: Mapping[str, str] | None = None) -> bool:
    """관리 공유(`$`로 끝나는 공유 — `C$`·`ADMIN$`·`IPC$` 등)나 이 PC를 가리키는 UNC인가 (검수 2,
    이유 `admin_share`). 일반 UNC(`\\\\nas\\share\\docs`)는 허용한다. 연결하지 않고 글자만 본다."""
    env = os.environ if env is None else env
    text = _strip_device(path.strip()).replace("/", "\\")
    if not text.startswith("\\\\") or text.startswith("\\\\\\"):
        return False
    parts = text[2:].split("\\")
    host = parts[0]
    share = parts[1] if len(parts) > 1 else ""
    return share.endswith("$") or _this_pc(host, env)


def _strip_device(text: str) -> str:
    """비교 대상(환경 변수·실경로 결과)의 확장 접두사를 뗀다 (`\\\\?\\UNC\\` → `\\\\`)."""
    unified = text.replace("/", "\\")
    if unified[:8].casefold() == "\\\\?\\unc\\":
        return "\\\\" + unified[8:]
    if _DEVICE.match(unified):
        return unified[4:]
    return text


def _long(path: str) -> str:
    """8.3 짧은 이름을 긴 이름으로 (`GetLongPathNameW`). 없는 경로는 있는 조상까지 풀고 나머지를
    붙인다."""
    if os.name != "nt":
        return path
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    buf = ctypes.create_unicode_buffer(32768)
    n = int(kernel32.GetLongPathNameW(path, buf, 32768))
    if 0 < n < 32768:
        return buf.value
    parent, name = os.path.split(path)
    if not name or parent == path:
        return path
    return os.path.join(_long(parent), name)


def canonical(path: str | Path, *, real: bool = True) -> str:
    """비교용 한 표현: (확장 접두사 뗌) → 절대 경로 → 실경로(`real`) → 긴 이름 → `normcase`.
    후보·워크스페이스·금지 폴더를 모두 이 함수로 맞춰 비교한다 (검수 1 H1)."""
    text = os.path.abspath(_strip_device(os.fspath(path)))
    if real:
        with contextlib.suppress(OSError):
            text = _strip_device(os.path.realpath(text))
    return os.path.normcase(_long(text)).rstrip("\\/")


def _forms(path: str | Path) -> set[str]:
    """지정 경로 그대로의 표현과 실경로 표현 둘 다 (정션·별칭)."""
    return {canonical(path, real=False), canonical(path)}


def _same(a: str | Path, b: str | Path) -> bool:
    return bool(_forms(a) & _forms(b))


def _under(base: str | Path, path: str | Path) -> bool:
    """`path`가 `base`이거나 그 아래인가 (같은 정규화로)."""
    bases = _forms(base)
    return any(p == b or p.startswith(b + "\\") for p in _forms(path) for b in bases)


def derived_path(workspace: Workspace, path: str | Path) -> bool:
    """`path`가 워크스페이스 파생 경로인가 — `canonical`로 맞춘 표현으로 (`sources._derived`를
    보탠다. `source_read`도 쓴다)."""
    dirs = {d.casefold() for d in DERIVED_DIRS}
    for ws in _forms(workspace.root):
        for p in _forms(path):
            if not p.startswith(ws + "\\"):
                continue
            rest = p[len(ws) + 1 :].split("\\")
            first = rest[0].casefold()
            if first in dirs or (len(rest) == 1 and first in DERIVED_FILES):
                return True
    return False


def resolved_parts(real_root: Path, target: Path) -> list[str]:
    """`target` 실경로의 `real_root` 아래 조각들 (긴 이름 — 8.3 이름 우회를 막는 민감한 이름
    검사용). 루트 밖이면 실경로 전체 조각."""
    root = canonical(real_root)
    full = canonical(target)
    if full == root:
        return []
    if full.startswith(root + "\\"):
        return full[len(root) + 1 :].split("\\")
    return list(Path(full).parts[1:])


def _env_dirs(env: Mapping[str, str], *names: str) -> list[str]:
    return [value for name in names if (value := env.get(name))]


def sensitive(parts: Sequence[str]) -> bool:
    """경로 조각 중 민감한 이름이 있는가 (폴더 이름·파일 이름 둘 다, 대소문자 무시)."""
    for part in parts:
        low = part.casefold()
        if low in SENSITIVE_DIRS:
            return True
        if any(fnmatch.fnmatchcase(low, pattern) for pattern in SENSITIVE_FILES):
            return True
    return False


def refusal(workspace: Workspace, path: str, *, env: Mapping[str, str] | None = None) -> str | None:
    """읽기 허용 폴더로 쓸 수 없는 이유(`REASONS` 키) 또는 None. 지정 경로와 실경로 둘 다 본다."""
    env = os.environ if env is None else env
    if device_path(path):
        return "device_path"
    # 실경로를 풀기(SMB 연결) 전에 지정 경로부터 본다 (검수 2)
    if admin_share(path, env=env):
        return "admin_share"
    raw = Path(path)
    if not path.strip() or not raw.is_absolute():
        return "not_absolute"
    if any(odd_part(p) for p in path.replace("/", "\\").split("\\")[1:]):
        return "odd_name"
    lexical = Path(os.path.abspath(raw))
    try:
        real = Path(os.path.realpath(lexical))
    except OSError:
        return "missing"
    if device_path(str(real)):
        real = Path(_strip_device(str(real)))
    # 네트워크 드라이브 문자의 실경로가 루프백·관리 공유 UNC로 풀리는 경우
    if admin_share(str(real), env=env):
        return "admin_share"
    profiles = _env_dirs(env, "USERPROFILE")
    if not profiles:
        try:
            profiles = [str(Path.home())]
        except RuntimeError:
            profiles = []
    windows = _env_dirs(env, "SystemRoot", "windir")
    program_files = _env_dirs(env, "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")
    for candidate in (lexical, real):
        if candidate.parent == candidate:
            return "drive_root"
    # 후보·금지 폴더·워크스페이스 모두 같은 정규화(canonical)로 비교한다 (검수 1 H1)
    if any(_same(lexical, p) for p in profiles):
        return "user_profile"
    if any(_same(lexical, os.path.join(_strip_device(p), "AppData")) for p in profiles):
        return "app_data"
    if any(_under(w, lexical) for w in windows):
        return "windows"
    if any(_same(lexical, p) for p in program_files):
        return "program_files"
    if _under(lexical, workspace.root):
        return "contains_workspace"
    for form in _forms(lexical) | {str(lexical)}:
        if sensitive(Path(form).parts[1:]):
            return "sensitive_name"
    if (
        _derived_route(workspace, lexical)
        or _derived(workspace, real)
        or derived_path(workspace, lexical)
    ):
        return "workspace_derived"
    if not real.is_dir():
        return "missing"
    return None


def check_root(
    workspace: Workspace,
    path: str,
    *,
    index: int | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """저장할 때의 검사: 쓸 수 없으면 `policy_path`(필드 `reason`·`index`)."""
    reason = refusal(workspace, path, env=env)
    if reason is None:
        return
    fields: dict[str, Any] = {"reason": reason}
    if index is not None:
        fields["index"] = index
    raise KnowledgeError("policy_path", REASONS[reason], **fields)


def normalize(
    workspace: Workspace, paths: Sequence[Any], *, env: Mapping[str, str] | None = None
) -> list[str]:
    """저장할 목록: 글자 목록(`MAX_ROOTS`까지), 앞뒤 공백 정리, 같은 폴더는 하나로, 하나씩 검사."""
    if len(paths) > MAX_ROOTS:
        raise KnowledgeError("format", f"읽기 허용 폴더는 {MAX_ROOTS}개까지다")
    out: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(paths):
        if not isinstance(value, str) or len(value) > 1000:
            raise KnowledgeError("format", "읽기 허용 폴더는 1000자까지의 경로 글이다")
        clean = value.strip()
        if not clean:
            continue
        check_root(workspace, clean, index=index, env=env)
        key = canonical(clean, real=False)
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def configured(workspace: Workspace) -> list[str]:
    """이 PC `local.json`의 읽기 허용 폴더 (글자만, 빈 값 뺌)."""
    local = workspace.local or {}
    settings = local.get("settings")
    value = cast(dict[str, Any], settings).get(KEY) if isinstance(settings, dict) else None
    if not isinstance(value, list):
        return []
    return [v.strip() for v in cast(list[Any], value) if isinstance(v, str) and v.strip()]


def _effective_dir(workspace: Workspace, key: str, *, parent: bool) -> Path | None:
    found = workspace.lookup_setting(key, RunOptions())
    value = found.value if found.found else None
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value.strip())
    if not path.is_absolute():
        path = workspace.root / path
    path = Path(os.path.abspath(path))
    return path.parent if parent else path


def _entry(
    workspace: Workspace,
    root_id: str,
    path: Path | str,
    title: str,
    *,
    auto: bool,
    env: Mapping[str, str] | None,
) -> dict[str, Any]:
    reason = refusal(workspace, str(path), env=env)
    if reason is None:
        state = "ok"
    elif reason == "missing":
        state = "missing"
    else:
        state = "refused"
    return {
        "id": root_id,
        "path": str(path),
        "title": title,
        "auto": auto,
        "state": state,
        "reason": reason,
    }


def read_roots(
    workspace: Workspace, *, env: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """읽기 허용 폴더 전부 (자동 포함 먼저): `{id, path, title, auto, state, reason}`. 상태는
    `ok`·`missing`·`refused`(허용하지 않는 폴더 — 읽지 않는다)."""
    out: list[dict[str, Any]] = []
    exe_dir = _effective_dir(workspace, "game.executable", parent=True)
    if exe_dir is not None:
        out.append(_entry(workspace, f"{PREFIX}game", exe_dir, AUTO_TITLE, auto=True, env=env))
    cwd = _effective_dir(workspace, "game.cwd", parent=False)
    if cwd is not None and (exe_dir is None or not _same(cwd, exe_dir)):
        out.append(_entry(workspace, f"{PREFIX}game_cwd", cwd, AUTO_CWD_TITLE, auto=True, env=env))
    for n, path in enumerate(configured(workspace)[:MAX_ROOTS], start=1):
        out.append(_entry(workspace, f"{PREFIX}{n}", path, path, auto=False, env=env))
    return out
