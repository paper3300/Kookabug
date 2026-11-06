"""검사용 로컬 패키지 인덱스 (M6 계획 D15): 127.0.0.1의 PEP 503 simple 인덱스.

    with IndexServer(files_dir) as index:       # files_dir = wheel·sdist 파일 폴더
        url = index.url                         # http://127.0.0.1:<포트>/simple
        index.requests                          # 받은 경로 (검사가 무엇을 받았는지 본다)

PyPI 역할이다. 파일 목록은 요청마다 폴더에서 다시 읽는다(검사 중에 파일을 더해도 된다). 링크에
`#sha256=`를 붙이고, 파일은 `/files/<이름>`으로 준다. 네트워크 밖으로 나가지 않는다.
"""

from __future__ import annotations

import hashlib
import html
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from typing import Self
from urllib.parse import unquote

__all__ = ["IndexServer"]

_DIST = re.compile(r"^(?P<name>[A-Za-z0-9_.]+?)-(?P<version>\d[^-]*?)(-|\.tar\.gz$)")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


class IndexServer:
    def __init__(self, files: Path) -> None:
        self.files = files
        self.requests: list[str] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_HEAD(self) -> None:
                # uv는 wheel 메타데이터를 범위 요청으로 읽으려 HEAD를 먼저 본다: 범위는 안 준다
                self._head_only = True
                self.do_GET()

            def do_GET(self) -> None:
                server.requests.append(f"{self.command} {self.path}")
                path = unquote(self.path.split("?", 1)[0])
                if path in ("/simple", "/simple/"):
                    names = sorted({_normalize(n) for n, _ in server._dists()})
                    body = "".join(f'<a href="/simple/{n}/">{n}</a>\n' for n in names)
                    return self._html(body)
                if path.startswith("/simple/"):
                    wanted = _normalize(path[len("/simple/") :].strip("/"))
                    links = [
                        f'<a href="/files/{html.escape(p.name)}#sha256='
                        f'{hashlib.sha256(p.read_bytes()).hexdigest()}">{html.escape(p.name)}</a>'
                        for name, p in server._dists()
                        if _normalize(name) == wanted
                    ]
                    if not links:
                        return self._send(404, b"not found", "text/plain")
                    return self._html("\n".join(links))
                if path.startswith("/files/"):
                    target = server.files / path[len("/files/") :]
                    if target.parent != server.files or not target.is_file():
                        return self._send(404, b"not found", "text/plain")
                    return self._send(200, target.read_bytes(), "application/octet-stream")
                return self._send(404, b"not found", "text/plain")

            def _html(self, body: str) -> None:
                page = f"<!DOCTYPE html><html><body>\n{body}\n</body></html>\n"
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

            def _send(self, status: int, data: bytes, kind: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if not getattr(self, "_head_only", False):
                    self.wfile.write(data)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="kb-plugin-index", daemon=True
        )

    def _dists(self) -> list[tuple[str, Path]]:
        out: list[tuple[str, Path]] = []
        for p in sorted(self.files.iterdir()):
            match = _DIST.match(p.name)
            if match and (p.suffix == ".whl" or p.name.endswith(".tar.gz")):
                out.append((match["name"], p))
        return out

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host!s}:{port}/simple"

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(5)
