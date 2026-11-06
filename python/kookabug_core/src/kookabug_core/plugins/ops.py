"""플러그인 설치 거래 (M6 계획 3.5 — 엄격: 사용자 파일 손상).

    busy.lock → ⓪ 남은 staging 정리 → ① 원천 받기(코드 실행 없음, `sources`) → ② 정적 읽기·검사
    (wheel: zip / git·path: pyproject.toml) → ③ 신뢰 확인 ── 여기까지 취소하면 실행된 코드 없음
    → ④ 해석·환경 배정 → ⑤ (git·path) staging 임시 빌드 환경에서 `kookabug-sdk build`·`uv build`
    (wheel 원천은 받은 그대로) → ⑥ wheel 확정: 바이트 해시·스키마·②와 대조 → 최종 지문
    → ⑦ 실행 환경: (가) 같은 지문의 완성 환경 = 읽기 검증만 / (나) 새 확정 경로에 설치·검증·표식
    → ⑧ wheel 보관 plugins/wheels/<sha256>/<원래 이름> → ⑨ op.lock 안에서 잠금 바꿔 넣기 (커밋)
    → ⑩ staging/<작업> 지우기

- 자동 정리는 staging 안만이다. ⑦(나)의 환경 폴더·⑧의 보관 wheel은 커밋 전에 실패해도 남는다
  (잠금이 가리키지 않아 아무도 쓰지 않고, 같은 지문의 다음 설치가 재사용할 수 있다). 치우는 것은
  수동 `gc`뿐이다. 그래서 ⑨ 앞 어디서 실패·취소·죽음이 나도 잠금·기존 환경·기존 wheel은 그대로다
- 거래가 띄우는 모든 자식(git·uv·빌드·검증 인터프리터)은 거래마다 만든 설치 작업 Job 안이다
- `sync`·`relock`은 `sync.py`·`relock.py` (같은 ⑦·⑨, 빌드 없음, 보관 wheel 경로를 그대로 씀)
"""

from __future__ import annotations

import contextlib
import dataclasses
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

from packaging.version import Version

from kookabug_core.plugins import envs as envs_mod
from kookabug_core.plugins import sources, trust
from kookabug_core.plugins.errors import PluginError
from kookabug_core.plugins.layout import Layout
from kookabug_core.plugins.lockfile import LOCK_FORMAT, lock_sha256, read_lock, write_lock
from kookabug_core.plugins.manifest import (
    SDK_DIST,
    Manifest,
    ProjectManifest,
    min_core_satisfied,
    normalize_name,
    read_project_manifest,
    read_wheel,
    same_requirements,
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
    "built",
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
    """upgrade면 바꾸는 판."""
    untrusted: list[str] = field(default_factory=list[str])
    """이 PC에서 신뢰 확인하지 않은 잠금의 기존 플러그인 ID (같은 환경을 다시 만들면 그 코드도
    실행된다 — 같은 확인으로 함께 신뢰한다)."""

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
            "untrusted": self.untrusted,
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

    def _untrusted(self, lock: Mapping[str, Any], keep: Sequence[Mapping[str, Any]]) -> list[str]:
        """이 PC에서 신뢰 확인하지 않은 잠금이면 남는 플러그인 **전체** ID (환경 무관). 잠금을
        신뢰한다 = 그 잠금의 모든 플러그인을 신뢰한다 (U2)."""
        if not keep or trust.is_trusted(self.root, lock_sha256(dict(lock))):
            return []
        return sorted(str(p["id"]) for p in keep)

    def _remember(
        self,
        before: Mapping[str, Any],
        new_lock: dict[str, Any],
        shown: Sequence[str],
        *,
        confirmed: Sequence[str] = (),
    ) -> bool:
        """커밋한 잠금을 신뢰로 기억한다 — 이전 잠금을 이미 신뢰했거나, 새 잠금의 플러그인이 모두
        이번 확인에 나왔을 때만 (`shown`: 함께 보인 기존 플러그인, `confirmed`: 확인 대상 자체).
        확인에 다 나오지 않았으면 기억하지 않는다 (다음 sync가 다시 묻는다)."""
        ids = {str(p["id"]) for p in new_lock["plugins"]}
        trusted_before = not before["plugins"] or trust.is_trusted(
            self.root, lock_sha256(dict(before))
        )
        if not trusted_before and not ids <= set(shown) | set(confirmed):
            return False
        return trust.remember(self.root, lock_sha256(new_lock))

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
        ref: str | None = None,
        confirm: Callable[[Preview], bool],
    ) -> dict[str, Any]:
        """원천 하나를 설치한다 (`git+<url>[@ref]`·wheel 파일/https URL·폴더). 성공하면 결과,
        실패하면 `PluginError` (잠금·기존 환경 그대로)."""
        spec = sources.parse_source(source, ref=ref, sha256=sha256)
        return self._install(spec, None, isolation=isolation, confirm=confirm)

    def upgrade(
        self,
        plugin_id: str,
        *,
        ref: str | None = None,
        sha256: str | None = None,
        isolation: str | None = None,
        confirm: Callable[[Preview], bool],
    ) -> dict[str, Any]:
        """잠금에 기록된 원천을 다시 받아(git은 `ref`로 바꿀 수 있다) add와 같은 거래로 바꾼다."""
        return self._install(
            None, plugin_id, isolation=isolation, confirm=confirm, ref=ref, sha256=sha256
        )

    def _install(
        self,
        spec: sources.SourceSpec | None,
        replacing: str | None,
        *,
        isolation: str | None,
        confirm: Callable[[Preview], bool],
        ref: str | None = None,
        sha256: str | None = None,
    ) -> dict[str, Any]:
        with self._transaction() as (op_id, staging, runner):
            with self.layout.op():
                lock, revision = read_lock(self.layout.lock)
            old: dict[str, Any] | None = None
            if replacing is not None:
                old = next(
                    (p for p in (lock or {}).get("plugins", []) if p["id"] == replacing), None
                )
                if old is None:
                    raise PluginError("plugin_not_found", f"플러그인 {replacing}이(가) 없다")
                spec = sources.from_lock(old["source"], self.root, ref=ref)
                if sha256 is not None:
                    spec = dataclasses.replace(spec, sha256=sha256.lower())
            assert spec is not None
            # ① 원천 받기 (코드 실행 없음)
            fetched = sources.fetch(spec, staging / "src", runner, root=self.root)
            self._point("fetched")
            # ② 정적 읽기·검사 (wheel: zip / git·path: pyproject.toml)
            manifest: Manifest | ProjectManifest = (
                read_wheel(fetched.wheel)
                if fetched.wheel is not None
                else read_project_manifest(_project(fetched))
            )
            index = self.index()
            app = self.app
            lock = lock or _empty_lock(app, index)
            if (stale := app.stale_reason(lock)) is not None and lock["plugins"]:
                raise PluginError(
                    "sdk_incompatible", f"{stale}. kookabug plugin relock 먼저", stage="manifest"
                )
            if replacing is not None and manifest.id != replacing:
                raise PluginError(
                    "manifest_invalid",
                    f"원천의 플러그인 ID {manifest.id}이(가) {replacing}이(가) 아니다",
                    stage="manifest",
                )
            if replacing is None and any(p["id"] == manifest.id for p in lock["plugins"]):
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
            # ③ 신뢰 확인 (신뢰 확인 안 한 잠금이면 남는 플러그인 전체도 함께 보인다)
            others = [p for p in lock["plugins"] if p["id"] != replacing]
            untrusted = self._untrusted(lock, others)
            preview = Preview(
                op_id=op_id,
                id=manifest.id,
                title=manifest.header.get("title"),
                version=manifest.version,
                dist=manifest.dist,
                source=fetched.source,
                permissions=manifest.permissions,
                dependencies=list(manifest.dependencies),
                isolation=choice,
                replaces=None if old is None else str(old["version"]),
                untrusted=untrusted,
            )
            if not confirm(preview):
                raise PluginError("cancelled", "신뢰 확인에서 취소했다", stage="confirm")
            self._point("confirmed")
            # ④ 해석·환경 배정 (② 정적 의존성 목록 기준)
            work = staging / "resolve"
            self._check_sdk(runner, work, manifest.id, manifest.sdk_requires)
            base = dict(lock)
            base["plugins"] = others
            entry: dict[str, Any] = {
                "id": manifest.id,
                "dist": manifest.dist,
                "version": manifest.version,
                "manifest": manifest.lock_manifest(),
                "requires": list(manifest.requires),
                "source": fetched.source,
            }
            plan = self._assign(runner, work, base, manifest, entry, choice, index, previous=old)
            self._point("resolved")
            # ⑤ wheel 만들기 (git·path: staging 임시 빌드 환경) / 받은 wheel 그대로
            dist_dir = staging / "dist"
            dist_dir.mkdir()
            if fetched.wheel is not None:
                built = dist_dir / fetched.wheel.name
                shutil.copyfile(fetched.wheel, built)
            else:
                built = self._build(runner, staging, _project(fetched), plan.packages, index)
                self._point("built")
            # ⑥ wheel 확정: 바이트 해시, 안의 스키마 파일(정적 검사·schema_digest), ②와 같은지
            if fetched.wheel is None:
                # 빌드 wheel: 직접 참조 등 ②와 다른 의존성은 원천과의 대조에서 build_failed
                final = read_wheel(built, allow_direct=True)
                _check_built(manifest, final)
            else:
                final = read_wheel(built)
            wheel_sha = _sha256(built)
            entry.update(
                dist=final.dist,
                version=final.version,
                manifest=final.lock_manifest(),
                requires=list(final.requires),
                schema_sha256=final.schema_sha256,
                wheel_sha256=wheel_sha,
                wheel=f"plugins/wheels/{wheel_sha}/{final.wheel_name}",
            )
            plan.wheels[final.id] = built
            new_lock = dict(base)
            new_lock["plugins"] = [*others, entry]
            new_lock["environments"] = dict(lock["environments"])
            new_lock.update(
                python=app.python,
                python_full=app.python_full,
                platform=app.platform,
                sdk=app.sdk(),
                index=mask(index.url),
            )
            # ⑦ 실행 환경 (upgrade로 옛 환경에서 빠지면 그 환경도 남은 플러그인으로 다시 고른다)
            if old is not None and old["env"] != plan.name:
                self._regroup(runner, op_id, staging, lock, new_lock, str(old["env"]), index)
            reused = self._prepare_env(runner, op_id, staging, plan, new_lock, index)
            # ⑧ wheel 보관
            self._archive(built, entry["wheel"], wheel_sha)
            self._point("archived")
            # ⑨ 커밋
            new_revision = self._commit(new_lock, revision)
            self._point("committed")
            self._remember(lock, new_lock, untrusted, confirmed=(final.id,))
            return {
                "op_id": op_id,
                "plugin": entry,
                "env": plan.name,
                "reused": reused,
                "revision": new_revision,
                **({"replaced": old["version"]} if old is not None else {}),
            }

    def _regroup(
        self,
        runner: ProcessRunner,
        op_id: str,
        staging: Path,
        lock: Mapping[str, Any],
        new_lock: dict[str, Any],
        env_name: str,
        index: IndexConfig,
    ) -> None:
        """플러그인이 빠진 환경: 남은 것이 없으면 빼고, 있으면 남은 플러그인 + 기존 판으로 ⑦."""
        members = [p for p in new_lock["plugins"] if p["env"] == env_name]
        if not members:
            new_lock["environments"].pop(env_name, None)
            return
        old_env = lock["environments"][env_name]
        plan = _EnvPlan(
            env_name,
            members,
            [Package.from_json(p) for p in old_env["packages"]],
            {str(m["id"]): self._archived_wheel(m) for m in members},
        )
        self._prepare_env(runner, op_id, staging, plan, new_lock, index)

    def _build(
        self,
        runner: ProcessRunner,
        staging: Path,
        project: Path,
        packages: Sequence[Package],
        index: IndexConfig,
    ) -> Path:
        """⑤ 거래 전용 임시 빌드 환경(staging/build-env)에 해석된 의존성 + 앱 SDK를 깔고
        `kookabug-sdk build`(스키마 생성) → `uv build --wheel`. 결과는 staging/dist 의 wheel 하나.
        실행 환경과는 다른 폴더다 (빌드 도구·산출물이 실행 환경에 들어가지 않는다)."""
        uv = find_uv(self.environ)
        app = self.app
        env = staging / "build-env"
        dist = staging / "dist"

        def uv_(*args: str | Path) -> None:
            self._uv(runner, [uv, *args], cwd=staging, code="build_failed", stage="build")

        uv_("venv", env, "--python", app.python_exe, "--no-project", "--quiet")
        python = envs_mod.env_python(env)
        if packages:
            req = staging / "build-requirements.txt"
            req.write_text("".join(p.requirement() + "\n" for p in packages), encoding="utf-8")
            uv_("pip", "sync", req, "--python", python, "--require-hashes", "--only-binary",
                ":all:", "--quiet", *index.args())  # fmt: skip
        uv_("pip", "install", "--python", python, "--no-deps", "--no-index", "--quiet",
            app.sdk_wheel)  # fmt: skip
        done = runner.run(
            [python, "-I", "-m", "kookabug_sdk.cli", "build", project], stage="build", cwd=staging
        )
        if done.returncode != 0:
            raise PluginError(
                "build_failed",
                f"kookabug-sdk build가 실패했다: {mask(_last_line(done.stderr or done.stdout))}",
                stage="build",
            )
        uv_("build", "--wheel", "--no-sources", "--python", app.python_exe, "--out-dir", dist,
            "--quiet", *index.args(), project)  # fmt: skip
        wheels = sorted(dist.glob("*.whl"))
        if len(wheels) != 1:
            raise PluginError(
                "build_failed",
                f"빌드 결과 wheel이 {len(wheels)}개다 (하나여야 한다)",
                stage="build",
            )
        return wheels[0]

    def _check_sdk(
        self, runner: ProcessRunner, work: Path, plugin_id: str, sdk_requires: Sequence[str]
    ) -> None:
        """플러그인의 SDK 범위가 앱 SDK를 받는가 (네트워크 없이 앱 SDK wheel만으로 해석)."""
        app = self.app
        try:
            resolve_with_app_sdk(
                runner,
                find_uv(self.environ),
                work,
                list(sdk_requires),
                python=app.python,
                index=IndexConfig(),
                sdk_wheel=self._app_sdk_wheel(work),
                no_index=True,
            )
        except ResolveFailure as exc:
            raise PluginError(
                "sdk_incompatible",
                f"{plugin_id}의 SDK 범위({', '.join(sdk_requires)})가 앱 SDK "
                f"{app.sdk_version}을(를) 받지 않는다",
                stage="resolve",
                plugin=plugin_id,
            ) from exc

    def _assign(
        self,
        runner: ProcessRunner,
        work: Path,
        lock: dict[str, Any],
        manifest: Manifest | ProjectManifest,
        entry: dict[str, Any],
        choice: str,
        index: IndexConfig,
        *,
        previous: Mapping[str, Any] | None = None,
    ) -> _EnvPlan:
        """④ 해석해 환경을 정한다 (D7). 공유면 기존 공유 고정 판 전부가 제약이다. 공유·격리 모두
        SDK는 앱 SDK wheel 파일 직접 참조(`resolve_with_app_sdk`)라, 전이 의존성의 SDK 요구도
        앱 SDK artifact로만 풀린다 (안 되면 `sdk_incompatible`). `lock`에는 바꾸는 플러그인
        (`previous`, upgrade)이 이미 빠져 있다 — 그것이 공유였으면 제약은 남은 공유 플러그인이 쓰는
        기존 판만이다 (옛 판의 자기 의존성에 묶이지 않게)."""
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
        kept = sorted({r for p in members for r in p["requires"] if not _is_sdk(r)})
        if previous is not None and previous["env"] == SHARED_ENV:
            # 남은 공유 플러그인만의 기존 판 (기존 판을 제약으로 풀면 그 부분 집합이 나온다)
            try:
                old_packages = (
                    compile_(kept, [f"{p.name}=={p.version}" for p in old_packages])
                    if members
                    else []
                )
            except ResolveFailure as exc:
                raise _resolve_error(exc) from exc
        requirements = sorted(set(kept) | set(deps))
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
        *,
        expect_digest: str | None = None,
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
        if expect_digest is not None and digest != expect_digest:
            # sync: 같은 입력인데 파일이 다르면 재현이 아니다 (표식 없음 = "없는 것"으로 남는다)
            raise PluginError(
                "verify_failed",
                f"{plan.name}: 만든 환경의 digest가 잠금과 다르다",
                stage="verify",
                env=plan.name,
            )
        envs_mod.write_marker(folder, env=plan.name, fp=fp, digest=digest)
        self._point("env_complete")
        return digest

    def _uv(
        self,
        runner: ProcessRunner,
        args: Sequence[str | Path],
        *,
        cwd: Path,
        code: str = "env_create_failed",
        stage: str = "env",
    ) -> None:
        done = runner.run(args, stage=stage, cwd=cwd)
        if done.returncode != 0:
            raise PluginError(
                code,
                f"uv {args[1]}이(가) 실패했다: {mask(_last_line(done.stderr or done.stdout))}",
                stage=stage,
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
                f"플러그인 모듈을 import할 수 없다: {mask(_last_line(done.stderr))}",
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
            others = [p for p in lock["plugins"] if p["id"] != plugin_id]
            untrusted = self._untrusted(lock, others)
            asked = {
                "op_id": op_id,
                "id": plugin_id,
                "version": entry["version"],
                "untrusted": untrusted,
            }
            if not confirm(asked):
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
            self._remember(lock, new_lock, untrusted)
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

    # ------------------------------------------------------------ sync·relock

    def sync(
        self,
        *,
        confirm: Callable[[dict[str, Any]], bool],
        lock_sha256: str | None = None,
    ) -> dict[str, Any]:
        """잠금 → 환경 (`sync.py`). 잠금 파일을 쓰지 않는다."""
        from kookabug_core.plugins.sync import sync

        return sync(self, confirm=confirm, expected_sha256=lock_sha256)

    def relock(self, *, confirm: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        """앱 Python·SDK로 다시 잠근다 (`relock.py`)."""
        from kookabug_core.plugins.relock import relock

        return relock(self, confirm=confirm)


def _project(fetched: sources.Fetched) -> Path:
    assert fetched.project is not None
    return fetched.project


def _check_built(static: Manifest | ProjectManifest, built: Manifest) -> None:
    """⑥ 빌드한 wheel이 신뢰 확인에 보인 것(② pyproject)과 같은가: ID·배포판·판·머리·의존성."""
    problems: list[str] = []
    if built.id != static.id:
        problems.append(f"ID {built.id} ≠ {static.id}")
    if normalize_name(built.dist) != normalize_name(static.dist):
        problems.append(f"배포판 {built.dist} ≠ {static.dist}")
    if Version(built.version) != Version(static.version):
        problems.append(f"판 {built.version} ≠ {static.version}")
    if built.lock_manifest() != static.lock_manifest():
        problems.append("스키마 머리(modules·permissions 등)가 pyproject와 다르다")
    if not same_requirements(built.requires, static.requires):
        problems.append("wheel의 의존성이 pyproject의 dependencies와 다르다")
    if problems:
        raise PluginError(
            "build_failed", f"빌드한 wheel이 원천과 다르다: {'; '.join(problems)}", stage="build"
        )


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
