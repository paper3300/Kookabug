"""플러그인 원천 받기 (M6 계획 3.5 ①, 3.5a). 코드를 실행하지 않는다 — 받기·복사만.

원천 세 가지 (D1):

- `git+<url>[@ref]` (`--ref`로도): 허용 URL은 `https://`·로컬 절대 경로·`file://`.
  `ssh://`·`user@host:path`(MVP 뒤, U14)·`ext::`·`git://`·`http://`·remote helper(`x::y`)는 아무
  명령 전 `source_refused`. ref는 `^[A-Za-z0-9._/-]+$`이고 `-`로 시작하지 않는다
- wheel: 파일 경로 또는 `https://…whl`(sha256 필수, 받은 바이트 대조)
- path: 로컬 폴더 (`pyproject.toml`이 있는 프로젝트)

git은 사용자 설정을 쓰지 않는다: 시스템·전역 설정 끔(`GIT_CONFIG_NOSYSTEM`, 빈
`GIT_CONFIG_GLOBAL`), 자식 환경은 허용 목록만(실행 계열 변수 계승 없음), 빈 훅 폴더·템플릿,
허용 전송(https·file)만, 서브모듈 없이
`init` + `fetch`(원격 URL을 설정에 남기지 않음)로 받은 뒤 커밋을 정해 `checkout --detach`. 그래서
훅·필터 드라이버·LFS·fsmonitor·자격 증명 도우미가 돌지 않는다. git 저장소 폴더는 짧은 임시 폴더에
두고(깊은 경로의 index-pack 실패 회피) 끝나면 지운다 — staging에는 체크아웃한 파일만 남는다.

인증 정보(URL 사용자 정보·비밀 쿼리 값)는 받기에만 쓰고 잠금 `source`·응답 메시지·로그에서 지운다.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import os
import re
import shutil
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from kookabug_core.plugins.errors import PluginError
from kookabug_core.plugins.uv import SECRET_QUERY, ProcessRunner, mask, remove_tree

__all__ = [
    "Fetched",
    "SourceSpec",
    "fetch",
    "git_env",
    "parse_source",
    "strip_credentials",
]

type Kind = Literal["git", "wheel", "path"]

REF: Final = re.compile(r"^[A-Za-z0-9._/-]+$")
_SCP: Final = re.compile(r"^[A-Za-z0-9._~-]+@[A-Za-z0-9.-]+:(?!//)")
_SCHEME: Final = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")
_DRIVE: Final = re.compile(r"^[A-Za-z]:[\\/]")
_COPY_SKIP: Final = frozenset({".git", ".venv", "__pycache__"})
_SSH_LATER: Final = (
    "ssh git 원천은 MVP 뒤다 (ssh는 사용자 설정의 명령을 실행할 수 있다). "
    "비공개 레포는 https 주소에 토큰을 넣는다 (git+https://<토큰>@호스트/…)"
)
# git 자식 환경은 허용 목록만 (실행 계열 변수 GIT_SSH*·GIT_PROXY_COMMAND·GIT_ASKPASS·SSH_ASKPASS
# 같은 것은 계승하지 않는다). 프록시·인증서 경로는 실행이 아니라 통과
_GIT_ENV_KEEP: Final = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "ALL_PROXY",
        "GIT_SSL_CAINFO",
        "GIT_SSL_CAPATH",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
)
_DOWNLOAD_LIMIT: Final = 256 * 1024 * 1024
DOWNLOAD_TIMEOUT_S: Final = 60.0


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """사용자가 준 원천 (인증 정보가 든 그대로 — 잠금·응답에는 `strip_credentials`)."""

    kind: Kind
    location: str
    """git URL·wheel 경로/URL·폴더 경로 (로컬 경로는 절대 경로)."""
    ref: str | None = None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class Fetched:
    """① 결과: wheel 원천이면 `wheel`, git·path면 `project`(staging 안 복사본)."""

    spec: SourceSpec
    source: dict[str, Any]
    """잠금 `source` (인증 정보 없음)."""
    wheel: Path | None = None
    project: Path | None = None


def _refused(message: str) -> PluginError:
    return PluginError("source_refused", message, stage="fetch")


def strip_credentials(url: str) -> str:
    """잠금·화면에 남길 URL: https·http의 사용자 정보 전체, ssh의 비밀번호, 비밀 쿼리 값을 뺀다.
    ssh 사용자 이름(`git@`)은 남긴다 (비밀이 아니고 다시 받기에 필요)."""
    match = _SCHEME.match(url)
    if match is None:
        return SECRET_QUERY.sub(r"\1***", url)
    parts = urllib.parse.urlsplit(url)
    netloc = parts.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        if parts.scheme.lower() == "ssh":
            user = userinfo.split(":", 1)[0]
            netloc = f"{user}@{host}" if user else host
        else:
            netloc = host
    query = "&".join(
        f"{k}=***" if SECRET_QUERY.search(f"?{k}=x") else (f"{k}={v}" if v else k)
        for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    )
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


# ------------------------------------------------------------------ 해석


def _split_ref(url: str) -> tuple[str, str | None]:
    """`<url>@<ref>`를 나눈다. `@`는 경로 부분(호스트·사용자 정보 뒤)에서만 찾는다."""
    if (m := _SCHEME.match(url)) is not None:
        parts = urllib.parse.urlsplit(url)
        if "@" not in parts.path:
            return url, None
        path, ref = parts.path.rsplit("@", 1)
        head = url[: m.end()] + parts.netloc
        rest = path + (f"?{parts.query}" if parts.query else "")
        return head + rest, ref
    if _SCP.match(url):
        host, path = url.split(":", 1)
        if "@" in path:
            path, ref = path.rsplit("@", 1)
            return f"{host}:{path}", ref
        return url, None
    if "@" in url:
        base, ref = url.rsplit("@", 1)
        if REF.match(ref) and "\\" not in ref:
            return base, ref
    return url, None


def check_ref(ref: str) -> str:
    if not REF.match(ref) or ref.startswith("-") or ".." in ref:
        raise _refused(f"ref {ref!r}은(는) 쓸 수 없다 (영문·숫자·._/-, '-'로 시작하지 않음)")
    return ref


_URL_CHARS: Final = re.compile(r"^[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+$")
_BAD_PERCENT: Final = re.compile(r"%(?![0-9A-Fa-f]{2})")


def check_https_url(url: str) -> str:
    """https wheel 주소를 요청 전에 엄격히 본다: RFC 3986 문자만(공백·제어·비ASCII 문자는 미리
    퍼센트 인코딩), 올바른 퍼센트 인코딩, 호스트·포트. 아니면 `source_refused` (주소는 가린
    것만)."""
    shown = strip_credentials(url) if _URL_CHARS.match(url) else "https 주소"
    if not _URL_CHARS.match(url) or _BAD_PERCENT.search(url):
        raise _refused(
            f"{shown}: 주소에 쓸 수 없는 문자(공백·제어·비ASCII)나 잘못된 퍼센트 인코딩이 있다"
        )
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        raise _refused(f"{shown}: 주소의 호스트·포트를 읽을 수 없다") from None
    if parts.scheme.lower() != "https" or not parts.hostname or port == 0:
        raise _refused(f"{shown}: https 호스트가 없다")
    return url


def check_git_url(url: str) -> str:
    """허용 전송인지 본다. 로컬 경로는 절대 경로여야 한다."""
    if not url or url.startswith("-"):
        raise _refused("git URL이 비었거나 '-'로 시작한다")
    if "::" in url:
        raise _refused(f"remote helper 주소({mask(url)})는 쓸 수 없다")
    if (m := _SCHEME.match(url)) is not None:
        scheme = m.group(1).lower()
        if scheme == "ssh":
            raise _refused(_SSH_LATER)
        if scheme not in ("https", "file"):
            raise _refused(f"{scheme}:// 전송은 쓸 수 없다 (https·file만)")
        return url
    if _SCP.match(url):
        raise _refused(_SSH_LATER)
    if _DRIVE.match(url) or url.startswith("\\\\"):
        return url
    raise _refused(f"git 주소 {mask(url)}을(를) 알 수 없다 (https·file://·절대 경로)")


def parse_source(
    text: str, *, ref: str | None = None, sha256: str | None = None, cwd: Path | None = None
) -> SourceSpec:
    """원천 문자열 → `SourceSpec`. 받지 않는다 (검사만)."""
    raw = text.strip()
    if not raw:
        raise _refused("원천이 비었다")
    if sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise _refused("--sha256은 64자리 16진수다")
    if raw.startswith("git+"):
        url, inline = _split_ref(raw[4:])
        if inline is not None and ref is not None and inline != ref:
            raise _refused(f"ref가 둘이다 ({inline}, {ref})")
        chosen = ref or inline
        url = check_git_url(url)
        return SourceSpec("git", url, None if chosen is None else check_ref(chosen))
    if ref is not None:
        raise _refused("--ref는 git 원천에만 쓴다")
    if (m := _SCHEME.match(raw)) is not None:
        scheme = m.group(1).lower()
        path = urllib.parse.urlsplit(raw).path
        if scheme != "https" or not path.endswith(".whl"):
            raise _refused(
                f"{mask(raw)}: URL 원천은 https://…whl만 받는다 (git은 git+ 접두, http는 거부)"
            )
        if sha256 is None:
            raise _refused("https wheel은 --sha256이 필요하다")
        return SourceSpec("wheel", check_https_url(raw), sha256=sha256.lower())
    path = Path(raw)
    if not path.is_absolute():
        path = (cwd or Path.cwd()) / path
    if path.suffix == ".whl" and not path.is_dir():
        return SourceSpec("wheel", str(path), sha256=None if sha256 is None else sha256.lower())
    if sha256 is not None:
        raise _refused("--sha256은 wheel 원천에만 쓴다")
    if path.is_dir():
        return SourceSpec("path", str(path))
    if path.exists():
        raise _refused(f"{raw}은(는) wheel 파일(.whl)·폴더·git+URL이 아니다")
    raise PluginError("source_unavailable", f"{raw}이(가) 없다", stage="fetch")


def from_lock(entry_source: Mapping[str, Any], root: Path, *, ref: str | None) -> SourceSpec:
    """잠금 `source` → 다시 받을 원천 (`upgrade`). 인증 정보는 잠금에 없으므로 그대로 받는다."""
    kind = entry_source.get("kind")
    if kind == "git":
        url = check_git_url(str(entry_source["url"]))
        chosen = ref if ref is not None else entry_source.get("ref")
        return SourceSpec("git", url, None if chosen is None else check_ref(str(chosen)))
    if ref is not None:
        raise _refused("--ref는 git 원천에만 쓴다")
    if kind == "wheel":
        if entry_source.get("url"):
            url = check_https_url(str(entry_source["url"]))
            return SourceSpec("wheel", url, sha256=entry_source["sha256"])
        return SourceSpec("wheel", str(_local(root, str(entry_source["path"]))))
    if kind == "path":
        return SourceSpec("path", str(_local(root, str(entry_source["path"]))))
    raise _refused(f"모르는 원천 {kind!r}")


def _local(root: Path, recorded: str) -> Path:
    path = Path(recorded)
    return path if path.is_absolute() else root.joinpath(*recorded.split("/"))


def _recorded_path(root: Path, path: Path) -> str:
    """잠금의 로컬 경로: 워크스페이스 안이면 '/' 상대 경로, 밖이면 절대 경로 그대로."""
    resolved = path.resolve()
    return resolved.relative_to(root).as_posix() if resolved.is_relative_to(root) else str(resolved)


# ------------------------------------------------------------------ 받기


def fetch(spec: SourceSpec, dest: Path, runner: ProcessRunner, *, root: Path) -> Fetched:
    """① 원천을 `dest`(staging 안, 없는 폴더) 아래로 받는다. 코드를 실행하지 않는다."""
    dest.mkdir(parents=True)
    if spec.kind == "git":
        return _fetch_git(spec, dest, runner)
    if spec.kind == "path":
        source = Path(spec.location)
        if not (source / "pyproject.toml").is_file():
            raise PluginError(
                "source_unavailable", f"{source}에 pyproject.toml이 없다", stage="fetch"
            )
        project = dest / "project"
        try:
            _copy_tree(source, project)
        except OSError as exc:
            raise PluginError(
                "source_unavailable",
                f"{source}을(를) 복사할 수 없다: {type(exc).__name__}: {exc}",
                stage="fetch",
            ) from None
        return Fetched(
            spec, {"kind": "path", "path": _recorded_path(root, source)}, project=project
        )
    if _SCHEME.match(spec.location):
        return _fetch_wheel_url(spec, dest)
    path = Path(spec.location)
    if not path.is_file():
        raise PluginError("source_unavailable", f"{path}이(가) 없다", stage="fetch")
    target = dest / path.name
    try:
        shutil.copyfile(path, target)
    except OSError as exc:
        raise PluginError(
            "source_unavailable", f"{path}을(를) 읽을 수 없다: {exc}", stage="fetch"
        ) from exc
    digest = _sha256(target)
    if spec.sha256 is not None and spec.sha256 != digest:
        raise PluginError("source_unavailable", "wheel sha256이 다르다", stage="fetch")
    return Fetched(
        spec,
        {"kind": "wheel", "path": _recorded_path(root, path), "sha256": digest},
        wheel=target,
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class _HttpsOnlyVisits(dict[str, int]):
    """urllib 넘겨주기(redirect) 방문 기록. 표준 `HTTPRedirectHandler`는 다음 요청을 열기 **전에**
    `req.redirect_dict.get(새 주소)`로 고리를 검사하고 새 요청에 같은 기록을 넘긴다 — 여기서 https가
    아닌 주소를 거부하면 평문 요청(과 주소의 비밀 쿼리)이 나가지 않는다. 처리기를 갈아 끼운
    opener를 받아도(검사용 가짜 전송 포함) 표준 처리기를 쓰는 한 같다."""

    def __init__(self, shown: str) -> None:
        super().__init__()
        self.shown = shown

    def get(self, key: str, default: int = 0) -> int:  # type: ignore[override]
        if urllib.parse.urlsplit(key).scheme.lower() != "https":
            raise _refused(f"{self.shown}: https가 아닌 주소로 넘어가려 했다 (요청 전 거부)")
        return super().get(key, default)


def _fetch_wheel_url(spec: SourceSpec, dest: Path) -> Fetched:
    parts = urllib.parse.urlsplit(spec.location)
    name = urllib.parse.unquote(parts.path.rsplit("/", 1)[-1])
    if not name.endswith(".whl") or "/" in name or "\\" in name:
        raise _refused(f"{strip_credentials(spec.location)}: wheel 파일 이름을 알 수 없다")
    host = parts.hostname or ""
    netloc = host + (f":{parts.port}" if parts.port else "")
    clean = urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
    request = urllib.request.Request(clean, headers={"User-Agent": "kookabug-plugin"})
    if parts.username is not None:
        user = urllib.parse.unquote(parts.username)
        password = urllib.parse.unquote(parts.password or "")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        # 넘겨주기(redirect)에는 싣지 않는다
        request.add_unredirected_header("Authorization", f"Basic {token}")
    target = dest / name
    shown = strip_credentials(spec.location)
    request.redirect_dict = _HttpsOnlyVisits(shown)  # pyright: ignore[reportAttributeAccessIssue]
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
            # 보조 검사 (넘겨주기는 위 방문 기록이 요청 전에 막는다)
            if urllib.parse.urlsplit(response.geturl()).scheme != "https":
                raise _refused(f"{shown}: https가 아닌 주소로 넘어갔다")
            size = 0
            with target.open("wb") as f:
                while chunk := response.read(1 << 20):
                    size += len(chunk)
                    if size > _DOWNLOAD_LIMIT:
                        raise PluginError(
                            "source_unavailable", f"{shown}: 너무 크다", stage="fetch"
                        )
                    f.write(chunk)
    except PluginError:
        raise
    except Exception as exc:
        # 예외 문구에는 요청 경로·쿼리(인증 값)가 들어 있을 수 있다: 가린 문구만, 원인 연결 없음
        reason = getattr(exc, "reason", exc)
        raise PluginError(
            "source_unavailable",
            f"{shown}을(를) 받지 못했다: {type(exc).__name__}: {mask(str(reason))}",
            stage="fetch",
        ) from None
    if _sha256(target) != spec.sha256:
        raise PluginError("source_unavailable", f"{shown}: sha256이 다르다", stage="fetch")
    return Fetched(spec, {"kind": "wheel", "url": shown, "sha256": str(spec.sha256)}, wheel=target)


def git_env(environ: Mapping[str, str], empty: Path) -> dict[str, str]:
    """git 자식 환경: 허용 목록(`_GIT_ENV_KEEP`)만 계승하고, 사용자·시스템 git 설정을 끄고, HOME을
    빈 폴더로 둔다 (`empty`: 빈 설정 파일이 든 폴더). `GIT_SSH_COMMAND`·`GIT_PROXY_COMMAND`·
    `GIT_ASKPASS`·`XDG_CONFIG_HOME` 같은 실행·설정 계열 변수는 넘기지 않는다."""
    env = {k: v for k, v in environ.items() if k.upper() in _GIT_ENV_KEEP}
    env.update(
        HOME=str(empty),
        USERPROFILE=str(empty),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=str(empty / "gitconfig"),
        GIT_TERMINAL_PROMPT="0",
        GCM_INTERACTIVE="never",
    )
    return env


def _git_args(git: str, empty: Path) -> list[str]:
    hooks = str(empty / "hooks")
    return [
        git,
        "-c",
        f"core.hooksPath={hooks}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.longpaths=true",
        "-c",
        "credential.helper=",
        "-c",
        "core.askPass=",
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.https.allow=always",
        "-c",
        "protocol.file.allow=always",
    ]


def _fetch_git(spec: SourceSpec, dest: Path, runner: ProcessRunner) -> Fetched:
    git = shutil.which("git", path=runner.env.get("PATH"))
    if git is None:
        raise PluginError("source_unavailable", "git을 찾을 수 없다", stage="fetch")
    empty = dest / "git-empty"
    (empty / "hooks").mkdir(parents=True)
    (empty / "template").mkdir()
    (empty / "gitconfig").write_bytes(b"")
    run = dataclasses.replace(runner, env=git_env(runner.env, empty))
    repo = dest / "project"
    repo.mkdir()
    shown = strip_credentials(spec.location)
    # git 저장소 폴더는 짧은 임시 폴더에 둔다: Windows에서 GIT_DIR 경로가 길면(깊은 워크스페이스의
    # staging) index-pack이 실패한다. 받은 객체만 들고 원격 URL은 쓰지 않는다(아래 fetch).
    git_dir = Path(tempfile.mkdtemp(prefix="kbgit-"))
    base = [*_git_args(git, empty), f"--git-dir={git_dir}", f"--work-tree={repo}"]

    def git_(*args: str | Path, what: str) -> str:
        done = run.run([*base, *args], stage="fetch", cwd=dest)
        if done.returncode != 0:
            detail = mask(_last_line(done.stderr or done.stdout))
            raise PluginError(
                "source_unavailable", f"{shown}: {what} 실패: {detail}", stage="fetch"
            )
        return done.stdout.strip()

    try:
        git_("init", "--quiet", f"--template={empty / 'template'}", what="git init")
        # clone 대신 init + fetch: 원격 URL(인증 정보 포함)을 설정 파일에 남기지 않는다
        git_(
            "fetch",
            "--quiet",
            "--no-recurse-submodules",
            "--no-write-fetch-head",
            "--",
            spec.location,
            "+HEAD:refs/remotes/origin/HEAD",
            "+refs/heads/*:refs/remotes/origin/*",
            "+refs/tags/*:refs/tags/*",
            what="git fetch",
        )
        ref = spec.ref or "HEAD"
        commit = ""
        for candidate in (ref, f"origin/{ref}"):
            done = run.run(
                [*base, "rev-parse", "--verify", "--quiet", "--end-of-options",
                 f"{candidate}^{{commit}}"],
                stage="fetch",
                cwd=dest,
            )  # fmt: skip
            if done.returncode == 0:
                commit = done.stdout.strip()
                break
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise PluginError(
                "source_unavailable", f"{shown}: ref {ref}을(를) 찾지 못했다", stage="fetch"
            )
        git_("checkout", "--quiet", "--detach", commit, "--", what="git checkout")
    finally:
        remove_tree(git_dir)
    if not (repo / "pyproject.toml").is_file():
        raise PluginError(
            "source_unavailable", f"{shown}@{commit[:12]}에 pyproject.toml이 없다", stage="fetch"
        )
    return Fetched(
        spec,
        {"kind": "git", "url": shown, "ref": spec.ref, "commit": commit},
        project=repo,
    )


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _copy_tree(source: Path, dest: Path) -> None:
    """폴더 복사: 심볼릭 링크·정션은 따라가지도 복사하지도 않는다. `.git`·`.venv`·`__pycache__`
    제외. 원본에는 아무것도 쓰지 않는다."""
    dest.mkdir(parents=True)
    with os.scandir(source) as entries:
        for entry in entries:
            if entry.name in _COPY_SKIP or entry.is_symlink() or _is_junction(entry):
                continue
            target = dest / entry.name
            if entry.is_dir(follow_symlinks=False):
                _copy_tree(Path(entry.path), target)
            elif entry.is_file(follow_symlinks=False):
                shutil.copyfile(entry.path, target)


def _is_junction(entry: os.DirEntry[str]) -> bool:
    try:
        attrs = entry.stat(follow_symlinks=False).st_file_attributes
    except OSError, AttributeError:
        return False
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
