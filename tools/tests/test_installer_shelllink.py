"""설치 스모크의 바로 가기 읽기: ANSI 코드 페이지 밖 글자가 든 경로도 그대로 읽는다.

CI 러너(시스템 로캘 cp1252)에서 한글 설치 폴더 바로 가기를 WScript.Shell로 읽으면 `?`가 되어
`install.shortcut`이 틀리게 실패했다. 로컬(cp949)에서는 한글이 ANSI에 있어 드러나지 않으므로
cp949·cp1252 둘 다 없는 태국 글자를 함께 넣어 같은 상황을 만든다.
"""

from __future__ import annotations

import struct
from pathlib import Path

from installer import shelllink, smoke

# MS-SHLLINK LinkFlags(오프셋 0x14)의 IsUnicode
_IS_UNICODE = 0x80


def test_shortcut_target_keeps_characters_outside_ansi_code_page(tmp_path: Path) -> None:
    folder = tmp_path / "설치 폴더 공백 한글 ทดสอบ"
    folder.mkdir()
    exe = folder / "KookabugTest.exe"
    exe.write_bytes(b"MZ")
    link = tmp_path / "Kookabug Test.lnk"
    shelllink.write_shortcut(link, exe, exe, 0)
    assert struct.unpack_from("<I", link.read_bytes(), 0x14)[0] & _IS_UNICODE
    assert shelllink.is_unicode(link)

    aim, icon = smoke.shortcut_target(link)

    assert aim == str(exe)
    assert icon == f"{exe},0"
    assert smoke.same_file(aim, exe)


def test_is_unicode_reads_link_flags(tmp_path: Path) -> None:
    exe = tmp_path / "a.exe"
    exe.write_bytes(b"MZ")
    link = tmp_path / "a.lnk"
    shelllink.write_shortcut(link, exe, exe, 0)
    raw = bytearray(link.read_bytes())
    flags = struct.unpack_from("<I", raw, 0x14)[0]
    struct.pack_into("<I", raw, 0x14, flags & ~_IS_UNICODE)
    ansi = tmp_path / "ansi.lnk"
    ansi.write_bytes(bytes(raw))
    assert not shelllink.is_unicode(ansi)
    junk = tmp_path / "junk.lnk"
    junk.write_text("lnk", encoding="utf-8")
    assert not shelllink.is_unicode(junk)
