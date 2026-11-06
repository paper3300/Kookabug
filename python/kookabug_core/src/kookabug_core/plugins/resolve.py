"""의존성 해석 (M6 계획 D2·D5·D7): `uv pip compile --generate-hashes --only-binary :all:`.

- 대상 Python 소판·플랫폼을 고정해 해석한다 (앱과 같은 조건)
- 의존성은 wheel만: sdist만 있는 배포판(전이 포함)이 걸리면 `ResolveFailure(kind="sdist_only")`
- 공유 환경에 더할 때는 기존 공유 고정 판 전부를 제약(`-c`)으로 넣는다 → 기존 판을 바꿔야 하면
  해석 실패(충돌). 충돌인지 해석 불가인지는 호출자가 제약 없이 다시 해석해 가린다
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from kookabug_core.plugins.manifest import SDK_DIST, normalize_name
from kookabug_core.plugins.uv import ProcessRunner

__all__ = [
    "PLATFORM",
    "IndexConfig",
    "Package",
    "ResolveFailure",
    "compile_requirements",
    "resolve_with_app_sdk",
]

PLATFORM: Final = "x86_64-pc-windows-msvc"
DEFAULT_INDEX: Final = "https://pypi.org/simple"
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)")
_HASH = re.compile(r"--hash=(sha256:[0-9a-f]{64})")
_DIRECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\s*@\s*\S+")
_SDIST_ONLY = re.compile(
    r"Wheels are required for `([^`]+)`|`?([A-Za-z0-9._-]+)==\S+`? has no usable wheels"
)


@dataclass(frozen=True, slots=True)
class IndexConfig:
    """`plugin_index` (`kookabug.json` → `.kookabug/local.json` 덮어쓰기)."""

    url: str = DEFAULT_INDEX
    find_links: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, team: Any, local: Any) -> IndexConfig:
        chosen = local if isinstance(local, dict) else team
        if not isinstance(chosen, dict):
            return cls()
        url = chosen.get("url")
        links = chosen.get("find_links")
        return cls(
            url=url if isinstance(url, str) and url else DEFAULT_INDEX,
            find_links=tuple(str(x) for x in links) if isinstance(links, list) else (),
        )

    def args(self) -> list[str]:
        out = ["--index-url", self.url]
        for link in self.find_links:
            out += ["--find-links", link]
        return out


@dataclass(frozen=True, slots=True)
class Package:
    name: str
    version: str
    hashes: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "hashes": list(self.hashes)}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Package:
        return cls(str(data["name"]), str(data["version"]), tuple(data["hashes"]))

    def requirement(self) -> str:
        """`uv pip sync --require-hashes` 한 줄."""
        hashes = " ".join(f"--hash={h}" for h in self.hashes)
        return f"{self.name}=={self.version} {hashes}"


class ResolveFailure(Exception):
    def __init__(
        self, kind: Literal["sdist_only", "unsatisfiable"], message: str, names: Sequence[str] = ()
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.names = tuple(names)


def parse_compiled(text: str) -> list[Package]:
    """`uv pip compile --generate-hashes --no-header --no-annotate` 출력 → 패키지 목록 (이름 순)."""
    out: list[Package] = []
    current: tuple[str, str] | None = None
    hashes: list[str] = []

    def flush() -> None:
        if current is not None:
            out.append(Package(normalize_name(current[0]), current[1], tuple(sorted(hashes))))

    for raw in text.splitlines():
        line = raw.strip().rstrip("\\").strip()
        if not line or line.startswith("#"):
            continue
        pin = _PIN.match(line)
        if pin:
            flush()
            current, hashes = (pin.group(1), pin.group(2)), []
        elif _DIRECT.match(line):
            # 직접 참조(`이름 @ URL`): 앱 SDK wheel 같은 고정 파일. 목록에 넣지 않는다 (경로 포함)
            flush()
            current, hashes = None, []
            continue
        hashes += _HASH.findall(line)
    flush()
    return sorted(out, key=lambda p: p.name)


def compile_requirements(
    runner: ProcessRunner,
    uv: Path,
    work: Path,
    requirements: Sequence[str],
    *,
    python: str,
    index: IndexConfig,
    constraints: Sequence[str] = (),
    find_links: Sequence[Path] = (),
    no_index: bool = False,
    stage: str = "resolve",
) -> list[Package]:
    """해석한다. 요구가 없으면 빈 목록 (uv를 부르지 않음)."""
    if not requirements:
        return []
    work.mkdir(parents=True, exist_ok=True)
    count = len(list(work.glob("req-*.in")))
    req = work / f"req-{count}.in"
    req.write_text("".join(f"{r}\n" for r in requirements), encoding="utf-8")
    args: list[str | Path] = [
        uv,
        "pip",
        "compile",
        req,
        "--generate-hashes",
        "--only-binary",
        ":all:",
        "--python-version",
        python,
        "--python-platform",
        PLATFORM,
        "--no-header",
        "--no-annotate",
        "--quiet",
    ]
    if constraints:
        con = work / f"req-{count}.constraints.txt"
        con.write_text("".join(f"{c}\n" for c in constraints), encoding="utf-8")
        args += ["-c", con]
    if no_index:
        args.append("--no-index")
    else:
        args += index.args()
    for link in find_links:
        args += ["--find-links", link]
    done = runner.run(args, stage=stage)
    if done.returncode != 0:
        text = (done.stderr or done.stdout).strip()
        names = [a or b for a, b in _SDIST_ONLY.findall(text)]
        if names:
            raise ResolveFailure("sdist_only", text, sorted({normalize_name(n) for n in names}))
        raise ResolveFailure("unsatisfiable", text)
    return parse_compiled(done.stdout)


def resolve_with_app_sdk(
    runner: ProcessRunner,
    uv: Path,
    work: Path,
    requirements: Sequence[str],
    *,
    python: str,
    index: IndexConfig,
    sdk_wheel: Path,
    constraints: Sequence[str] = (),
    no_index: bool = False,
) -> list[Package]:
    """환경 해석 (설치·sync·relock 공용). SDK 후보는 **앱 SDK wheel 파일 하나**다: 요구에
    `kookabug-sdk @ file:///…` 직접 참조를 더해, 인덱스·find-links의 다른 SDK artifact(같은 판·
    build tag 포함)의 메타데이터·의존성이 해석에 들어오지 않는다. 일반 의존성은 설정 인덱스에서
    푼다. 결과에서 SDK(직접 참조 줄)는 빠진다 — 잠금은 SDK를 `sdk` 하나로만 나타낸다 (로컬 절대
    경로가 잠금에 남지 않음). SDK와 맞지 않는 요구는 해석 실패(`ResolveFailure`, 메시지에 SDK
    이름)다."""
    pinned = f"{SDK_DIST} @ {sdk_wheel.resolve().as_uri()}"
    packages = compile_requirements(
        runner,
        uv,
        work,
        [*requirements, pinned],
        python=python,
        index=index,
        constraints=constraints,
        no_index=no_index,
    )
    if strays := [p for p in packages if p.name == SDK_DIST]:
        # 직접 참조를 줬는데 레지스트리 SDK가 나오면 고정이 깨진 것 (uv 동작이 바뀐 경우)
        raise ResolveFailure(
            "unsatisfiable", f"{SDK_DIST}가 앱 wheel이 아닌 {strays[0].version}로 풀렸다"
        )
    return packages
