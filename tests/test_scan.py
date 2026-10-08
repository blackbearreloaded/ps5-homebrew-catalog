import io
import stat
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from catalog import scan

try:
    import yara  # noqa: F401
    HAVE_YARA = True
except ImportError:
    HAVE_YARA = False
try:
    import capstone  # noqa: F401
    HAVE_CAPSTONE = True
except ImportError:
    HAVE_CAPSTONE = False

TITLE = "PPSA01234"
NOPS = b"\x90" * 32


def title_elf(imports=("printf",), code=NOPS, extra=b"", elf_type=scan.ET_SCE_DYNEXEC) -> bytes:
    """A small executable laid out like a PS5 title's: one loaded segment, imports named by NID."""
    strings = b"\0libkernel\0"
    offsets = []
    for name in imports:
        offsets.append(len(strings))
        strings += f"{scan.nid(name)}#A#B\0".encode()
    symbols = b"".join(struct.pack("<IBBHQQ", o, 0x12, 0, 0, 0, 0) for o in offsets)
    header_size = 64 + 2 * 56
    code_at = header_size
    strings_at = code_at + len(code)
    symbols_at = strings_at + len(strings)
    dynamic_at = symbols_at + len(symbols)
    dynamic = b"".join(struct.pack("<qQ", tag, value) for tag, value in (
        (5, strings_at), (6, symbols_at), (scan.DT_SCE_IMPORT_LIB, 1), (scan.DT_SCE_SYMTABSZ, len(symbols)), (0, 0)))
    size = dynamic_at + len(dynamic) + len(extra)
    ident = b"\x7fELF\x02\x01\x01" + b"\0" * 9
    head = ident + struct.pack("<HHIQQQIHHHHHH", elf_type, 0x3E, 1, code_at, 64, 0, 0, 64, 56, 2, 0, 0, 0)
    load = struct.pack("<IIQQQQQQ", 1, 5, 0, 0, 0, size, size, 0x4000)
    dyn = struct.pack("<IIQQQQQQ", 2, 6, dynamic_at, dynamic_at, 0, len(dynamic), len(dynamic), 8)
    return head + load + dyn + code + strings + symbols + dynamic + extra


def signed(elf: bytes) -> bytes:
    """Wrap an ELF the way a title's eboot.bin is: a header, one data entry per loaded segment."""
    head = 64 + 2 * 56
    entries = struct.pack("<4Q", (1 << 11) | (0 << 20), 0x20 + 0x20 + head, len(elf), len(elf))
    return scan.SELF_MAGICS[0] + b"\0" * 20 + struct.pack("<H", 1) + b"\0" * 6 + entries + elf[:head] + elf


def payload_elf() -> bytes:
    ident = b"\x7fELF\x02\x01\x01" + b"\0" * 9
    head = ident + struct.pack("<HHIQQQIHHHHHH", 3, 0x3E, 1, 0, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    body = b"libkernel_web.sprx\0KERNEL_ADDRESS_ALLPROC\0kernel_copyin\0kernel_set_ucred_authid\0"
    size = 64 + 56 + len(body)
    return head + struct.pack("<IIQQQQQQ", 1, 5, 0, 0, 0, size, size, 0x4000) + body


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def archive(self, files: dict, links=()) -> Path:
        path = Path(self.tmp.name) / "app.zip"
        with zipfile.ZipFile(path, "w") as z:
            for name, data in files.items():
                z.writestr(name, data)
            for name in links:
                info = zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(info, "/data")
        return path

    def app(self, eboot: bytes, **more) -> scan.Scan:
        files = {f"{TITLE}/eboot.bin": eboot, f"{TITLE}/sce_sys/param.json": "{}"}
        files.update({f"{TITLE}/{name}": data for name, data in more.items()})
        return scan.scan_archive(self.archive(files), TITLE)

    def test_nid_matches_known_identifiers(self):
        self.assertEqual(scan.nid("printf"), "hcuQgD53UxM")
        self.assertEqual(scan.nid("sceKernelLoadStartModule"), "wzvqT4UqKX8")

    def test_signed_executable_is_unwrapped_and_its_imports_read(self):
        elf = title_elf(imports=("printf", "connect", "mprotect", "sceKernelLoadStartModule"))
        self.assertEqual(scan.unwrap_self(signed(elf)), elf)
        result = self.app(signed(elf))
        info = result.executables[0]
        self.assertEqual((info.role, info.imports, info.libraries), ("title executable", 4, ["libkernel"]))
        self.assertEqual(info.watched, {"network": ["connect"], "makes memory executable": ["mprotect"],
                                        "loads code at run time": ["sceKernelLoadStartModule"]})
        self.assertFalse(result.elevates)
        self.assertFalse(result.failed)
        text = scan.markdown(result, "Test")
        self.assertIn("No sign that this app leaves the sandbox", text)
        self.assertIn("`connect`", text)

    def test_encrypted_or_damaged_executables_are_reported_not_trusted(self):
        elf = title_elf()
        head = 64 + 2 * 56
        encrypted = bytearray(signed(elf))
        struct.pack_into("<Q", encrypted, 0x20, (1 << 11) | (1 << 1))
        result = self.app(bytes(encrypted))
        self.assertTrue(any("could not be read" in text for _, text in result.findings))
        self.assertTrue(any("could not be read" in t for _, t in self.app(scan.SELF_MAGICS[0] + b"\1" * 40).findings))
        self.assertEqual(len(elf[:head]), head)

    def test_a_payload_in_the_archive_means_the_app_can_leave_the_sandbox(self):
        result = self.app(signed(title_elf()), **{"helper.elf": payload_elf()})
        self.assertTrue(result.elevates)
        self.assertEqual([x.role for x in result.executables], ["title executable", "payload"])
        self.assertTrue(any(level == "warning" and "is a payload" in text for level, text in result.findings))
        self.assertIn("can leave the sandbox", scan.markdown(result, "Test"))
        # A plain library the app loads itself (an emulator core) is not a payload.
        library = payload_elf().replace(b"libkernel_web.sprx\0", b"libretro_core.so\0\0\0").replace(b"KERNEL", b"kernal")
        library = library.replace(b"kernel_", b"kernal_")
        result = self.app(signed(title_elf()), **{"cores/x.so": library})
        self.assertFalse(result.elevates)
        self.assertEqual(result.executables[1].role, "library")

    def test_helpers_are_checked_against_the_approved_list(self):
        import hashlib
        import json
        result = self.app(signed(title_elf()), **{"helper.elf": payload_elf()})
        digest = hashlib.sha256(payload_elf()).hexdigest()
        self.assertEqual(scan.check_helpers(result, {}), 1)
        self.assertTrue(any(level == "warning" and "NOT on the approved helper list" in text and digest in text
                            for level, text in result.findings))
        listed = Path(self.tmp.name) / "approved.json"
        listed.write_text(json.dumps({"helpers": [{"sha256": digest, "name": "Test helper"}, {"sha256": "nope"}]}))
        approved = scan.load_approved(listed)
        self.assertEqual(list(approved), [digest])
        again = self.app(signed(title_elf()), **{"helper.elf": payload_elf()})
        self.assertEqual(scan.check_helpers(again, approved), 0)
        self.assertTrue(any(level == "notice" and "Test helper" in text for level, text in again.findings))
        self.assertEqual(scan.load_approved(Path(self.tmp.name) / "missing.json"), {})
        # The list in the repository is well formed.
        self.assertTrue(all(len(k) == 64 for k in scan.load_approved()))

    def test_comparison_with_the_listed_release(self):
        old = self.app(signed(title_elf(imports=("printf",))))
        new = self.app(signed(title_elf(imports=("printf", "connect"), extra=b"\x00https://evil.example/x\x00")),
                       **{"helper.elf": payload_elf()})
        lines = scan.compare(old, new)
        text = "\n".join(lines)
        self.assertIn("**Verdict changed:**", text)
        self.assertIn("**New way out of the sandbox:** payload", text)
        self.assertIn("New payload: `" + TITLE + "/helper.elf`", text)
        self.assertIn("now imports (network): `connect`", text)
        self.assertIn("names new hosts: `evil.example`", text)
        self.assertEqual(scan.compare(old, old), [])
        new.compared_with, new.comparison = "the listed release, 1.0", lines
        self.assertIn("### Changes since the listed release, 1.0", scan.markdown(new, "Test"))

    def test_summary_round_trip_and_distrust(self):
        result = self.app(signed(title_elf(imports=("connect",))), **{"helper.elf": payload_elf()})
        result.attested, result.workflow = True, "owner/repo/.github/workflows/release.yml@refs/tags/v1"
        data = scan.summary(result)
        self.assertEqual((data["sandbox"], data["routes"], data["network"], len(data["payloads"])),
                         ("leaves", ["payload"], True, 1))
        self.assertEqual(scan.read_summary(data, result.sha256), data)
        for change in ({"sandbox": "safe"}, {"scanner": 0}, {"routes": ["magic"]}, {"network": "yes"},
                       {"payloads": [{"sha256": "<script>"}]}, {"attested": "true"}):
            self.assertIsNone(scan.read_summary({**data, **change}, result.sha256), change)
        self.assertIsNone(scan.read_summary(data, "0" * 64))
        self.assertIsNone(scan.read_summary({**data, "workflow": "<b>x</b>"}, result.sha256)["workflow"])

    def test_attestation_is_not_claimed_when_it_cannot_be_checked(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"GH_TOKEN": "", "GITHUB_TOKEN": ""}):
            self.assertIsNone(scan.attested_build(Path(self.tmp.name) / "x.zip", "owner/repo")[0])

    def test_unsafe_archives_fail(self):
        for files, links in (({"../outside.txt": "x"}, ()), ({f"{TITLE}/a": "x"}, (f"{TITLE}/link",)),
                             ({"/abs.txt": "x"}, ())):
            result = scan.scan_archive(self.archive(files, links), TITLE)
            self.assertTrue(result.failed, files)
            self.assertEqual(result.executables, [])
        not_zip = Path(self.tmp.name) / "bad.zip"
        not_zip.write_bytes(b"not a zip")
        self.assertTrue(scan.scan_archive(not_zip, TITLE).failed)

    def test_layout_and_foreign_files_are_described(self):
        files = {f"wrap/{TITLE}/eboot.bin": signed(title_elf()), f"wrap/{TITLE}/sce_sys/param.json": "{}",
                 "wrap/setup.exe": b"MZ" + b"\0" * 64, "wrap/tool.sh": b"#!/bin/sh\n", "wrap/app.ffpfsc": b"image"}
        result = scan.scan_archive(self.archive(files), TITLE)
        self.assertFalse(result.failed)
        found = {level + ": " + text for level, text in result.findings}
        self.assertTrue(any(f.startswith("warning: 1 windows program file(s)") for f in found), found)
        self.assertTrue(any(f.startswith("notice: 1 script file(s)") for f in found))
        self.assertTrue(any("`wrap/" + TITLE + "/`" in f for f in found))
        self.assertTrue(any("can't look inside" in f for f in found))
        missing = scan.scan_archive(self.archive({"readme.txt": "x"}), TITLE)
        self.assertTrue(any("eboot.bin" in text for _, text in missing.findings))

    def test_sha256_mismatch_is_said(self):
        result = scan.scan_archive(self.archive({f"{TITLE}/eboot.bin": signed(title_elf())}), TITLE, "0" * 64)
        self.assertTrue(any("sha256" in text for _, text in result.findings))

    @unittest.skipUnless(HAVE_YARA, "yara-python is not installed")
    def test_loader_address_and_request_file_are_found(self):
        loader = b"\x10\x02\x23\x3d\x7f\x00\x00\x01"
        result = self.app(signed(title_elf(extra=b"\0" * 8 + loader)))
        self.assertTrue(result.elevates)
        self.assertTrue(any("loader's address" in text for _, text in result.findings))
        result = self.app(signed(title_elf(extra=b"\0/download0/elevate_proc\0")))
        self.assertTrue(result.elevates)
        self.assertTrue(any("resident jailbreak service" in text for _, text in result.findings))
        # A payload's own contents are one line of detail under the payload finding.
        result = self.app(signed(title_elf()), **{"helper.elf": payload_elf()})
        self.assertTrue(any(level == "notice" and "as a payload" in text and "kernel read/write" in text
                            for level, text in result.findings))

    @unittest.skipUnless(HAVE_CAPSTONE, "capstone is not installed")
    def test_system_calls_made_by_the_title_itself_are_counted(self):
        ptrace = NOPS + b"\xb8\x1a\x00\x00\x00\x49\x89\xca\x0f\x05" + NOPS       # mov eax, 26; mov r10, rcx; syscall
        result = self.app(signed(title_elf(code=ptrace)))
        self.assertEqual(result.executables[0].syscalls, {26: 1})
        self.assertTrue(any(level == "warning" and "ptrace" in text for level, text in result.findings))
        # The loader's port as a bare constant is weak evidence: the verdict says unclear, not elevated.
        port = NOPS + b"\xb8\x3d\x23\x00\x00" + NOPS                      # mov eax, 9021
        result = self.app(signed(title_elf(imports=("connect",), code=port, extra=b"\x00" + b"127.0.0.1\x00")))
        self.assertEqual((result.elevates, result.unclear), (False, True))
        self.assertIn("unclear", scan.markdown(result, "Test"))
        self.assertFalse(self.app(signed(title_elf(imports=("connect",), code=port))).unclear)
        # The same two bytes inside another instruction are not a system call.
        self.assertEqual(self.app(signed(title_elf(code=NOPS + b"\xb8\x0f\x05\x00\x00" + NOPS))).executables[0].syscalls, {})


if __name__ == "__main__":
    unittest.main()
