"""설치 트리 DLL 의존성 검사 (구현 계획 M1 2.12).

    $env:PYTHONPATH = "tools"; uv run python -m installer.dllcheck <설치 폴더> [--json]

설치 폴더의 모든 `.pyd`·`.dll`·`.exe`의 import(일반·지연)를 PE 헤더에서 읽어, 실행 때 Windows가
찾을 곳(`LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | APPLICATION_DIR | SYSTEM32`)으로만 푼다.

- 그 파일 폴더 → 앱 폴더(`python/`, python.exe 폴더) → **등록 근거가 확인된 DLL 폴더** → System32
  순서
- 등록 DLL 폴더(`DLL_DIRECTORIES`)는 패키지가 실행 중에 `os.add_dll_directory`로 더하는 폴더다
  (numpy의 delvewheel 패치가 `numpy.libs`를 더한다). 그 패키지 안 파일의 import에만 쓰고, 등록하는
  파일에 근거 글귀가 그대로 있을 때만 인정한다. 글귀가 없으면(패키지가 바뀜) 실패
- 설치 폴더 어딘가에 같은 이름이 있어도 위 탐색 경로 밖이면 실패 ("탐색 경로 밖") — 실제 import가
  `DLL load failed`로 끝난다
- **VC++ 런타임**(`msvcp140*`·`vcruntime140*`·`concrt140`)은 위 설치 폴더 경로에서 풀려야 한다.
  System32에 있어도 실패 — 깨끗한 Windows에는 없거나 다른 판이다 (2.12 앱 로컬 복사)
- API 집합(`api-ms-*`·`ext-ms-*`)은 시스템이 푼다
- 위에서 못 찾고 PATH 등 설치 밖 비시스템 폴더(`outside`)에 있으면 실패 ("설치 밖에서 풀림"),
  어디에도 없으면 일반 import는 실패, 지연 import는 참고 (선택 기능의 DLL일 수 있다)

종료 코드 0 = 통과, 1 = 실패, 2 = 입력 오류.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from kookabug_sdk.console import utf8_stdio

NATIVE_SUFFIXES: Final = (".dll", ".pyd", ".exe")
APP_DIR: Final = "python"
VC_RUNTIME_PREFIXES: Final = ("msvcp140", "vcruntime140", "concrt140")
API_SET_PREFIXES: Final = ("api-ms-", "ext-ms-")
_IMPORT_DIR: Final = 1
_DELAY_IMPORT_DIR: Final = 13


class PeError(Exception):
    pass


@dataclass(frozen=True)
class PeImports:
    imports: tuple[str, ...]
    delay: tuple[str, ...]


def _cstr(data: bytes, offset: int) -> str:
    end = data.find(b"\0", offset)
    if offset < 0 or end < 0:
        raise PeError(f"이름 문자열이 범위 밖 ({offset:#x})")
    return data[offset:end].decode("ascii", errors="replace")


def read_imports(path: Path) -> PeImports:
    """PE(32·32+)의 import·지연 import DLL 이름."""
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise PeError("MZ 헤더가 없다")
    (pe,) = struct.unpack_from("<I", data, 0x3C)
    if data[pe : pe + 4] != b"PE\0\0":
        raise PeError("PE 서명이 없다")
    coff = pe + 4
    (sections,) = struct.unpack_from("<H", data, coff + 2)
    (opt_size,) = struct.unpack_from("<H", data, coff + 16)
    opt = coff + 20
    (magic,) = struct.unpack_from("<H", data, opt)
    if magic == 0x20B:  # PE32+
        image_base = struct.unpack_from("<Q", data, opt + 24)[0]
        count_at, dirs_at = opt + 108, opt + 112
    elif magic == 0x10B:  # PE32
        image_base = struct.unpack_from("<I", data, opt + 28)[0]
        count_at, dirs_at = opt + 92, opt + 96
    else:
        raise PeError(f"알 수 없는 옵션 헤더 ({magic:#x})")
    (dir_count,) = struct.unpack_from("<I", data, count_at)

    table = opt + opt_size
    spans: list[tuple[int, int, int]] = []
    for i in range(sections):
        vsize, vaddr, raw_size, raw_ptr = struct.unpack_from("<IIII", data, table + i * 40 + 8)
        spans.append((vaddr, max(vsize, raw_size), raw_ptr))

    def offset(rva: int) -> int:
        for vaddr, size, raw in spans:
            if vaddr <= rva < vaddr + size:
                return raw + rva - vaddr
        raise PeError(f"RVA {rva:#x}가 어느 섹션에도 없다")

    def directory(index: int) -> int:
        if index >= dir_count:
            return 0
        rva, _ = struct.unpack_from("<II", data, dirs_at + index * 8)
        return rva

    imports: list[str] = []
    if rva := directory(_IMPORT_DIR):
        at = offset(rva)
        while True:
            entry = struct.unpack_from("<IIIII", data, at)
            if not any(entry):
                break
            imports.append(_cstr(data, offset(entry[3])))
            at += 20
    delay: list[str] = []
    if rva := directory(_DELAY_IMPORT_DIR):
        at = offset(rva)
        while True:
            attrs, name = struct.unpack_from("<II", data, at)
            if not attrs and not name:
                break
            # 옛 형식(속성 0)은 RVA 대신 VA
            delay.append(_cstr(data, offset(name if attrs & 1 else name - image_base)))
            at += 32
    return PeImports(tuple(imports), tuple(delay))


@dataclass(frozen=True)
class DllDirectory:
    """실행 중 `os.add_dll_directory`로 더해지는 설치 폴더 안 DLL 폴더 (설치 폴더 기준 경로).

    `importers` 아래 파일의 import에만 쓴다 — 그 패키지를 import해야 등록되므로. `registered_by`
    파일에 `evidence` 글귀가 전부 있어야 등록을 인정한다."""

    folder: str
    importers: str
    registered_by: str
    evidence: tuple[str, ...]


SITE: Final = f"{APP_DIR}/Lib/site-packages"
DLL_DIRECTORIES: Final = (
    DllDirectory(
        folder=f"{SITE}/numpy.libs",
        importers=f"{SITE}/numpy/",
        registered_by=f"{SITE}/numpy/__init__.py",
        evidence=("def _delvewheel_patch", "'numpy.libs'", "os.add_dll_directory(libs_dir)"),
    ),
)


@dataclass
class DllReport:
    files: int = 0
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def is_vc_runtime(name: str) -> bool:
    return name.casefold().startswith(VC_RUNTIME_PREFIXES)


def default_system_dir() -> Path:
    return Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32"


def default_outside() -> list[Path]:
    """설치 밖 비시스템 폴더 후보: PATH의 폴더 중 Windows 폴더 밖."""
    windows = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")).resolve()
    out: list[Path] = []
    for item in os.environ.get("PATH", "").split(os.pathsep):
        if not item:
            continue
        path = Path(item)
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if not resolved.is_relative_to(windows):
            out.append(path)
    return out


def _index(root: Path) -> tuple[list[Path], dict[str, list[Path]]]:
    natives: list[Path] = []
    by_name: dict[str, list[Path]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.casefold() in NATIVE_SUFFIXES:
            natives.append(path)
            by_name.setdefault(path.name.casefold(), []).append(path)
    return natives, by_name


def registered_dirs(
    root: Path, directories: Sequence[DllDirectory], report: DllReport
) -> list[DllDirectory]:
    """설치 트리에 있는 등록 DLL 폴더 중 등록 근거가 확인된 것. 폴더는 있는데 근거가 없으면 실패."""
    active: list[DllDirectory] = []
    for d in directories:
        if not (root / d.folder).is_dir():
            continue
        try:
            source = (root / d.registered_by).read_text(encoding="utf-8")
        except OSError:
            source = ""
        missing = [e for e in d.evidence if e not in source]
        if missing:
            report.problems.append(
                f"[DLL 폴더 등록 근거 없음] {d.folder}: {d.registered_by}에 {missing}가 없다"
            )
            continue
        active.append(d)
    return active


def check_tree(
    root: Path,
    *,
    system_dir: Path | None = None,
    outside: Iterable[Path] | None = None,
    directories: Sequence[DllDirectory] = DLL_DIRECTORIES,
) -> DllReport:
    system = default_system_dir() if system_dir is None else system_dir
    outside_dirs = default_outside() if outside is None else list(outside)
    app = root / APP_DIR
    natives, by_name = _index(root)
    report = DllReport(files=len(natives))
    active = registered_dirs(root, directories, report)
    via_registered: dict[str, set[str]] = {}

    def resolve(owner: Path, name: str, delayed: bool) -> None:
        key = name.casefold()
        rel = owner.relative_to(root).as_posix()
        if key.startswith(API_SET_PREFIXES):
            return
        if (owner.parent / name).is_file() or (app / name).is_file():
            return
        for d in active:
            if rel.startswith(d.importers) and (root / d.folder / name).is_file():
                via_registered.setdefault(f"{name} ← {d.folder}", set()).add(rel)
                return
        inside = [p.parent.relative_to(root).as_posix() for p in by_name.get(key, [])]
        if is_vc_runtime(name):
            where = f"설치 폴더의 {inside}에만 있다" if inside else "설치 폴더에 없다"
            report.problems.append(
                f"[VC++ 런타임 탐색 경로 밖] {rel}: {name}이 {where} (System32·PATH에서 읽힘)"
            )
            return
        if (system / name).is_file():
            return
        for folder in outside_dirs:
            if (folder / name).is_file():
                report.problems.append(
                    f"[설치 밖에서 풀림] {rel}: {name} → {folder / name} (비시스템 DLL)"
                )
                return
        if inside:
            report.problems.append(
                f"[탐색 경로 밖] {rel}: {name}이 설치 폴더의 {inside}에 있지만 "
                "그 파일 폴더·앱 폴더·등록 DLL 폴더가 아니다"
            )
            return
        if delayed:
            report.notes.append(f"[지연 import 없음] {rel}: {name}")
        else:
            report.problems.append(f"[풀리지 않음] {rel}: {name}")

    for path in natives:
        try:
            imports = read_imports(path)
        except (PeError, struct.error, OSError) as exc:
            report.problems.append(f"[PE 읽기 실패] {path.relative_to(root).as_posix()}: {exc}")
            continue
        normal = {n.casefold() for n in imports.imports}
        for name in dict.fromkeys(imports.imports):
            resolve(path, name, delayed=False)
        for name in dict.fromkeys(imports.delay):
            if name.casefold() not in normal:
                resolve(path, name, delayed=True)
    for where, owners in sorted(via_registered.items()):
        report.notes.append(f"[등록 DLL 폴더] {where} ({len(owners)}개 파일)")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    utf8_stdio()
    parser = argparse.ArgumentParser(description="Kookabug 설치 트리 DLL 의존성 검사")
    parser.add_argument("root", type=Path, help="설치 폴더")
    parser.add_argument("--json", action="store_true", help="결과 JSON 한 개만 출력한다")
    args = parser.parse_args(argv)
    if not (args.root / APP_DIR / "python.exe").is_file():
        print(f"설치 폴더가 아니다: {args.root}", file=sys.stderr)
        return 2
    report = check_tree(args.root)
    if args.json:
        body = {"files": report.files, "problems": report.problems, "notes": report.notes}
        print(json.dumps(body, ensure_ascii=False))
    else:
        print(f"네이티브 파일 {report.files}개")
        for note in report.notes:
            print(f"참고: {note}")
        for problem in report.problems:
            print(f"  {problem}", file=sys.stderr)
        print("DLL 검사 " + ("통과" if not report.problems else f"실패 ({len(report.problems)}건)"))
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
