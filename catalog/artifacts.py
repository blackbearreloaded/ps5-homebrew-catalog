"""Fetch icons with hard limits, and inspect them. Artifacts are never downloaded whole:
one file inside a ZIP is read with HTTP range requests (a few kilobytes of the archive)."""

from __future__ import annotations

import io
import urllib.error
import urllib.request
import zipfile

from .github import USER_AGENT

MAX_ARTIFACT_BYTES = 2 << 30          # GitHub's per-asset limit
MAX_ICON_BYTES = 2 << 20
TIMEOUT = 60
MAX_RANGE_BYTES = 8 << 20             # most a ranged read of one archive may fetch in all
RANGE_CHUNK = 1 << 16


class DownloadError(RuntimeError):
    pass


def _open(url: str, headers: dict | None = None):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        response = urllib.request.urlopen(request, timeout=TIMEOUT)
    except urllib.error.HTTPError as error:
        raise DownloadError(f"HTTP {error.code} from {url}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise DownloadError(f"could not download {url}: {error}") from error
    if not response.geturl().startswith("https://"):
        response.close()
        raise DownloadError(f"{url} redirected to a non-HTTPS location")
    return response


def fetch_small(url: str, max_bytes: int) -> bytes:
    with _open(url) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise DownloadError(f"{url} is larger than {max_bytes} bytes")
    return data


class _RemoteFile(io.RawIOBase):
    """A read-only, seekable view of a remote file, fetched in ranges as it is read."""

    def __init__(self, url: str):
        self.url, self.position, self.fetched = url, 0, 0
        self.window_start, self.window = 0, b""
        self.size = 0
        self._fetch(0, 0)

    def _fetch(self, start: int, end: int) -> bytes:
        """Bytes start..end inclusive; the server must honour the range."""
        self.fetched += end - start + 1
        if self.fetched > MAX_RANGE_BYTES:
            raise DownloadError(f"{self.url}: reading it needs more than {MAX_RANGE_BYTES} bytes")
        with _open(self.url, {"Range": f"bytes={start}-{end}"}) as response:
            total = (response.headers.get("Content-Range") or "").rpartition("/")[2]
            if response.status != 206 or not total.isdigit():
                raise DownloadError(f"{self.url} does not serve byte ranges")
            self.size = int(total)
            return response.read(end - start + 1)

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.position, io.SEEK_END: self.size}[whence]
        self.position = max(0, base + offset)
        return self.position

    def readinto(self, buffer):
        end = min(self.position + len(buffer), self.size)
        if end <= self.position:
            return 0
        if not self.window_start <= self.position or end > self.window_start + len(self.window):
            self.window_start = self.position
            self.window = self._fetch(self.position, min(max(end, self.position + RANGE_CHUNK), self.size) - 1)
        data = self.window[self.position - self.window_start:end - self.window_start]
        buffer[:len(data)] = data
        self.position += len(data)
        return len(data)


def read_zip_member(url: str, suffix: str, max_bytes: int) -> tuple[str, bytes] | None:
    """(path, content) of the file in a remote ZIP whose path is `suffix` (nearest the top first), or None.

    Only the ZIP's directory and that one file are fetched, never the whole archive."""
    try:
        with zipfile.ZipFile(_RemoteFile(url)) as archive:
            found = sorted((m for m in archive.infolist() if not m.is_dir() and not m.flag_bits & 1
                            and (m.filename == suffix or m.filename.endswith("/" + suffix))),
                           key=lambda m: (m.filename.count("/"), m.filename))
            if not found:
                return None
            with archive.open(found[0]) as handle:
                data = handle.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise DownloadError(f"{found[0].filename} in {url} is larger than {max_bytes} bytes")
            return found[0].filename, data
    except (zipfile.BadZipFile, NotImplementedError, OSError, EOFError, RuntimeError) as error:
        raise DownloadError(f"{url} is not a readable ZIP archive: {error}") from error


def inspect_icon(data: bytes) -> tuple[str | None, list[str]]:
    """Return (format, warnings) for image bytes; format None means not an accepted image."""
    warnings = []
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        if width != height:
            warnings.append(f"icon is {width}x{height}; a square image is recommended")
        elif width < 256:
            warnings.append(f"icon is {width}x{height}; at least 256x256 is recommended")
        return "png", warnings
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg", warnings
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", warnings
    return None, warnings
