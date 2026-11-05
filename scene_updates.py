"""GitHub Releases updates for the manually published Windows Inno installer.

The UI calls these blocking functions from a worker, then asks the operator when
to install. In particular, a release check never interrupts a performance.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request


REPOSITORY = "hyjys/SCENE-App"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
LATEST_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
TIMEOUT = 20
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_INSTALLER_BYTES = 2 * 1024 * 1024 * 1024
_VERSION = re.compile(r"v?([0-9]{1,6}(?:\.[0-9]{1,6}){1,3})\Z")
_INSTALLER = re.compile(r"sceneapp-([0-9]{1,6}(?:\.[0-9]{1,6}){1,3})-windows-x64(?:-setup)?\.exe\Z")


class UpdateError(Exception):
    """A user-readable update failure; the current installation is untouched."""


class UpdateCancelled(UpdateError):
    pass


@dataclass(frozen=True)
class ReleaseUpdate:
    version: str
    tag: str
    name: str
    url: str
    size: int
    sha256: str | None
    release_url: str
    notes: str = ""


def version_tuple(value: str) -> tuple[int, int, int, int]:
    """Stable numeric versions only. 0.10 > 0.9 and 0.4 == 0.4.0."""
    match = _VERSION.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise UpdateError(f"지원하지 않는 버전 형식입니다: {str(value)[:80]}")
    parts = tuple(int(part) for part in match[1].split("."))
    return parts + (0,) * (4 - len(parts))


def _is_https_host(url: str, hosts: set[str]) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in hosts
                and parsed.port in {None, 443} and not parsed.username
                and not parsed.password and not parsed.fragment)
    except (ValueError, TypeError):
        return False


class _GitHubRedirects(urllib.request.HTTPRedirectHandler):
    """Release downloads may redirect to GitHub's own signed asset CDN."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        hosts = {"api.github.com", "github.com", "release-assets.githubusercontent.com",
                 "objects.githubusercontent.com"}
        if not _is_https_host(newurl, hosts):
            raise UpdateError("업데이트 다운로드가 GitHub 이외의 주소로 이동했습니다.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str):
    request = urllib.request.Request(url, headers={
        "User-Agent": "SCENE-App-Updater",
        "Accept": "application/vnd.github+json" if url == LATEST_API else "application/octet-stream",
        "X-GitHub-Api-Version": "2026-03-10",
    })
    return urllib.request.build_opener(_GitHubRedirects()).open(request, timeout=TIMEOUT)


def _validate_release(update: ReleaseUpdate) -> None:
    version_tuple(update.version)
    if update.tag not in {update.version, "v" + update.version}:
        raise UpdateError("릴리스 태그와 버전이 일치하지 않습니다.")
    allowed_names = {f"sceneapp-{update.version}-windows-x64.exe",
                     f"sceneapp-{update.version}-windows-x64-setup.exe"}
    if update.name not in allowed_names:
        raise UpdateError("공식 SCENE App 설치 파일 이름이 아닙니다.")
    expected = f"https://github.com/{REPOSITORY}/releases/download/{update.tag}/{update.name}"
    if update.url != expected:
        raise UpdateError("설치 파일이 공식 GitHub 저장소의 릴리스 주소가 아닙니다.")
    if (type(update.size) is not int or not 2 <= update.size <= MAX_INSTALLER_BYTES):
        raise UpdateError("설치 파일의 크기 정보가 올바르지 않습니다.")
    if update.sha256 is not None and not re.fullmatch(r"[a-fA-F0-9]{64}", update.sha256):
        raise UpdateError("설치 파일의 SHA-256 정보가 올바르지 않습니다.")
    if update.release_url != f"{RELEASES_URL}/tag/{update.tag}":
        raise UpdateError("릴리스 설명 주소가 공식 저장소의 주소가 아닙니다.")


def check_for_update(current_version: str) -> ReleaseUpdate | None:
    """Read the latest published stable release, without downloading an installer.

    A newer release without its installer is reported as an actionable error;
    this can happen while a manual release upload is still in progress.
    """
    current = version_tuple(current_version)
    try:
        with _open(LATEST_API) as response:
            raw = response.read(MAX_METADATA_BYTES + 1)
        if len(raw) > MAX_METADATA_BYTES:
            raise UpdateError("GitHub 릴리스 정보가 너무 큽니다.")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise UpdateError("GitHub 릴리스 정보를 읽을 수 없습니다.")
        if payload.get("draft") or payload.get("prerelease"):
            return None
        tag = payload.get("tag_name", "")
        # GitHub prerelease flags occasionally differ from the tag; never offer
        # an alpha/rc installer to the performance operator.
        if not isinstance(tag, str) or not _VERSION.fullmatch(tag):
            return None
        if version_tuple(tag) <= current:
            return None
        version = tag.removeprefix("v")
        preferred = [f"sceneapp-{version}-windows-x64.exe",
                     f"sceneapp-{version}-windows-x64-setup.exe"]
        assets = payload.get("assets", [])
        if not isinstance(assets, list):
            raise UpdateError("GitHub 설치 파일 목록을 읽을 수 없습니다.")
        asset = next((entry for name in preferred for entry in assets
                      if isinstance(entry, dict) and entry.get("name") == name
                      and entry.get("state", "uploaded") == "uploaded"), None)
        if asset is None:
            raise UpdateError(f"v{version} 릴리스에 Windows 설치 파일이 아직 없습니다. 나중에 다시 확인해 주세요.")
        digest = asset.get("digest")
        if digest is not None and (not isinstance(digest, str) or not digest.startswith("sha256:")):
            raise UpdateError("지원하지 않는 설치 파일 해시 형식입니다.")
        update = ReleaseUpdate(
            version, tag, asset.get("name", ""), asset.get("browser_download_url", ""),
            asset.get("size", 0), digest.removeprefix("sha256:") if digest else None,
            payload.get("html_url", ""), str(payload.get("body") or "")[:40000],
        )
        _validate_release(update)
        return update
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code == 404:
            return None
        if exc.code in {403, 429}:
            raise UpdateError("GitHub 요청 한도를 초과했습니다. 잠시 후 다시 확인해 주세요.") from exc
        raise UpdateError(f"GitHub 업데이트 확인 실패 (HTTP {exc.code}).") from exc
    except (OSError, ValueError, TypeError, urllib.error.URLError) as exc:
        raise UpdateError(f"업데이트 확인에 실패했습니다. 인터넷 연결을 확인해 주세요.\n{exc}") from exc


def update_cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".cache") / "SCENE App" / "updates"


def download_update(update: ReleaseUpdate, *, cache_dir: Path | None = None,
                    cancel: threading.Event | None = None,
                    progress: Callable[[int, int], None] | None = None) -> Path:
    """Download and verify the installer, publishing it only after completion.

    Progress runs on the caller's worker thread; put messages into the Tk queue.
    Cancelled/failed partials are deleted, never replacing a previously valid exe.
    """
    _validate_release(update)
    if cancel is not None and cancel.is_set():
        raise UpdateCancelled("업데이트 다운로드를 취소했습니다.")
    directory = Path(cache_dir) if cache_dir is not None else update_cache_dir()
    partial: Path | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=update.name + ".", suffix=".part", dir=directory)
        partial = Path(temporary)
        size = 0
        digest = hashlib.sha256()
        first_bytes = b""
        with os.fdopen(descriptor, "wb") as target, _open(update.url) as response:
            header = response.headers.get("Content-Length")
            if header is not None and int(header) != update.size:
                raise UpdateError("설치 파일 크기가 GitHub 릴리스 정보와 다릅니다.")
            if progress:
                progress(0, update.size)
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateCancelled("업데이트 다운로드를 취소했습니다.")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > update.size:
                    raise UpdateError("설치 파일이 GitHub에 표시된 크기를 초과했습니다.")
                if len(first_bytes) < 2:
                    first_bytes = (first_bytes + chunk)[:2]
                target.write(chunk)
                digest.update(chunk)
                if progress:
                    progress(size, update.size)
            target.flush()
            os.fsync(target.fileno())
        if cancel is not None and cancel.is_set():
            raise UpdateCancelled("업데이트 다운로드를 취소했습니다.")
        if size != update.size:
            raise UpdateError("설치 파일 다운로드가 완전하지 않습니다. 다시 시도해 주세요.")
        if first_bytes != b"MZ":
            raise UpdateError("다운로드한 파일이 Windows 실행 파일이 아닙니다.")
        if update.sha256 and digest.hexdigest().lower() != update.sha256.lower():
            raise UpdateError("설치 파일 SHA-256 검증에 실패했습니다. 다시 다운로드해 주세요.")
        destination = directory / update.name
        os.replace(partial, destination)
        return destination
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise UpdateError(f"설치 파일 다운로드에 실패했습니다.\n{exc}") from exc
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)


def launch_installer(path: Path) -> subprocess.Popen:
    """Open the interactive Inno wizard; the UI should close SCENE on success.

    No forced process termination or unattended installation is requested.
    /NORESTART avoids an unexpected Windows restart, and /CLOSEAPPLICATIONS lets
    Inno wait for remaining files to be released during the normal app shutdown.
    """
    path = Path(path).resolve()
    if sys.platform != "win32":
        raise UpdateError("자동 설치는 Windows에서만 지원합니다.")
    if not _INSTALLER.fullmatch(path.name) or not path.is_file():
        raise UpdateError("다운로드한 SCENE App 설치 파일을 찾을 수 없습니다.")
    try:
        with path.open("rb") as source:
            if source.read(2) != b"MZ":
                raise UpdateError("Windows 설치 파일이 아닙니다.")
        return subprocess.Popen([str(path), "/SP-", "/NORESTART", "/CLOSEAPPLICATIONS"],
                                cwd=str(path.parent), close_fds=True)
    except OSError as exc:
        raise UpdateError(f"설치 프로그램을 실행하지 못했습니다.\n{exc}") from exc
