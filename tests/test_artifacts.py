import http.server
import io
import threading
import unittest
import zipfile
from unittest import mock

from catalog import artifacts
from catalog.artifacts import DownloadError, inspect_icon, read_zip_member


def serve(body: bytes, ranges: bool = True):
    """A local server for `body`; returns (url, stop)."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            header = self.headers.get("Range")
            if header and ranges:
                start, end = (int(v) for v in header.removeprefix("bytes=").split("-"))
                end = min(end, len(body) - 1)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
                chunk = body[start:end + 1]
            else:
                self.send_response(200)
                chunk = body
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}/a.zip", server.shutdown


class RemoteZipTests(unittest.TestCase):
    def setUp(self):
        # _open insists on HTTPS; the local server speaks plain HTTP.
        def local(url, headers=None):
            request = artifacts.urllib.request.Request(url, headers={**(headers or {})})
            return artifacts.urllib.request.urlopen(request, timeout=5)
        patch = mock.patch.object(artifacts, "_open", local)
        patch.start()
        self.addCleanup(patch.stop)

    def archive(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("T/eboot.bin", b"x" * 300000)
            z.writestr("T/sce_sys/param.json", '{"titleId": "PPSA01234"}')
            z.writestr("T/vendor/sce_sys/param.json", "{}")
        return buffer.getvalue()

    def test_reads_one_member_with_ranges_and_prefers_the_shallowest(self):
        url, stop = serve(self.archive())
        self.addCleanup(stop)
        self.assertEqual(read_zip_member(url, "sce_sys/param.json", 1000),
                         ("T/sce_sys/param.json", b'{"titleId": "PPSA01234"}'))
        self.assertIsNone(read_zip_member(url, "sce_sys/nothing.json", 1000))

    def test_refuses_a_server_without_ranges_and_a_member_over_the_limit(self):
        url, stop = serve(self.archive(), ranges=False)
        self.addCleanup(stop)
        with self.assertRaises(DownloadError):
            read_zip_member(url, "sce_sys/param.json", 1000)
        url, stop = serve(self.archive())
        self.addCleanup(stop)
        with self.assertRaises(DownloadError):
            read_zip_member(url, "sce_sys/param.json", 5)


class IconTests(unittest.TestCase):
    def png(self, width, height):
        return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big")

    def test_formats(self):
        self.assertEqual(inspect_icon(self.png(512, 512)), ("png", []))
        self.assertEqual(inspect_icon(b"\xff\xd8\xff\xe0rest")[0], "jpeg")
        self.assertEqual(inspect_icon(b"RIFF\x00\x00\x00\x00WEBPVP8 ")[0], "webp")
        self.assertIsNone(inspect_icon(b"GIF89a")[0])

    def test_shape_warnings(self):
        self.assertIn("square", inspect_icon(self.png(512, 256))[1][0])
        self.assertIn("at least 256x256", inspect_icon(self.png(128, 128))[1][0])


if __name__ == "__main__":
    unittest.main()
