"""플러그인 설치 거래 (M6 계획 3.5 — 엄격: 사용자 파일 손상).

    busy.lock → ⓪ 남은 staging 정리 → ① 원천 받기(코드 실행 없음) → ② 정적 읽기·검사
    → ③ 신뢰 확인 ── 여기까지 취소하면 실행된 코드 없음
    → ④ 해석·환경 배정 → ⑤ wheel 확정(wheel 원천은 받은 그대로) → ⑥ 최종 지문
    → ⑦ 실행 환경: (가) 같은 지문의 완성 환경 = 읽기 검증만 / (나) 새 확정 경로에 설치·검증·표식
    → ⑧ wheel 보관 plugins/wheels/<sha256>/<원래 이름> → ⑨ op.lock 안에서 잠금 바꿔 넣기 (커밋)
    → ⑩ staging/<작업> 지우기

- 자동 정리는 staging 안만이다. ⑦(나)의 환경 폴더·⑧의 보관 wheel은 커밋 전에 실패해도 남는다
  (잠금이 가리키지 않아 아무도 쓰지 않고, 같은 지문의 다음 설치가 재사용할 수 있다). 치우는 것은
  수동 `gc`뿐이다. 그래서 ⑨ 앞 어디서 실패·취소·죽음이 나도 잠금·기존 환경·기존 wheel은 그대로다
- 거래가 띄우는 모든 자식(uv·검증 인터프리터)은 거래마다 만든 설치 작업 Job 안이다
- B1 원천: wheel 파일. git·path·https wheel은 B2
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform as platform_mod
import shutil
import sys
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any, Final

from kookabug_core.plugins import envs as envs_mod
from kookabug_core.plugins.errors import PluginError
from kookabug_core.plugins.layout import Layout
from kookabug_core.plugins.lockfile import LOCK_FORMAT, read_lock, write_lock
from kookabug_core.plugins.manifest import (
    SDK_DIST,
    Manifest,
    min_core_satisfied,
    normalize_name,
    read_wheel,
)
from kookabug_core.plugins.resolve import (
    PLATFORM,
    IndexConfig,
    Package,
    ResolveFailure,
    resolve_with_app_sdk,
)
from kookabug_core.plugins.uv import ProcessRunner, app_root, find_uv, mask, remove_tree, uv_env
from kookabug_core.win import Job
from kookabug_core.workspace import Workspace
from kookabug_sdk import _faults

__all__ = ["SDK_WHEEL_ENV", "STAGES", "AppInfo", "PluginOps", "Preview"]

SDK_WHEEL_ENV: Final = "KOOKABUG_SDK_WHEEL"
STAGES: Final = (
    "fetched",
    "manifest",
    "confirmed",
    "resolved",
    "env_venv",
    "env_synced",
    "env_installed",
    "env_verified",
    "env_complete",
    "env_reused",
    "archived",
    "before_commit",
    "committed",
)
"""고장 주입 단계 (`plugins.stage` 지점의 이벤트, 검사의 `fault` 콜백 인자)."""
SHARED_ENV: Final = "shared"
WORKER_TIMEOUT_S: Final = 30.0

# 검증: 환경의 인터프리터가 워커 hello와 같은 함수(`collect_plugins`)로 스키마·digest를 낸다
_VERIFY_SCRIPT: Final = (
    "import json, os, re, sys\n"
    "from importlib import metadata\n"
    "dists = {re.sub(r'[-_.]+', '-', d.metadata['Name']).lower(): d.version\n"
    "         for d in metadata.distributions()}\n"
    "from kookabug_sdk.worker import collect_plugins\n"
    "plugins = collect_plugins(json.loads(sys.argv[1]))\n"
    "print('\\n' + json.dumps({'pid': os.getpid(), 'plugins': plugins, 'dists': dists}))\n"
)
"""설치된 배포판(플러그인 import 전)과 워커 hello의 플러그인 목록."""


@dataclass(frozen=True, slots=True)
class AppInfo:
    """앱의 재현 조건 (잠금 머리)과 환경을 만들 재료."""

    python: str
    python_full: str
    python_exe: Path
    sdk_wheel: Path
    sdk_version: str
    sdk_sha256: str
    core_version: str
    platform: str = PLATFORM

    @classmethod
    def detect(cls, environ: Mapping[str, str]) -> AppInfo:
        given = environ.get(SDK_WHEEL_ENV)
        if given:
            wheel = Path(given)
        else:
            found = sorted((app_root() / "plugin-sdk").glob("kookabug_sdk-*.whl"))
            if len(found) != 1:
                raise PluginError(
                    "app_incomplete",
                    "앱의 플러그인 SDK wheel(plugin-sdk\\kookabug_sdk-*.whl)이 없다",
                )
            wheel = found[0]
        if not wheel.is_file():
            raise PluginError("app_incomplete", f"SDK wheel {wheel}이(가) 없다")
        try:
            core = metadata.version("kookabug-core")
        except metadata.PackageNotFoundError:
            core = "0+dev"
        info = sys.version_info
        return cls(
            python=f"{info.major}.{info.minor}",
            python_full=platform_mod.python_version(),
            python_exe=Path(sys.base_prefix) / "python.exe",
            sdk_wheel=wheel,
            sdk_version=wheel.name.split("-")[1],
            sdk_sha256=_sha256(wheel),
            core_version=core,
        )

    def sdk(self) -> dict[str, str]:
        return {"version": self.sdk_version, "wheel_sha256": self.sdk_sha256}

    def stale_reason(self, lock: Mapping[str, Any]) -> str | None:
        """잠금 조건이 앱과 다르면 이유 (D10). 같으면 None."""
        if lock.get("python") != self.python:
            return f"잠금의 Python {lock.get('python')} ≠ 앱 {self.python}"
        if lock.get("platform") != self.platform:
            return f"잠금의 플랫폼 {lock.get('platform')} ≠ 앱 {self.platform}"
        if lock.get("sdk") != self.sdk():
            return f"잠금의 SDK {lock.get('sdk', {}).get('version')} ≠ 앱 {self.sdk_version}"
        return None


@dataclass(frozen=True, slots=True)
class Preview:
    """③ 신뢰 확인에 보이는 것."""

    op_id: str
    id: str
    title: str | None
    version: str
    dist: str
    source: dict[str, Any]
    permissions: list[str]
    dependencies: list[str]
    isolation: str
    replaces: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "op_id": self.op_id,
            "id": self.id,
            "title": self.title,
            "version": self.version,
            "dist": self.dist,
            "source": self.source,
            "permissions": self.permissions,
            "dependencies": self.dependencies,
            "isolation": self.isolation,
            "replaces": self.replaces,
        }


@dataclass
class _EnvPlan:
    name: str
    plugins: list[dict[str, Any]]
    packages: list[Package]
    wheels: dict[str, Path] = field(default_factory=dict[str, Path])
    """플러그인 ID → 설치할 wheel (새 것은 staging, 기존 것은 보관 경로)."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _empty_lock(app: AppInfo, index: IndexConfig) -> dict[str, Any]:
    return {
        "format": LOCK_FORMAT,
        "python": app.python,
        "python_full": app.python_full,
        "platform": app.platform,
        "sdk": app.sdk(),
        "index": mask(index.url),
        "plugins": [],
        "environments": {},
    }


class PluginOps:
    """워크스페이스 하나의 플러그인 작업 (CLI·daemon 공통). 작업마다 새로 만들어도 된다."""

    def __init__(
        self,
        root: Path,
        *,
        environ: Mapping[str, str] | None = None,
        app: AppInfo | None = None,
        fault: Callable[[str], None] | None = None,
        worker_timeout_s: float = WORKER_TIMEOUT_S,
    ) -> None:
        self.root = Path(root).resolve()
        self.layout = Layout(self.root)
        self.environ = dict(os.environ if environ is None else environ)
        self._app = app
        self.fault = fault
        self.worker_timeout_s = worker_timeout_s
        self.calls: list[tuple[str, ...]] = []
        """이 객체의 거래가 부른 자식 명령 (검사가 본다)."""
        self._cancel = threading.Event()
        self._job: Job | None = None

    # ------------------------------------------------------------ 공통

    @property
    def app(self) -> AppInfo:
        if self._app is None:
            self._app = AppInfo.detect(self.environ)
        return self._app

    def index(self) -> IndexConfig:
        ws = Workspace.open(self.root)
        local = (ws.local or {}).get("plugin_index")
        return IndexConfig.from_config(ws.config.get("plugin_index"), local)

    def read_lock(self) -> tuple[dict[str, Any] | None, str | None]:
        with self.layout.op():
            return read_lock(self.layout.lock)

    def cancel(self) -> None:
        """진행 중인 거래를 취소한다 (Job을 끝낸다). 커밋 뒤면 효과 없음."""
        self._cancel.set()
        job = self._job
        if job is not None:
            with contextlib.suppress(OSError):
                job.terminate()

    def _point(self, stage: str) -> None:
        if self._cancel.is_set():
            raise PluginError("cancelled", "작업을 취소했다", stage=stage)
        if self.fault is not None:
            self.fault(stage)
        _faults.fault_point("plugins.stage", event=stage)

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[tuple[str, Path, ProcessRunner]]:
        """busy.lock + ⓪ staging 정리 + 설치 작업 Job. 실패하면 이 작업의 staging만 지운다."""
        with self.layout.busy():
            remove_tree(self.layout.staging)  # ⓪ 남은 staging (staging/ 아래만)
            op_id = uuid.uuid4().hex
            staging = self.layout.staging / op_id
            staging.mkdir(parents=True)
            job = Job.create()
            self._job = job
            runner = ProcessRunner(
                uv_env(self.environ),
                self.layout.logs / f"{op_id}.log",
                job,
            )
            runner.calls = self.calls
            try:
                yield op_id, staging, runner
            finally:
                self._job = None
                job.close()  # 남은 자식(손자 포함)을 끝낸다
                with contextlib.suppress(OSError):
                    remove_tree(staging)

    # ------------------------------------------------------------ add

    def add(
        self,
        source: str,
        *,
        isolation: str | None = None,
        sha256: str | None = None,
        confirm: Callable[[Preview], bool],
    ) -> dict[str, Any]:
        """원천 하나를 설치한다. 성공하면 결과, 실패하면 `PluginError` (잠금·기존 환경 그대로)."""
        with self._transaction() as (op_id, staging, runner):
            # ① 원천 받기 (B1: wheel 파일. 코드 실행 없음)
            wheel, source_info = self._fetch_wheel(source, sha256, staging)
            self._point("fetched")
            # ② 정적 읽기·검사
            manifest = read_wheel(wheel)
            with self.layout.op():
                lock, revision = read_lock(self.layout.lock)
            index = self.index()
            app = self.app
            lock = lock or _empty_lock(app, index)
            if (stale := app.stale_reason(lock)) is not None and lock["plugins"]:
                raise PluginError(
                    "sdk_incompatible", f"{stale}. kookabug plugin relock 먼저", stage="manifest"
                )
            if any(p["id"] == manifest.id for p in lock["plugins"]):
                raise PluginError(
                    "plugin_id_taken", f"플러그인 {manifest.id}이(가) 이미 있다", stage="manifest"
                )
            min_core = manifest.header.get("min_core")
            if min_core and not min_core_satisfied(app.core_version, str(min_core)):
                raise PluginError(
                    "core_too_old",
                    f"{manifest.id}은(는) 앱 {min_core} 이상이 필요하다 (지금 {app.core_version})",
                    stage="manifest",
                )
            choice = isolation or manifest.isolation
            if choice not in ("auto", "shared", "isolated"):
                raise PluginError(
                    "manifest_invalid", f"모르는 isolation {choice}", stage="manifest"
                )
            self._point("manifest")
            # ③ 신뢰 확인
            preview = Preview(
                op_id=op_id,
                id=manifest.id,
                title=manifest.header.get("title"),
                version=manifest.version,
                dist=manifest.dist,
                source=source_info,
                permissions=manifest.permissions,
                dependencies=list(manifest.dependencies),
                isolation=choice,
            )
            if not confirm(preview):
                raise PluginError("cancelled", "신뢰 확인에서 취소했다", stage="confirm")
            self._point("confirmed")
            # ④ 해석·환경 배정
            work = staging / "resolve"
            self._check_sdk(runner, work, manifest)
            entry: dict[str, Any] = {
                "id": manifest.id,
                "dist": manifest.dist,
                "version": manifest.version,
                "manifest": manifest.lock_manifest(),
                "requires": list(manifest.requires),
                "schema_sha256": manifest.schema_sha256,
                "source": source_info,
            }
            plan = self._assign(runner, work, lock, manifest, entry, choice, index)
            self._point("resolved")
            # ⑤⑥ wheel 확정 (wheel 원천은 받은 그대로) → 최종 지문
            dist_dir = staging / "dist"
            dist_dir.mkdir()
            built = dist_dir / manifest.wheel_name
            shutil.copyfile(wheel, built)
            wheel_sha = _sha256(built)
            entry["wheel_sha256"] = wheel_sha
            entry["wheel"] = f"plugins/wheels/{wheel_sha}/{manifest.wheel_name}"
            plan.wheels[manifest.id] = built
            new_lock = dict(lock)
            new_lock["plugins"] = [*lock["plugins"], entry]
            new_lock["environments"] = dict(lock["environments"])
            new_lock.update(
                python=app.python,
                python_full=app.python_full,
                platform=app.platform,
                sdk=app.sdk(),
                index=mask(index.url),
            )
            # ⑦ 실행 환경
            reused = self._prepare_env(runner, op_id, staging, plan, new_lock, index)
            # ⑧ wheel 보관
            self._archive(built, entry["wheel"], wheel_sha)
            self._point("archived")
            # ⑨ 커밋
            new_revision = self._commit(new_lock, revision)
            self._point("committed")
            return {
                "op_id": op_id,
                "plugin": entry,
                "env": plan.name,
                "reused": reused,
                "revision": new_revision,
            }

    def _fetch_wheel(
        self, source: str, sha256: str | None, staging: Path
    ) -> tuple[Path, dict[str, Any]]:
        text = source.strip()
        if text.startswith(("git+", "http://", "https://", "file://", "ssh://")):
            raise PluginError(
                "source_refused",
                "이 판은 wheel 파일 원천만 설치한다 (git·폴더·https wheel은 다음 판)",
                stage="fetch",
            )
        path = Path(text)
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.is_dir() or path.suffix != ".whl":
            raise PluginError(
                "source_refused", f"{source}은(는) wheel 파일(.whl)이 아니다", stage="fetch"
            )
        if not path.is_file():
            raise PluginError("source_unavailable", f"{source}이(가) 없다", stage="fetch")
        target = staging / "src" / path.name
        target.parent.mkdir(parents=True)
        try:
            shutil.copyfile(path, target)
        except OSError as exc:
            raise PluginError(
                "source_unavailable", f"{source}을(를) 읽을 수 없다: {exc}", stage="fetch"
            ) from exc
        digest = _sha256(target)
        if sha256 is not None and sha256.lower() != digest:
            raise PluginError("source_unavailable", "wheel sha256이 다르다", stage="fetch")
        resolved = path.resolve()
        rel = (
            resolved.relative_to(self.root).as_posix()
            if resolved.is_relative_to(self.root)
            else str(resolved)
        )
        return target, {"kind": "wheel", "path": rel, "sha256": digest}

    def _check_sdk(self, runner: ProcessRunner, work: Path, manifest: Manifest) -> None:
        """플러그인의 SDK 범위가 앱 SDK를 받는가 (네트워크 없이 앱 SDK wheel만으로 해석)."""
        app = self.app
        try:
            resolve_with_app_sdk(
                runner,
                find_uv(self.environ),
                work,
                list(manifest.sdk_requires),
                python=app.python,
                index=IndexConfig(),
                sdk_wheel=self._app_sdk_wheel(work),
                no_index=True,
            )
        except ResolveFailure as exc:
            raise PluginError(
                "sdk_incompatible",
                f"{manifest.id}의 SDK 범위({', '.join(manifest.sdk_requires)})가 앱 SDK "
                f"{app.sdk_version}을(를) 받지 않는다",
                stage="resolve",
                plugin=manifest.id,
            ) from exc

    def _assign(
        self,
        runner: ProcessRunner,
        work: Path,
        lock: dict[str, Any],
        manifest: Manifest,
        entry: dict[str, Any],
        choice: str,
        index: IndexConfig,
    ) -> _EnvPlan:
        """④ 해석해 환경을 정한다 (D7). 공유면 기존 공유 고정 판 전부가 제약이다. 공유·격리 모두
        SDK는 앱 SDK wheel 파일 직접 참조(`resolve_with_app_sdk`)라, 전이 의존성의 SDK 요구도
        앱 SDK artifact로만 풀린다 (안 되면 `sdk_incompatible`)."""
        uv = find_uv(self.environ)
        app = self.app
        deps = list(manifest.dependencies)
        sdk_wheel = self._app_sdk_wheel(work)

        def compile_(requirements: list[str], pins: list[str]) -> list[Package]:
            return resolve_with_app_sdk(
                runner,
                uv,
                work,
                requirements,
                python=app.python,
                index=index,
                sdk_wheel=sdk_wheel,
                constraints=pins,
            )

        def alone() -> list[Package]:
            try:
                return compile_(deps, [])
            except ResolveFailure as exc:
                if exc.kind == "unsatisfiable" and SDK_DIST in exc.message:
                    raise self._sdk_error(manifest.id, _last_line(exc.message)) from exc
                raise _resolve_error(exc) from exc

        if choice == "isolated":
            entry.update(env=f"iso-{manifest.id}", isolated_because="declared")
            return _EnvPlan(f"iso-{manifest.id}", [entry], alone())

        shared = lock["environments"].get(SHARED_ENV)
        members = [p for p in lock["plugins"] if p["env"] == SHARED_ENV]
        old_packages = [Package.from_json(p) for p in (shared or {}).get("packages", [])]
        requirements = sorted(
            {r for p in members for r in p["requires"] if not _is_sdk(r)} | set(deps)
        )
        pins = [f"{p.name}=={p.version}" for p in old_packages]
        try:
            packages = compile_(requirements, pins)
        except ResolveFailure as exc:
            if exc.kind == "sdist_only":
                raise _resolve_error(exc) from exc
            mine = alone()  # 혼자도 안 되면 해석 불가 (충돌이 아님)
            if choice == "shared":
                raise PluginError(
                    "plugin_conflict",
                    f"{manifest.id}의 의존성이 공유 환경과 맞지 않는다",
                    stage="resolve",
                    conflicts=_conflicts(old_packages, mine),
                ) from exc
            entry.update(
                env=f"iso-{manifest.id}",
                isolated_because="conflict",
                conflicts=_conflicts(old_packages, mine),
            )
            return _EnvPlan(f"iso-{manifest.id}", [entry], mine)
        entry.update(env=SHARED_ENV, isolated_because=None)
        plan = _EnvPlan(SHARED_ENV, [*members, entry], packages)
        for member in members:
            plan.wheels[member["id"]] = self._archived_wheel(member)
        return plan

    def _sdk_error(self, plugin_id: str, detail: str) -> PluginError:
        return PluginError(
            "sdk_incompatible",
            f"{plugin_id}의 의존성이 앱 SDK {self.app.sdk_version}과(와) 맞지 않는다: "
            f"{mask(detail)}",
            stage="resolve",
            plugin=plugin_id,
        )

    def _app_sdk_wheel(self, work: Path) -> Path:
        """거래 작업 폴더에 둔 앱 SDK wheel 사본 (해석의 직접 참조 대상). 바이트를 대조한다."""
        target = work / "sdk" / self.app.sdk_wheel.name
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.app.sdk_wheel, target)
        if _sha256(target) != self.app.sdk_sha256:
            raise PluginError(
                "app_incomplete", "앱 SDK wheel이 작업 중에 바뀌었다", stage="resolve"
            )
        return target

    def _archived_wheel(self, entry: Mapping[str, Any]) -> Path:
        """잠금의 보관 wheel 경로 (그대로 uv에 넘긴다). 넘기기 전에 바이트 sha256을 대조한다."""
        path = self.layout.wheel_path(str(entry["wheel"]))
        if not path.is_file() or _sha256(path) != entry["wheel_sha256"]:
            raise PluginError(
                "verify_failed",
                f"커밋된 wheel {entry['wheel']}이(가) 없거나 잠금의 sha256과 다르다",
                stage="env",
            )
        return path

    # ------------------------------------------------------------ ⑦ 환경

    def _prepare_env(
        self,
        runner: ProcessRunner,
        op_id: str,
        staging: Path,
        plan: _EnvPlan,
        new_lock: dict[str, Any],
        index: IndexConfig,
    ) -> bool:
        """그 환경을 고르고 잠금 `environments`를 채운다. 재사용(읽기 검증만)이면 True."""
        app = self.app
        packages_json = [p.to_json() for p in plan.packages]
        fp = envs_mod.fingerprint(
            python=app.python,
            platform=app.platform,
            sdk=app.sdk(),
            packages=packages_json,
            plugin_wheels=[str(p["wheel_sha256"]) for p in plan.plugins],
        )
        existing = envs_mod.find_env(self.layout.envs, plan.name, fp)
        if existing is not None:
            # (가) 읽기 검증만: uv·설치·표식 쓰기 없음. 틀리면 그 폴더는 손대지 않고 실패
            problem = envs_mod.verify_env(existing, fp)
            if problem is not None:
                raise PluginError(
                    "verify_failed", f"{existing.name}: {problem}", stage="verify", env=plan.name
                )
            marker = envs_mod.read_marker(existing) or {}
            digest = str(marker["digest"])
            self._point("env_reused")
            reused = True
        else:
            folder = self.layout.envs / envs_mod.folder_name(plan.name, fp, op_id)
            digest = self._create_env(runner, staging, folder, plan, fp, index)
            reused = False
        new_lock["environments"][plan.name] = {
            "plugins": sorted(p["id"] for p in plan.plugins),
            "packages": packages_json,
            "fingerprint": fp,
            "digest": digest,
        }
        return reused

    def _create_env(
        self,
        runner: ProcessRunner,
        staging: Path,
        folder: Path,
        plan: _EnvPlan,
        fp: str,
        index: IndexConfig,
    ) -> str:
        """(나) 새 확정 경로에 venv → 의존성 sync(빈 새 환경에만) → SDK·플러그인 wheel --no-deps
        → 검증 → 완성 표식(마지막). 실패해도 폴더는 남는다 (미완성 = 없는 것, gc 몫)."""
        uv = find_uv(self.environ)
        app = self.app
        folder.parent.mkdir(parents=True, exist_ok=True)
        self._uv(
            runner,
            [uv, "venv", folder, "--python", app.python_exe, "--no-project", "--quiet"],
            cwd=staging,
        )
        self._point("env_venv")
        python = envs_mod.env_python(folder)
        if plan.packages:
            req = staging / f"env-{plan.name}.txt"
            req.write_text("".join(p.requirement() + "\n" for p in plan.packages), encoding="utf-8")
            self._uv(
                runner,
                [
                    uv,
                    "pip",
                    "sync",
                    req,
                    "--python",
                    python,
                    "--require-hashes",
                    "--only-binary",
                    ":all:",
                    "--quiet",
                    *index.args(),
                ],
                cwd=staging,
            )
        self._point("env_synced")
        wheels = [plan.wheels[p["id"]] for p in plan.plugins]
        self._uv(
            runner,
            [
                uv,
                "pip",
                "install",
                "--python",
                python,
                "--no-deps",
                "--no-index",
                "--quiet",
                app.sdk_wheel,
                *wheels,
            ],
            cwd=staging,
        )
        self._point("env_installed")
        expected = {p.name: p.version for p in plan.packages}
        expected[SDK_DIST] = app.sdk_version
        for plugin in plan.plugins:
            expected[normalize_name(str(plugin["dist"]))] = str(plugin["version"])
        self._verify_hello(runner, python, plan.plugins, staging, expected)
        self._point("env_verified")
        digest = envs_mod.env_digest(folder)
        envs_mod.write_marker(folder, env=plan.name, fp=fp, digest=digest)
        self._point("env_complete")
        return digest

    def _uv(self, runner: ProcessRunner, args: Sequence[str | Path], *, cwd: Path) -> None:
        done = runner.run(args, stage="env", cwd=cwd)
        if done.returncode != 0:
            raise PluginError(
                "env_create_failed",
                f"uv {args[1]}이(가) 실패했다: {mask(_last_line(done.stderr or done.stdout))}",
                stage="env",
            )

    def _verify_hello(
        self,
        runner: ProcessRunner,
        python: Path,
        plugins: Sequence[Mapping[str, Any]],
        staging: Path,
        expected: Mapping[str, str],
    ) -> None:
        """환경 인터프리터로 워커 hello와 같은 스키마·digest를 받아 잠금 값과 대조하고, 설치된
        배포판 전체(`importlib.metadata`)가 잠글 목록(`expected`, 정규 이름 → 판)과 같은지 본다."""
        modules = [m for p in plugins for m in p["manifest"]["modules"]]
        saved = runner.timeout_s
        runner.timeout_s = self.worker_timeout_s
        try:
            done = runner.run(
                [python, "-I", "-c", _VERIFY_SCRIPT, json.dumps(modules)],
                stage="verify",
                cwd=staging,
            )
        finally:
            runner.timeout_s = saved
        if done.returncode != 0:
            raise PluginError(
                "verify_failed",
                f"플러그인 모듈을 import할 수 없다: {_last_line(done.stderr)}",
                stage="verify",
            )
        try:
            hello = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise PluginError("verify_failed", "검증 결과를 읽을 수 없다", stage="verify") from exc
        found = {str(p["id"]): p for p in hello["plugins"]}
        for plugin in plugins:
            got = found.get(str(plugin["id"]))
            if got is None:
                raise PluginError(
                    "verify_failed",
                    f"{plugin['id']}의 노드를 찾지 못했다 (modules의 노드 ID가 다르다)",
                    stage="verify",
                )
            if got["digest"] != plugin["schema_sha256"]:
                raise PluginError(
                    "verify_failed",
                    f"{plugin['id']}: 코드의 노드가 wheel의 스키마 파일과 다르다 (schema digest)",
                    stage="verify",
                )
            allowed = set(plugin["manifest"].get("permissions", []))
            for node in got["schema"]["nodes"]:
                if extra := sorted(set(node.get("effects", [])) - allowed):
                    raise PluginError(
                        "verify_failed",
                        f"{node['type']}: effects {extra}이(가) permissions 밖이다",
                        stage="verify",
                    )
        if extra_ids := sorted(set(found) - {str(p["id"]) for p in plugins}):
            raise PluginError(
                "verify_failed", f"선언하지 않은 플러그인 노드가 있다: {extra_ids}", stage="verify"
            )
        # 잠글 배포판 판 = 실제 설치 판 (빠진 것·남는 것·판 다름 모두 실패)
        installed = {str(k): str(v) for k, v in hello["dists"].items()}
        if installed != expected:
            diff = sorted(
                f"{name}: 잠금 {expected.get(name)} / 설치 {installed.get(name)}"
                for name in set(expected) | set(installed)
                if expected.get(name) != installed.get(name)
            )
            raise PluginError(
                "verify_failed",
                f"설치된 배포판이 잠금과 다르다: {'; '.join(diff)}",
                stage="verify",
            )

    # ------------------------------------------------------------ ⑧ ⑨

    def _archive(self, built: Path, rel: str, sha: str) -> None:
        """⑧ plugins/wheels/<sha256>/<원래 이름>. 있으면 바이트 대조만, 없으면 같은 폴더 임시 파일
        → replace (다른 볼륨이어도 같은 폴더 안 교체)."""
        target = self.layout.wheel_path(rel)
        if target.is_file():
            if _sha256(target) != sha:
                raise PluginError(
                    "verify_failed",
                    f"보관 wheel {rel}이(가) 이름의 sha256과 다르다",
                    stage="archive",
                )
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / f".{target.name}.{uuid.uuid4().hex[:8]}.tmp"
        try:
            shutil.copyfile(built, tmp)
            os.replace(tmp, target)
        except OSError as exc:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise PluginError(
                "env_create_failed", f"wheel을 보관할 수 없다: {exc}", stage="archive"
            ) from exc

    def _commit(self, lock: dict[str, Any], revision: str | None) -> str:
        """⑨ op.lock 안에서 revision 확인 → 바꿔 넣기."""
        with self.layout.op():
            return write_lock(
                self.layout.lock,
                lock,
                revision,
                before_replace=lambda: self._point("before_commit"),
            )

    # ------------------------------------------------------------ remove

    def remove(
        self, plugin_id: str, *, confirm: Callable[[dict[str, Any]], bool]
    ) -> dict[str, Any]:
        """잠금에서 빼고 바꿔 넣는다. 공유에서 빼면 남은 플러그인 + 기존 판으로 새 지문 공유 환경을
        ⑦로 고른다 (해석·빌드 없음). wheel·폴더는 gc가 치운다."""
        with self._transaction() as (op_id, staging, runner):
            with self.layout.op():
                lock, revision = read_lock(self.layout.lock)
            entry = next((p for p in (lock or {}).get("plugins", []) if p["id"] == plugin_id), None)
            if lock is None or entry is None:
                raise PluginError("plugin_not_found", f"플러그인 {plugin_id}이(가) 없다")
            if (stale := self.app.stale_reason(lock)) is not None:
                raise PluginError("sdk_incompatible", f"{stale}. kookabug plugin relock 먼저")
            if not confirm({"op_id": op_id, "id": plugin_id, "version": entry["version"]}):
                raise PluginError("cancelled", "확인에서 취소했다", stage="confirm")
            new_lock = dict(lock)
            new_lock["plugins"] = [p for p in lock["plugins"] if p["id"] != plugin_id]
            new_lock["environments"] = dict(lock["environments"])
            env_name = str(entry["env"])
            members = [p for p in new_lock["plugins"] if p["env"] == env_name]
            reused = True
            if not members:
                new_lock["environments"].pop(env_name, None)
            else:
                old = lock["environments"][env_name]
                plan = _EnvPlan(
                    env_name,
                    members,
                    [Package.from_json(p) for p in old["packages"]],
                    {str(m["id"]): self._archived_wheel(m) for m in members},
                )
                reused = self._prepare_env(runner, op_id, staging, plan, new_lock, self.index())
            new_revision = self._commit(new_lock, revision)
            self._point("committed")
            return {
                "op_id": op_id,
                "removed": plugin_id,
                "reused": reused,
                "revision": new_revision,
            }

    # ------------------------------------------------------------ list·verify

    def status(self) -> dict[str, Any]:
        """`list`: 잠금 항목 + 환경 상태(`ready`·`missing`·`stale`). digest는 다시 계산하지
        않는다."""
        lock, revision = self.read_lock()
        if lock is None:
            return {"revision": None, "plugins": [], "environments": {}, "stale_reason": None}
        stale = self.app.stale_reason(lock)
        environments: dict[str, Any] = {}
        for name, env in lock["environments"].items():
            folder = envs_mod.find_env(self.layout.envs, name, env["fingerprint"])
            status = "stale" if stale else ("ready" if folder is not None else "missing")
            environments[name] = {
                "status": status,
                "folder": None if folder is None else folder.name,
                "plugins": env["plugins"],
            }
        plugins = [
            {**p, "env_status": environments.get(p["env"], {}).get("status", "missing")}
            for p in lock["plugins"]
        ]
        return {
            "revision": revision,
            "plugins": plugins,
            "environments": environments,
            "stale_reason": stale,
        }

    def verify(self) -> dict[str, Any]:
        """digest 재계산·잠금과 대조, 커밋된 wheel 바이트 대조. `ok`가 거짓이면 문제 목록."""
        lock, revision = self.read_lock()
        problems: list[dict[str, Any]] = []
        environments: dict[str, Any] = {}
        if lock is not None:
            for plugin in lock["plugins"]:
                path = self.layout.wheel_path(plugin["wheel"])
                if not path.is_file() or _sha256(path) != plugin["wheel_sha256"]:
                    problems.append(
                        {
                            "plugin": plugin["id"],
                            "problem": f"커밋된 wheel {plugin['wheel']}이(가) 없거나 다르다",
                        }
                    )
            stale = self.app.stale_reason(lock)
            for name, env in lock["environments"].items():
                folder = envs_mod.find_env(self.layout.envs, name, env["fingerprint"])
                if stale:
                    status, problem = "stale", stale
                elif folder is None:
                    status, problem = "missing", "환경이 없다 (kookabug plugin sync)"
                else:
                    problem = envs_mod.verify_env(folder, env["fingerprint"], env["digest"])
                    status = "ready" if problem is None else "broken"
                environments[name] = {"status": status, "folder": folder and folder.name}
                if problem is not None:
                    problems.append({"env": name, "status": status, "problem": problem})
        return {
            "ok": not problems,
            "revision": revision,
            "environments": environments,
            "problems": problems,
        }

    # ------------------------------------------------------------ gc

    def gc(self, *, confirm: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        from kookabug_core.plugins.gc import collect

        with self.layout.busy():
            return collect(self.layout, confirm)


def _is_sdk(requirement: str) -> bool:
    from kookabug_core.plugins.manifest import requirement_name

    return requirement_name(requirement) == SDK_DIST


def _resolve_error(exc: ResolveFailure) -> PluginError:
    if exc.kind == "sdist_only":
        return PluginError(
            "sdist_only_dependency",
            f"wheel이 없는 의존성이 있다: {', '.join(exc.names)} (의존성은 wheel만 쓴다)",
            stage="resolve",
            packages=list(exc.names),
        )
    return PluginError(
        "resolve_failed", f"의존성을 풀 수 없다: {mask(_last_line(exc.message))}", stage="resolve"
    )


def _conflicts(shared: Sequence[Package], mine: Sequence[Package]) -> list[str]:
    pinned = {p.name: p.version for p in shared}
    return sorted(p.name for p in mine if p.name in pinned and pinned[p.name] != p.version)


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""
