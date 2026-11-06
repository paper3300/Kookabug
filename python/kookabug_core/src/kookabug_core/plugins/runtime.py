"""실행이 쓰는 설치 플러그인 (M6 계획 3.6·D8·D9). runner·daemon은 플러그인 코드를 import하지 않는다.

- `acquire`: runner 스냅샷 단계. `op.lock` 안에서 `kookabug.lock`을 읽고, 그래프가 쓰는 플러그인의
  조건(D10)·환경을 정한 뒤, 고른 환경마다 사용 표식 `.in-use/<runner pid>-<생성 시각>`을 만든다
  (워커를 띄우기 전). 환경 검증(digest 재계산)은 `op.lock` 밖에서 하고, 표식을 만들 때 잠금 바이트가
  그대로인지·고른 폴더가 아직 완성인지 다시 본다 (바뀌었으면 처음부터, 몇 번까지). 검증에 실패한
  완성 환경은 깨짐으로 기록하고 다음 후보를 쓴다 (`envs.select_env`)
- `check_hello`: 워커 hello를 잠금과 대조한다 — 노드 스키마 digest는 runner가 다시 계산하고(워커가
  보낸 `digest`를 믿지 않는다) 잠금 `schema_sha256`과, 노드 `effects`는 **잠금의** `permissions`와
- `installed_schemas`: 잠금의 각 플러그인 노드 스키마를 커밋된 wheel 안 스키마 파일에서 읽는다
  (바이트 sha256·schema digest를 잠금과 대조). daemon 팔레트·사전 검증, runner의 환경 없는 플러그인
  검증용
- `release_markers`: runner가 죽었을 때 감독자가 그 runner의 사용 표식을 지운다
"""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from kookabug_core.plugins import envs as envs_mod
from kookabug_core.plugins.errors import PluginError
from kookabug_core.plugins.layout import Layout
from kookabug_core.plugins.lockfile import lock_sha256, parse_lock
from kookabug_core.win import ProcessId
from kookabug_sdk.schema import schema_digest

__all__ = [
    "EnvUse",
    "LockedPlugin",
    "Problem",
    "RunPlugins",
    "acquire",
    "check_hello",
    "inspect",
    "installed_schemas",
    "marker_name",
    "release_markers",
]

ACQUIRE_ATTEMPTS: Final = 5
"""잠금이 검증 중에 바뀌면 처음부터 다시 고르는 횟수."""

type ProblemCode = Literal["plugin_not_installed", "plugin_env_missing", "plugin_env_stale"]
type HelloCode = Literal["plugin_schema_mismatch", "plugin_permission_exceeded"]


def marker_name(ident: ProcessId) -> str:
    """사용 표식 이름 (`gc.in_use`가 같은 형식을 읽는다)."""
    return f"{ident.pid}-{ident.created}"


@dataclass(frozen=True, slots=True)
class LockedPlugin:
    """잠금의 플러그인 항목 중 실행에 필요한 것."""

    id: str
    version: str
    env: str
    modules: tuple[str, ...]
    permissions: frozenset[str]
    wheel: str
    wheel_sha256: str
    schema_sha256: str

    @classmethod
    def from_lock(cls, entry: Mapping[str, Any]) -> LockedPlugin:
        manifest: Mapping[str, Any] = entry["manifest"]
        return cls(
            id=str(entry["id"]),
            version=str(entry["version"]),
            env=str(entry["env"]),
            modules=tuple(manifest["modules"]),
            permissions=frozenset(manifest.get("permissions", ())),
            wheel=str(entry["wheel"]),
            wheel_sha256=str(entry["wheel_sha256"]),
            schema_sha256=str(entry["schema_sha256"]),
        )

    def run_json(self) -> dict[str, Any]:
        """`run.json plugins[]` 항목."""
        return {
            "id": self.id,
            "version": self.version,
            "env": self.env,
            "wheel_sha256": self.wheel_sha256,
            "schema_sha256": self.schema_sha256,
        }


@dataclass(frozen=True, slots=True)
class EnvUse:
    """이 실행이 쓰는 환경 하나 (워커 하나)."""

    name: str
    folder: Path
    plugins: tuple[LockedPlugin, ...]

    @property
    def python(self) -> Path:
        return envs_mod.env_python(self.folder)

    @property
    def modules(self) -> list[str]:
        return [m for p in self.plugins for m in p.modules]


@dataclass(frozen=True, slots=True)
class Problem:
    """실행 전 검증 오류가 되는 플러그인 문제."""

    code: ProblemCode
    plugin: str
    message: str


@dataclass
class RunPlugins:
    """`acquire`의 결과. 실행이 끝나면 `release()`."""

    lock_bytes: bytes | None = None
    lock_sha256: str | None = None
    envs: list[EnvUse] = field(default_factory=list[EnvUse])
    problems: list[Problem] = field(default_factory=list[Problem])
    versions: dict[str, str] = field(default_factory=dict[str, str])
    """잠금의 플러그인 판 (그래프 `plugins`와 대조 — `plugin_version_differs`)."""
    unready: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    """환경을 쓸 수 없는 플러그인의 노드 스키마 (커밋된 wheel에서, 검증 진단용)."""
    markers: list[Path] = field(default_factory=list[Path])
    unreadable: list[Path] = field(default_factory=list[Path])
    """고르지 못한 환경의 후보 중 읽다 실패했거나 검증 중 사라진 폴더 (op.lock 안에서 다시 본다)."""

    def plugin(self, plugin_id: str) -> LockedPlugin | None:
        for env in self.envs:
            for plugin in env.plugins:
                if plugin.id == plugin_id:
                    return plugin
        return None

    def release(self) -> None:
        """사용 표식을 지운다 (여러 번 불러도 된다)."""
        markers, self.markers = self.markers, []
        for marker in markers:
            with contextlib.suppress(OSError):
                marker.unlink()


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _not_installed(used: Iterable[str]) -> list[Problem]:
    return [
        Problem(
            "plugin_not_installed",
            pid,
            f"플러그인 {pid}이(가) kookabug.lock에 없다 (kookabug plugin add로 설치한다)",
        )
        for pid in sorted(used)
    ]


def acquire(
    root: Path,
    used: Iterable[str],
    ident: ProcessId,
    *,
    environ: Mapping[str, str],
    fault: Callable[[str], None] | None = None,
) -> RunPlugins:
    """그래프가 쓰는 설치 플러그인(`used`, 코어·개발 모듈 제외 ID)의 환경을 정하고 사용 표식을
    만든다. 문제는 `problems`로 (예외로 던지지 않는다). `fault(이벤트)`: 검사용 지점
    (`read` = 잠금을 읽은 뒤, `marked` = 표식을 만든 뒤)."""
    wanted = set(used)
    if not wanted:
        return RunPlugins()
    layout = Layout(Path(root))
    if not layout.lock.is_file():
        return RunPlugins(problems=_not_installed(wanted))
    last: RunPlugins | None = None
    for _ in range(ACQUIRE_ATTEMPTS):
        with layout.op():
            data = _read(layout.lock)
        if data is None:
            return RunPlugins(problems=_not_installed(wanted))
        try:
            lock = parse_lock(data)
        except PluginError as exc:
            problems = [Problem("plugin_env_missing", pid, exc.message) for pid in sorted(wanted)]
            return RunPlugins(problems=problems)
        if fault is not None:
            fault("read")
        result = _plan(layout, lock, data, wanted, environ)  # 검증(digest)은 op.lock 밖
        last = result
        with layout.op():
            if _read(layout.lock) != data:
                continue  # 그 사이 설치가 커밋했다: 새 잠금으로 다시 고른다
            if not all(envs_mod.still_complete(env.folder) for env in result.envs):
                continue  # 고른 폴더를 gc가 지우기 시작했다
            if not all(envs_mod.still_complete(p) for p in result.unreadable):
                # 검증 중 후보가 사라졌다(설치 커밋 뒤 gc 등): 새 스냅샷으로 다시. 폴더·잠금이
                # 그대로인데 읽지 못했으면 이번 실행만 환경 없음 (깨짐으로 기록하지 않는다)
                continue
            if not _mark(result, ident):
                continue  # 표식을 만들지 못했다(그 사이 지워짐 등): 만든 것은 지웠다
        if fault is not None:
            fault("marked")
        return result
    # 재시도를 다 썼다: 마지막에 읽은 잠금으로 검증 진단만 낸다 (워커 없음). 잠금 해시는 그 잠금의
    # 것을 남기고(run.json 형식), 노드는 커밋된 wheel의 스키마로 등록하게 한다
    # (unknown_node_type 없음)
    message = "kookabug.lock이 실행을 준비하는 동안 계속 바뀌었다"
    assert last is not None  # 반복은 한 번 이상 돈다
    failed = RunPlugins(
        lock_bytes=last.lock_bytes,
        lock_sha256=last.lock_sha256,
        versions=last.versions,
        problems=[Problem("plugin_env_missing", pid, message) for pid in sorted(wanted)],
    )
    if last.lock_bytes is not None:
        entries = parse_lock(last.lock_bytes)["plugins"]
        failed.unready.update(_schemas(layout, [e for e in entries if e["id"] in wanted]))
    return failed


def _mark(result: RunPlugins, ident: ProcessId) -> bool:
    """고른 환경마다 사용 표식을 만든다 (op.lock 안). 하나라도 실패하면 만든 것을 지우고 False."""
    try:
        for env in result.envs:
            folder = env.folder / envs_mod.IN_USE_DIR
            folder.mkdir(exist_ok=True)
            marker = folder / marker_name(ident)
            # 쓰기 전에 목록에 넣는다: 파일을 만든 뒤 쓰기가 실패해도 정리된다
            result.markers.append(marker)
            marker.write_bytes(b"")
    except OSError:
        result.release()
        return False
    return True


def _plan(
    layout: Layout,
    lock: Mapping[str, Any],
    data: bytes,
    wanted: set[str],
    environ: Mapping[str, str],
) -> RunPlugins:
    from kookabug_core.plugins.ops import AppInfo

    entries = {str(p["id"]): p for p in lock["plugins"]}
    result = RunPlugins(
        lock_bytes=data,
        lock_sha256=lock_sha256(dict(lock)),
        versions={pid: str(e["version"]) for pid, e in entries.items()},
    )
    result.problems.extend(_not_installed(wanted - entries.keys()))
    installed = sorted(wanted & entries.keys())
    if not installed:
        return result
    try:
        stale = AppInfo.detect(environ).stale_reason(lock)
    except PluginError as exc:
        stale = exc.message
    if stale is not None:
        for pid in installed:
            result.problems.append(
                Problem(
                    "plugin_env_stale",
                    pid,
                    f"{pid}: {stale}. 이 앱으로 쓰려면 kookabug plugin relock (사람이 확인)",
                )
            )
        result.unready.update(_schemas(layout, [entries[pid] for pid in installed]))
        return result
    _choose_envs(layout, lock, installed, entries, result)
    if result.problems:
        # 워커를 띄우지 않는다: 쓰는 설치 플러그인 노드 전부를 커밋된 wheel의 스키마로 (검증용)
        result.unready.update(_schemas(layout, [entries[pid] for pid in installed]))
    return result


def _choose_envs(
    layout: Layout,
    lock: Mapping[str, Any],
    installed: Sequence[str],
    entries: Mapping[str, Mapping[str, Any]],
    result: RunPlugins,
) -> None:
    by_env: dict[str, list[LockedPlugin]] = {}
    for pid in installed:
        plugin = LockedPlugin.from_lock(entries[pid])
        by_env.setdefault(plugin.env, []).append(plugin)
    for name, plugins in sorted(by_env.items()):
        env = lock["environments"].get(name)
        chosen = (
            envs_mod.Selection(None)
            if env is None
            else envs_mod.select(layout.envs, name, env["fingerprint"], env["digest"])
        )
        folder = chosen.folder
        if folder is None:
            result.unreadable.extend(chosen.unreadable)
            why = (
                "의 파일을 읽을 수 없다 (다시 실행하거나 kookabug plugin verify)"
                if chosen.unreadable
                else "이(가) 준비되지 않았다 (kookabug plugin sync)"
            )
            for plugin in plugins:
                result.problems.append(
                    Problem("plugin_env_missing", plugin.id, f"{plugin.id}의 환경 {name}{why}")
                )
            continue
        result.envs.append(EnvUse(name, folder, tuple(plugins)))


def check_hello(env: EnvUse, plugins: Sequence[Mapping[str, Any]]) -> tuple[HelloCode, str] | None:
    """워커 hello의 플러그인 목록을 잠금과 대조한다. 맞으면 None, 틀리면 (코드, 이유)."""
    expected = {p.id: p for p in env.plugins}
    got = {str(p.get("id")): p for p in plugins}
    if set(got) != set(expected):
        return (
            "plugin_schema_mismatch",
            f"환경 {env.name}의 워커가 알린 플러그인 {sorted(got)} ≠ 잠금 {sorted(expected)}",
        )
    for pid, locked in sorted(expected.items()):
        schema = got[pid].get("schema")
        if not isinstance(schema, dict):
            return ("plugin_schema_mismatch", f"{pid}: 워커가 노드 스키마를 주지 않았다")
        try:
            digest = schema_digest(schema)  # pyright: ignore[reportUnknownArgumentType]
        except (TypeError, ValueError) as exc:
            return ("plugin_schema_mismatch", f"{pid}: 노드 스키마를 읽을 수 없다: {exc}")
        if digest != locked.schema_sha256:
            return (
                "plugin_schema_mismatch",
                f"{pid}: 워커의 노드 스키마가 잠금의 schema_sha256과 다르다",
            )
        nodes: Any = schema.get("nodes", [])  # pyright: ignore[reportUnknownMemberType]
        for node in nodes:
            effects = set(node.get("effects", []))
            if extra := sorted(effects - locked.permissions):
                return (
                    "plugin_permission_exceeded",
                    f"{node.get('type')}: effects {extra}이(가) 잠금의 permissions 밖이다",
                )
    return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _schemas(layout: Layout, entries: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    from kookabug_core.plugins.manifest import read_wheel

    found: dict[str, dict[str, Any]] = {}
    for entry in entries:
        path = layout.wheel_path(str(entry["wheel"]))
        try:
            if not path.is_file() or _sha256(path) != entry["wheel_sha256"]:
                continue
            schema = read_wheel(path).schema
        except OSError, PluginError:
            continue
        if schema_digest(schema) == entry["schema_sha256"]:
            found[str(entry["id"])] = schema
    return found


def installed_schemas(root: Path) -> dict[str, dict[str, Any]]:
    """잠금의 플러그인 노드 스키마 (ID → 문서). 잠금이 없거나 깨졌으면 빈 것. 커밋된 wheel이 없거나
    잠금과 다른 플러그인은 뺀다 — 코드는 import하지 않는다."""
    layout = Layout(Path(root))
    data = _read(layout.lock)
    if data is None:
        return {}
    try:
        lock = parse_lock(data)
    except PluginError:
        return {}
    return _schemas(layout, lock["plugins"])


def inspect(
    root: Path, used: Iterable[str], *, stale: Callable[[Mapping[str, Any]], str | None]
) -> tuple[list[Problem], dict[str, str]]:
    """편집기 사전 검증용 (daemon): `acquire`와 같은 판정을 **읽기만으로** — op.lock·사용 표식·
    digest 재계산·깨짐 기록 없음 (완성 표식의 지문만 본다). 실행은 runner가 다시 검증한다.
    `stale(잠금)`: 조건(D10)이 앱과 다르면 이유. (문제, 잠금의 플러그인 판)."""
    wanted = set(used)
    if not wanted:
        return [], {}
    layout = Layout(Path(root))
    data = _read(layout.lock)
    if data is None:
        return _not_installed(wanted), {}
    try:
        lock = parse_lock(data)
    except PluginError as exc:
        return [Problem("plugin_env_missing", pid, exc.message) for pid in sorted(wanted)], {}
    entries = {str(p["id"]): p for p in lock["plugins"]}
    versions = {pid: str(e["version"]) for pid, e in entries.items()}
    problems = _not_installed(wanted - entries.keys())
    installed = sorted(wanted & entries.keys())
    if installed and (reason := stale(lock)) is not None:
        message = "{pid}: " + reason + ". 이 앱으로 쓰려면 kookabug plugin relock (사람이 확인)"
        problems += [Problem("plugin_env_stale", pid, message.format(pid=pid)) for pid in installed]
        return problems, versions
    for pid in installed:
        name = str(entries[pid]["env"])
        env = lock["environments"].get(name)
        if env is None or envs_mod.find_env(layout.envs, name, env["fingerprint"]) is None:
            why = (
                "이(가) 깨졌다"
                if env is not None and envs_mod.broken_of(layout.envs, name, env["fingerprint"])
                else "이(가) 준비되지 않았다"
            )
            problems.append(
                Problem(
                    "plugin_env_missing",
                    pid,
                    f"{pid}의 환경 {name}{why} (플러그인 화면의 [준비…] 또는 kookabug plugin sync)",
                )
            )
    return problems, versions


def release_markers(root: Path, ident: ProcessId) -> int:
    """그 runner의 사용 표식을 모두 지운다 (감독자 — runner가 죽었을 때). 지운 수."""
    envs = Layout(Path(root)).envs
    if not envs.is_dir():
        return 0
    name = marker_name(ident)
    removed = 0
    for folder in envs.iterdir():
        marker = folder / envs_mod.IN_USE_DIR / name
        with contextlib.suppress(OSError):
            marker.unlink()
            removed += 1
    return removed
