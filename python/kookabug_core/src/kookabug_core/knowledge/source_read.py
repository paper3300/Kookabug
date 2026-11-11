"""등록된 원본 읽기 (UX2 A) — Agent 도구 `kb_source_list`·`kb_source_read`의 본체.
엄격: 경계·비밀값.

- 읽는 곳은 `kookabug.json#sources`(+ `local.json#sources.<id>.path`)에 등록된 원본의 루트
  아래뿐이다. 루트는 `check_sources`처럼 실경로로 정규화한다(루트 자체가 정션이면 그 대상이
  루트). 루트 아래 상대 경로는 `filetx.plain` 규칙(`.`·`..`·드라이브 없음, 조각마다 링크·정션
  아님, 실경로가 루트 안)이다
- 워크스페이스 파생 경로(`DERIVED_DIRS`)는 원본으로 읽지 않는다 — 정규화 전 경로·실경로 둘 다
  본다(`verify_basis`와 같은 규칙). 목록에서도 링크·정션·파생 폴더는 뺀다
- URL 원본은 받지 않는다(`unchecked_url`). 쓰기는 없다
- 글은 텍스트(utf-8·utf-8-sig·utf-16 BOM, 실패하면 cp949)와 `.docx`·`.xlsx`·`.pptx`(표준
  `zipfile`+XML, 압축 해제 상한)만. 그 밖은 `unsupported_format`
- 돌려주는 글에는 `agent.log`와 같은 가림(알려진 값 → `***`)을 **전체 글에** 먼저 한 뒤
  자른다(경계를 넘는 값이 두 번에 나뉘어 새지 않게). 가림 값을 못 모으면 글을 주지 않는다
  (`secret_unchecked`)
- 한 번에 주는 글은 `TEXT_LIMIT`(JSON으로 실은 바이트)까지, 나머지는 `offset`(글자 단위)으로
  이어 읽는다. `ref`·`hash`는 `source` 근거(`sources:<id>#<경로>`)에 그대로 쓸 수 있다
  (`verify_basis`와 같은 hash)
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Final
from xml.etree import ElementTree
from xml.parsers import expat

from kookabug_core import filetx
from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_core.knowledge.sources import (
    _derived,  # pyright: ignore[reportPrivateUsage]
    _derived_route,  # pyright: ignore[reportPrivateUsage]
    _file_hash,  # pyright: ignore[reportPrivateUsage]
    source_path,
    sources_of,
)
from kookabug_core.workspace import Workspace

__all__ = [
    "LIST_LIMIT",
    "TEXT_LIMIT",
    "UNZIP_LIMIT",
    "extract_text",
    "list_source",
    "list_sources",
    "read_source",
]

TEXT_LIMIT: Final = 200 * 1024
"""한 번에 돌려주는 글 (JSON으로 실은 UTF-8 바이트 — MCP 결과 상한 256 KiB 안에 머리 필드와
함께 든다)."""
LIST_LIMIT: Final = 500
"""폴더 목록 항목 상한."""
FILE_LIMIT: Final = 32 * 1024 * 1024
"""읽는 원본 파일 하나의 크기 상한 (넘으면 `unsupported_format` too_large)."""
UNZIP_LIMIT: Final = 64 * 1024 * 1024
"""Office 파일 하나에서 풀어 읽는 XML 전체 바이트 상한 (zip 폭탄)."""
OUTPUT_LIMIT: Final = 16 * 1024 * 1024
"""Office 파일 하나에서 뽑는 글 전체 글자 수 상한 (공유 문자열 반복 참조 증폭 — 검수 1 M2)."""
PART_LIMIT: Final = 2000
"""Office 파일에서 읽는 부분(시트·슬라이드) 수 상한."""
_MASK: Final = "***"
_BINARY_PROBE: Final = 8192

type SecretValues = Callable[[], Iterable[str]]


def _fail(code: str, message: str, **fields: Any) -> KnowledgeError:
    return KnowledgeError(code, message, **fields)


# ---------------------------------------------------------------- 원본·경계


def _find(workspace: Workspace, source_id: str) -> dict[str, Any]:
    found = [s for s in sources_of(workspace) if s.get("id") == source_id]
    if not found:
        raise _fail("unknown_id", "kookabug.json sources에 없는 원본이다", id=source_id)
    if len(found) > 1:
        raise _fail("source_unavailable", "같은 ID의 원본이 여럿이다", reason="duplicate_id")
    return found[0]


def _is_url(source: Mapping[str, Any]) -> bool:
    return isinstance(source.get("url"), str) and not source.get("path") and not source.get("local")


def _state(workspace: Workspace, source: Mapping[str, Any]) -> tuple[str, Path | None]:
    """(상태, 실경로 루트). 상태: ok·missing·unreadable·unchecked_url·derived (hash는 계산하지
    않는다)."""
    if _is_url(source):
        return "unchecked_url", None
    path = source_path(workspace, source)
    if path is None:
        return "missing", None
    lexical = Path(os.path.abspath(path))
    try:
        real = Path(os.path.realpath(lexical))
        if not real.exists():
            return "missing", None
        if _derived_route(workspace, lexical) or _derived(workspace, real):
            return "derived", None
        os.stat(real)
    except OSError:
        return "unreadable", None
    return "ok", real


def _root_of(workspace: Workspace, source_id: str) -> tuple[dict[str, Any], Path]:
    source = _find(workspace, source_id)
    state, real = _state(workspace, source)
    if state == "derived":
        raise _fail(
            "policy_path",
            "워크스페이스의 파생 경로(knowledge·wiki·runs·tests 등)는 원본으로 읽지 않는다",
        )
    if real is None:
        raise _fail("source_unavailable", f"원본을 읽을 수 없다 ({state})", reason=state)
    return source, real


_BAD_PART: Final = re.compile(r'[\x00-\x1f<>"|?*]')


def _target(workspace: Workspace, real_root: Path, rel: str) -> Path:
    """원본 루트 아래 `rel`의 경로 (경계를 지난 것). `rel`이 비면 루트."""
    rel = rel.replace("\\", "/").strip()
    if rel in ("", "."):
        return real_root
    parts = rel.split("/")
    if rel.startswith("/") or any(p in ("", ".", "..") or ":" in p for p in parts):
        raise _fail("policy_path", "원본 안 경로는 원본 루트 기준 상대 경로다 (.·..·드라이브 없음)")
    if any(_BAD_PART.search(p) for p in parts):
        raise _fail("policy_path", "원본 안 경로에 쓸 수 없는 글자가 있다")
    try:
        target = filetx.plain(real_root, rel)
    except filetx.TxError as exc:
        raise _fail(
            "policy_path", "원본 안 경로에 링크·정션이 있거나 실경로가 원본 밖이다"
        ) from exc
    real = Path(os.path.realpath(target))
    if (
        _derived_route(workspace, target)
        or _derived(workspace, real)
        or not real.is_relative_to(real_root)
    ):
        raise _fail(
            "policy_path",
            "워크스페이스의 파생 경로(knowledge·wiki·runs·tests 등)는 원본으로 읽지 않는다",
        )
    return target


def _ref(source_id: str, rel: str) -> str:
    rel = rel.replace("\\", "/").strip().strip("/")
    return f"sources:{source_id}" if rel in ("", ".") else f"sources:{source_id}#{rel}"


# ---------------------------------------------------------------- 목록


def list_sources(workspace: Workspace) -> list[dict[str, Any]]:
    """등록된 원본 전부 (id·종류·이름·상태·파일/폴더)."""
    out: list[dict[str, Any]] = []
    for source in sources_of(workspace):
        state, real = _state(workspace, source)
        entry: dict[str, Any] = {
            "id": str(source.get("id")),
            "kind": source.get("kind"),
            "title": source.get("title"),
            "state": "unreadable" if state == "derived" else state,
            "type": None if real is None else ("dir" if real.is_dir() else "file"),
        }
        out.append(entry)
    return out


def list_source(workspace: Workspace, source_id: str, rel: str = "") -> dict[str, Any]:
    """원본 하나: 폴더면 `rel` 아래 한 단계 항목(이름·종류·크기, 상한 `LIST_LIMIT`), 파일이면 그
    파일."""
    source, real_root = _root_of(workspace, source_id)
    target = _target(workspace, real_root, rel)
    head: dict[str, Any] = {
        "source": source_id,
        "kind": source.get("kind"),
        "title": source.get("title"),
        "path": rel.replace("\\", "/").strip().strip("/"),
    }
    try:
        if not target.is_dir():
            if not target.exists():
                raise _fail("unknown_id", "원본 안에 그 경로가 없다", id=source_id)
            size = target.stat().st_size
            return {**head, "type": "file", "bytes": size, "entries": [], "truncated": False}
        entries: list[dict[str, Any]] = []
        truncated = False
        names = sorted(os.listdir(target), key=lambda n: n.casefold())
        dirs: list[dict[str, Any]] = []
        files: list[dict[str, Any]] = []
        for name in names:
            entry = target / name
            if entry.is_symlink() or entry.is_junction():
                continue
            if _derived(workspace, Path(os.path.realpath(entry))):
                continue
            if entry.is_dir():
                dirs.append({"name": name, "type": "dir"})
            else:
                try:
                    files.append({"name": name, "type": "file", "bytes": entry.stat().st_size})
                except OSError:
                    continue
        entries = dirs + files
        if len(entries) > LIST_LIMIT:
            entries = entries[:LIST_LIMIT]
            truncated = True
    except OSError as exc:
        raise _fail("source_unavailable", "원본 폴더를 읽을 수 없다", reason="unreadable") from exc
    return {**head, "type": "dir", "entries": entries, "truncated": truncated}


# ---------------------------------------------------------------- 글 뽑기


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    elif b"\0" in data[:_BINARY_PROBE]:
        raise _fail("unsupported_format", "텍스트·docx·xlsx·pptx가 아니다", reason="binary")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise _fail(
        "unsupported_format", "글자 인코딩을 알 수 없다 (utf-8·cp949 아님)", reason="encoding"
    )


class _Unzip:
    """Office zip 한 개: 실제로 풀린 바이트를 세어 상한을 넘으면 멈춘다(헤더 크기를 믿지 않는다)."""

    def __init__(self, data: bytes) -> None:
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise _fail("unsupported_format", "Office 파일이 깨졌다", reason="corrupt") from exc
        self.names = {i.filename: i for i in self.zip.infolist()}
        self.used = 0
        self.out = 0
        """뽑은 글 누적 글자 수 (공유 문자열 반복 참조·빈 열 채움도 센다 — 검수 1 M2)."""

    def spend(self, size: int) -> None:
        """뽑은 글을 `size`자 더한다. 상한(`OUTPUT_LIMIT`)을 넘으면 그 자리에서 멈춘다."""
        self.out += size
        if self.out > OUTPUT_LIMIT:
            raise _fail("unsupported_format", "뽑은 글이 상한을 넘는다", reason="too_large")

    def read(self, name: str) -> bytes | None:
        if name not in self.names:
            return None
        out = bytearray()
        try:
            with self.zip.open(self.names[name]) as f:
                while chunk := f.read(65536):
                    self.used += len(chunk)
                    if self.used > UNZIP_LIMIT:
                        raise _fail(
                            "unsupported_format",
                            "압축을 푼 크기가 상한을 넘는다",
                            reason="too_large",
                        )
                    out += chunk
        except (zipfile.BadZipFile, OSError, EOFError, NotImplementedError) as exc:
            raise _fail("unsupported_format", "Office 파일이 깨졌다", reason="corrupt") from exc
        return bytes(out)

    def xml(self, name: str) -> ElementTree.Element | None:
        data = self.read(name)
        if data is None:
            return None
        _reject_dtd(data)
        try:
            return ElementTree.fromstring(data)
        except ElementTree.ParseError as exc:
            raise _fail("unsupported_format", "Office XML이 깨졌다", reason="corrupt") from exc


class _DtdFound(Exception):
    pass


def _dtd(*_: object) -> None:
    raise _DtdFound


def _reject_dtd(data: bytes) -> None:
    """OOXML은 DTD를 쓰지 않는다 — 엔티티 확장(XML 폭탄)을 아예 받지 않는다. 바이트 검색이 아니라
    expat 파서가 인코딩(UTF-8·UTF-16 LE/BE, BOM)을 풀고 본 DOCTYPE·ENTITY 선언에서 멈춘다(검수 1
    M3). 이 검사를 지난 바이트만 ElementTree가 다시 읽는다."""
    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = _dtd
    parser.EntityDeclHandler = _dtd
    try:
        parser.Parse(data, True)
    except _DtdFound as exc:
        raise _fail("unsupported_format", "Office XML에 DTD가 있다", reason="dtd") from exc
    except expat.ExpatError as exc:
        raise _fail("unsupported_format", "Office XML이 깨졌다", reason="corrupt") from exc


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _paragraphs(z: _Unzip, root: ElementTree.Element, para: str) -> list[str]:
    """`para` 요소마다 한 줄: 글(`t`)·탭·줄바꿈. 더할 때마다 출력 상한을 센다."""
    lines: list[str] = []
    for p in root.iter():
        if _local(p.tag) != para:
            continue
        parts: list[str] = []
        for node in p.iter():
            name = _local(node.tag)
            piece = ""
            if name == "t" and node.text:
                piece = node.text
            elif name == "tab":
                piece = "\t"
            elif name in ("br", "cr"):
                piece = "\n"
            if piece:
                z.spend(len(piece))
                parts.append(piece)
        z.spend(1)
        lines.append("".join(parts))
    return lines


def _docx(z: _Unzip) -> str:
    doc = z.xml("word/document.xml")
    if doc is None:
        raise _fail("unsupported_format", "docx에 본문이 없다", reason="corrupt")
    return "\n".join(_paragraphs(z, doc, "p"))


def _rels(z: _Unzip, name: str) -> dict[str, str]:
    root = z.xml(name)
    out: dict[str, str] = {}
    if root is None:
        return out
    for rel in root.iter():
        if _local(rel.tag) == "Relationship" and rel.get("Id") and rel.get("Target"):
            out[str(rel.get("Id"))] = str(rel.get("Target"))
    return out


def _part_path(base: str, target: str) -> str:
    target = target.replace("\\", "/")
    if target.startswith("/"):
        return target.lstrip("/")
    parts = [*base.split("/"), *target.split("/")]
    out: list[str] = []
    for p in parts:
        if p == "..":
            if out:
                out.pop()
        elif p and p != ".":
            out.append(p)
    return "/".join(out)


_CELL: Final = re.compile(r"^([A-Z]+)([0-9]+)$")
_R_ID: Final = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _column(ref: str | None) -> int | None:
    match = _CELL.fullmatch(ref or "")
    if match is None:
        return None
    n = 0
    for ch in match.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _xlsx(z: _Unzip) -> str:
    shared: list[str] = []
    strings = z.xml("xl/sharedStrings.xml")
    if strings is not None:
        for si in strings:
            if _local(si.tag) == "si":
                shared.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"))
    book = z.xml("xl/workbook.xml")
    if book is None:
        raise _fail("unsupported_format", "xlsx에 통합 문서가 없다", reason="corrupt")
    rels = _rels(z, "xl/_rels/workbook.xml.rels")
    sheets = [s for s in book.iter() if _local(s.tag) == "sheet"][:PART_LIMIT]
    out: list[str] = []
    for sheet in sheets:
        target = rels.get(str(sheet.get(_R_ID) or ""))
        if target is None:
            continue
        doc = z.xml(_part_path("xl", target))
        if doc is None:
            continue
        out.append(f"## {sheet.get('name') or '-'}")
        for row in doc.iter():
            if _local(row.tag) != "row":
                continue
            cells: list[str] = []
            for c in row:
                if _local(c.tag) != "c":
                    continue
                kind = c.get("t")
                value = ""
                if kind == "inlineStr":
                    value = "".join(t.text or "" for t in c.iter() if _local(t.tag) == "t")
                else:
                    v = next((x for x in c if _local(x.tag) == "v"), None)
                    raw = "" if v is None else (v.text or "")
                    if kind == "s":
                        try:
                            value = shared[int(raw)]
                        except ValueError, IndexError:
                            value = ""
                    elif kind == "b":
                        value = "TRUE" if raw == "1" else "FALSE"
                    else:
                        value = raw
                col = _column(c.get("r"))
                if col is not None and col < 16384 and len(cells) < col:
                    # 빈 열 채움(탭)도 출력이다 — 셀마다 먼 열을 가리키는 증폭을 같이 센다
                    z.spend(col - len(cells))
                    cells.extend([""] * (col - len(cells)))
                # 공유 문자열은 셀마다 다시 나온다 — 셀 하나를 더할 때마다 센다 (검수 1 M2)
                z.spend(len(value) + 1)
                cells.append(value.replace("\t", " ").replace("\r", " ").replace("\n", " "))
            while cells and cells[-1] == "":
                cells.pop()
            out.append("\t".join(cells))
        out.append("")
    return "\n".join(out).rstrip("\n")


_SLIDE: Final = re.compile(r"^ppt/slides/slide([0-9]+)\.xml$")


def _pptx(z: _Unzip) -> str:
    slides = sorted(
        ((int(m.group(1)), name) for name in z.names if (m := _SLIDE.fullmatch(name))),
    )[:PART_LIMIT]
    out: list[str] = []
    for number, name in slides:
        doc = z.xml(name)
        if doc is None:
            continue
        out.append(f"## 슬라이드 {number}")
        out += [line for line in _paragraphs(z, doc, "p") if line.strip()]
        out.append("")
    return "\n".join(out).rstrip("\n")


_OFFICE: Final[dict[str, Callable[[_Unzip], str]]] = {
    ".docx": _docx,
    ".xlsx": _xlsx,
    ".pptx": _pptx,
}


def extract_text(name: str, data: bytes) -> tuple[str, str]:
    """(글, 형식 text·docx·xlsx·pptx). 아니면 `unsupported_format`."""
    suffix = Path(name).suffix.casefold()
    if suffix in _OFFICE:
        if not data.startswith(b"PK"):
            raise _fail("unsupported_format", "Office 파일이 깨졌다", reason="corrupt")
        return _OFFICE[suffix](_Unzip(data)), suffix[1:]
    if data.startswith(b"PK\x03\x04"):
        raise _fail("unsupported_format", "텍스트·docx·xlsx·pptx가 아니다", reason="binary")
    return _decode(data), "text"


# ---------------------------------------------------------------- 읽기


def _mask(text: str, values: Iterable[str]) -> str:
    for value in sorted({v for v in values if v}, key=len, reverse=True):
        text = text.replace(value, _MASK)
    return text


def _encoded(text: str) -> int:
    """JSON 글자(따옴표 뺀)로 실었을 때 UTF-8 바이트 — MCP 결과 상한(256 KiB)은 이 크기로 잰다
    (줄바꿈·탭·따옴표 이스케이프로 원문보다 커진다)."""
    return len(json.dumps(text, ensure_ascii=False).encode("utf-8")) - 2


def _slice(text: str, offset: int, limit: int) -> str:
    """`offset` 글자부터 JSON으로 실어 `limit` 바이트 안에 드는 만큼 (글자 중간에서 자르지
    않는다)."""
    chunk = text[offset : offset + limit]
    if _encoded(chunk) <= limit:
        return chunk
    lo, hi = 0, len(chunk)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _encoded(chunk[:mid]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return chunk[:lo]


def read_source(
    workspace: Workspace,
    source_id: str,
    rel: str = "",
    *,
    offset: int = 0,
    secrets: SecretValues,
    limit: int = TEXT_LIMIT,
) -> dict[str, Any]:
    """원본 파일 하나의 글. `secrets()`가 가림 값(작업 토큰·워크스페이스 비밀값)을 준다 — 예외면
    `secret_unchecked`로 글을 주지 않는다."""
    if offset < 0:
        raise _fail("format", "offset은 0 이상이다")
    _source, real_root = _root_of(workspace, source_id)
    target = _target(workspace, real_root, rel)
    clean = rel.replace("\\", "/").strip().strip("/")
    if target.is_dir():
        raise _fail("policy_path", "폴더다 — kb_source_list로 항목을 본다")
    try:
        size = target.stat().st_size
        if size > FILE_LIMIT:
            raise _fail("unsupported_format", "원본 파일이 너무 크다", reason="too_large")
        data = target.read_bytes()
    except FileNotFoundError as exc:
        raise _fail("unknown_id", "원본 안에 그 경로가 없다", id=source_id) from exc
    except OSError as exc:
        raise _fail("source_unavailable", "원본 파일을 읽을 수 없다", reason="unreadable") from exc
    text, kind = extract_text(target.name, data)
    try:
        values = list(secrets())
    except Exception as exc:
        raise _fail("secret_unchecked", "비밀값을 확인하지 못해 원본 글을 주지 않는다") from exc
    text = _mask(text, values)
    values.clear()
    piece = _slice(text, offset, limit)
    end = offset + len(piece)
    return {
        "source": source_id,
        "path": clean,
        "ref": _ref(source_id, clean),
        "hash": _file_hash(target),
        "format": kind,
        "bytes": size,
        "chars": len(text),
        "offset": offset,
        "next_offset": end if end < len(text) else None,
        "text": piece,
    }
