"""Static scan of a release archive: what the app's code is able to do.

The question is whether an app can leave the PS5's sandbox, and how. A title
that stays inside can crash itself; one that reaches the payload loader, or
ships a payload of its own, can reach the kernel. So the scan reports facts a
reviewer can act on:

- the archive: one <TITLEID> folder, no path tricks, no programs for a PC;
- the executable: what it imports from the system (PS5 executables name their
  imports by a hash, the NID, so names are matched by hashing a watch list),
  whether it holds the loader's address, makes system calls of its own, or
  embeds another executable;
- every payload file in the archive, and what the rules in scan_rules.yar find.

Nothing from the archive is ever run. The scan proves nothing is absent: code
can hide from every check here. It makes a careless or lazy attack visible and
gives a reviewer the same facts for every release.

The three libraries (pyelftools, capstone, yara-python; requirements-scan.txt)
are used only here. Without one of them its part of the scan is skipped and the
report says so; the catalog's other checks need none of them.
"""

from __future__ import annotations

import base64
import hashlib
import math
import re
import stat
import struct
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

RULES = Path(__file__).with_name("scan_rules.yar")
APPROVED_HELPERS = Path(__file__).resolve().parents[1] / "helpers" / "approved.json"
SCANNER = 2             # raised when what a scan records changes, so kept summaries are made again
SANDBOX = ("stays", "leaves", "unclear", "unreadable")
ROUTES = ("loader", "service", "payload")

MAX_ARCHIVE_BYTES = 2 << 30          # as for a release asset
MAX_UNPACKED_BYTES = 8 << 30
MAX_ENTRIES = 50000
MAX_FILE_SCAN = 512 << 20            # a single file larger than this is listed, not read
MAX_LISTED = 12                      # examples shown per finding

SELF_MAGICS = (b"\x4f\x15\x3d\x1d", b"\x54\x14\xf5\xee")
NID_SALT = bytes.fromhex("518D64A635DED8C1E6B039B1C3E55230")
ET_SCE_DYNEXEC, ET_SCE_DYNAMIC = 0xFE10, 0xFE18
DT_SCE_IMPORT_LIB, DT_SCE_SYMTABSZ = 0x61000049, 0x6100003F
LOADER_PORTS = (9021, 9020)
NID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-"

# System functions worth knowing about, by what they let an app do.
WATCH = {
    "network": ("socket", "connect", "bind", "listen", "accept", "send", "sendto", "recvfrom", "getaddrinfo",
                "sceNetSocket", "sceNetConnect", "sceNetBind", "sceNetListen", "sceNetAccept", "sceNetSend",
                "sceHttpSendRequest", "sceHttp2SendRequest"),
    "loads code at run time": ("dlopen", "dlsym", "sceKernelLoadStartModule", "sceKernelDlsym",
                               "sceSysmoduleLoadModuleInternal", "sceSysmoduleLoadModuleByNameInternal"),
    "makes memory executable": ("mprotect", "sceKernelMprotect", "sceKernelJitCreateSharedMemory",
                                "sceKernelJitCreateAliasOfSharedMemory", "sceKernelJitMapSharedMemory"),
    "starts or controls processes": ("fork", "vfork", "execve", "posix_spawn", "ptrace", "kill", "syscall",
                                     "sceSystemServiceLoadExec", "sceLncUtilLaunchApp", "sceSystemServiceLaunchApp"),
    "system state": ("mount", "nmount", "unmount", "reboot", "sysctl", "sysctlbyname", "setuid", "setgid", "chroot",
                     "ioctl", "sceKernelReboot", "sceRegMgrSetInt", "sceRegMgrSetStr", "sceRegMgrSetBin"),
    "installs or removes titles": ("sceAppInstUtilAppInstallPkg", "sceAppInstUtilAppUnInstall",
                                   "sceAppInstUtilInstallByPackage", "sceBgftServiceIntDownloadRegisterTask"),
    "accounts": ("sceNpAuthGetAuthorizationCode", "sceNpGetAccountIdA", "sceNpGetOnlineId",
                 "sceUserServiceGetNpAccountId", "sceNpWebApiSendRequest"),
}
# FreeBSD system call numbers that a title has no ordinary reason to make itself.
STUB_TABLE = 100        # this many different system calls in one executable is a linked stub table
SENSITIVE_SYSCALLS = {21: "mount", 22: "unmount", 26: "ptrace", 55: "reboot", 59: "execve", 378: "nmount", 61: "chroot"}


class ScanError(Exception):
    pass


def nid(name: str) -> str:
    """The identifier a PS5 executable imports `name` by."""
    digest = hashlib.sha1(name.encode() + NID_SALT).digest()
    return base64.b64encode(digest[:8][::-1], b"+-").decode().rstrip("=")


WATCH_NIDS = {nid(name): (group, name) for group, names in WATCH.items() for name in names}


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    total = len(data)
    return -sum(n / total * math.log2(n / total) for n in Counter(data).values())


def unwrap_self(data: bytes) -> bytes:
    """The ELF image inside a signed PS4/PS5 executable (or the data itself when it is a plain ELF)."""
    if data[:4] == b"\x7fELF":
        return data
    if data[:4] not in SELF_MAGICS:
        raise ScanError("not a signed executable or an ELF file")
    try:
        count = struct.unpack_from("<H", data, 0x18)[0]
        entries = [struct.unpack_from("<4Q", data, 0x20 + i * 0x20) for i in range(count)]
        start = 0x20 + count * 0x20
        if data[start:start + 4] != b"\x7fELF":
            raise ScanError("no ELF header after the segment table")
        phoff = struct.unpack_from("<Q", data, start + 32)[0]
        phentsize, phnum = struct.unpack_from("<HH", data, start + 54)
        headers = [struct.unpack_from("<IIQQQQQQ", data, start + phoff + i * phentsize) for i in range(phnum)]
        size = max((h[2] + h[5] for h in headers), default=0)
        if not 0 < size <= MAX_FILE_SCAN * 2:
            raise ScanError("implausible image size")
        image = bytearray(size)
        head = phoff + phnum * phentsize
        image[:head] = data[start:start + head]
        for props, offset, filesz, _memsz in entries:
            if not (props >> 11) & 1:          # not a data entry (its digests)
                continue
            if (props >> 1) & 1 or (props >> 3) & 1:
                raise ScanError("the executable is encrypted or compressed, so it can't be read")
            index = (props >> 20) & 0xFFFF
            if index >= len(headers) or offset + filesz > len(data):
                raise ScanError("a segment points outside the file")
            target = headers[index][2]
            image[target:target + filesz] = data[offset:offset + filesz]
        return bytes(image)
    except (struct.error, IndexError, ValueError) as error:
        raise ScanError(f"damaged executable header: {error}") from error


def file_kind(head: bytes) -> str:
    """What a file is, from its first bytes."""
    if head[:4] == b"\x7fELF":
        return "elf"
    if head[:4] in SELF_MAGICS:
        return "self"
    if head[:2] == b"MZ":
        return "windows program"
    if head[:4] in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe"):
        return "macOS program"
    if head[:2] == b"#!":
        return "script"
    if head[:4] == b"PK\x03\x04":
        return "zip"
    if head[:4] == b"\x4c\x00\x00\x00":
        return "windows shortcut"
    return "other"


@dataclass
class Executable:
    path: str
    role: str                       # "title executable", "module", "payload" or "library"
    sha256: str
    size: int
    libraries: list[str] = field(default_factory=list)
    watched: dict[str, list[str]] = field(default_factory=dict)      # group -> function names
    imports: int = 0
    rules: list[tuple[str, str, str, list[str]]] = field(default_factory=list)   # rule, level, says, examples
    loader: list[str] = field(default_factory=list)                  # evidence that it reaches the payload loader
    maybe: list[str] = field(default_factory=list)                   # weaker evidence of the same
    routes: set[str] = field(default_factory=set)                    # "loader", "service"
    hosts: list[str] = field(default_factory=list)                   # hosts named in URLs inside it
    syscalls: dict[int, int] = field(default_factory=dict)           # number -> count (-1: number unknown)
    embedded: list[int] = field(default_factory=list)                # offsets of other executables inside
    entropy: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass
class Scan:
    titleid: str
    findings: list[tuple[str, str]] = field(default_factory=list)    # (level, text)
    entries: int = 0
    unpacked: int = 0
    kinds: Counter = field(default_factory=Counter)
    executables: list[Executable] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)                 # parts of the scan that could not run
    sha256: str = ""
    attested: bool | None = None                                     # a verified build attestation; None: not checked
    workflow: str | None = None                                      # the workflow that built it, when attested
    comparison: list[str] = field(default_factory=list)              # what changed since the listed release
    downloaded: bool = True
    compared_with: str = ""

    def add(self, level: str, text: str) -> None:
        if (level, text) not in self.findings:
            self.findings.append((level, text))

    @property
    def elevates(self) -> bool:
        return any(x.role == "payload" or x.loader for x in self.executables)

    @property
    def sandbox(self) -> str:
        """One word for the verdict, as the API publishes it."""
        return "unreadable" if self.failed or not self.downloaded else "leaves" if self.elevates else "unclear" if self.unclear else "stays"

    @property
    def payloads(self) -> list[Executable]:
        return [x for x in self.executables if x.role == "payload"]

    @property
    def routes(self) -> list[str]:
        found = {route for x in self.executables for route in x.routes}
        if self.payloads:
            found.add("payload")
        return [route for route in ROUTES if route in found]

    @property
    def unclear(self) -> bool:
        """Something points at the loader, but not firmly enough to say the app uses it."""
        return not self.elevates and any(x.maybe for x in self.executables)

    @property
    def verdict(self) -> str:
        if not self.downloaded:
            return "the archive could not be downloaded, so nothing was scanned"
        if self.failed:
            return "the archive is unsafe to unpack or could not be read"
        if self.elevates:
            return "this app can leave the sandbox"
        if self.unclear:
            return "it is unclear whether this app leaves the sandbox"
        return "no sign that this app leaves the sandbox"

    @property
    def failed(self) -> bool:
        return any(level == "error" for level, _ in self.findings)


def fetch_archive(url: str, target: Path) -> None:
    """Download a release archive to `target`, refusing one larger than a release asset can be."""
    from . import artifacts
    received = 0
    with artifacts._open(url) as response, target.open("wb") as out:
        for block in iter(lambda: response.read(1 << 20), b""):
            received += len(block)
            if received > MAX_ARCHIVE_BYTES:
                raise artifacts.DownloadError(f"{url} is larger than {MAX_ARCHIVE_BYTES} bytes")
            out.write(block)


def scan_release(data: dict, workdir: Path, attest: bool = False) -> Scan:
    """Download and scan the archive a record's data points to; with `attest`, ask for its build attestation."""
    from . import artifacts
    target = workdir / f"{data['titleid']}.zip"
    try:
        fetch_archive(data["artifact_url"], target)
    except (artifacts.DownloadError, OSError) as error:
        scan = Scan(data["titleid"], downloaded=False)
        scan.add("warning", f"the archive could not be downloaded, so nothing was scanned: {error}")
        return scan
    try:
        scan = scan_archive(target, data["titleid"], data["sha256"])
        if attest and not scan.failed:
            repository = data["source_repo"].removeprefix("https://github.com/")
            scan.attested, scan.workflow, note = attested_build(target, repository)
            if scan.attested is None:
                scan.skipped.append(note)
        return scan
    finally:
        target.unlink(missing_ok=True)


def _libraries():
    """(pyelftools, capstone, yara) as available; None for a missing one."""
    found = []
    for name in ("elftools.elf.elffile", "capstone", "yara"):
        try:
            found.append(__import__(name, fromlist=["x"]))
        except ImportError:
            found.append(None)
    return found


def _segments(image: bytes) -> list[tuple]:
    phoff = struct.unpack_from("<Q", image, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", image, 54)
    return [struct.unpack_from("<IIQQQQQQ", image, phoff + i * phentsize) for i in range(min(phnum, 256))]


def _sce_imports(image: bytes, info: Executable) -> None:
    """Libraries and watched functions of a title executable or module, from its dynamic section."""
    segments = _segments(image)

    def at(address: int) -> int | None:
        for kind, _flags, offset, vaddr, _paddr, filesz, _memsz, _align in segments:
            if kind == 1 and vaddr <= address < vaddr + filesz:
                return address - vaddr + offset
        return None

    dynamic = next((s for s in segments if s[0] == 2), None)
    if dynamic is None:
        info.notes.append("no dynamic section: imports unknown")
        return
    tags: dict[int, list[int]] = {}
    for i in range(min(dynamic[5] // 16, 4096)):
        tag, value = struct.unpack_from("<qQ", image, dynamic[2] + i * 16)
        tags.setdefault(tag, []).append(value)
    strtab, symtab = at(tags.get(5, [0])[0]), at(tags.get(6, [0])[0])
    if strtab is None or symtab is None:
        info.notes.append("no symbol table: imports unknown")
        return

    def text(offset: int) -> str:
        end = image.find(b"\0", strtab + offset, strtab + offset + 256)
        return image[strtab + offset:end if end >= 0 else strtab + offset].decode("latin-1")

    libraries = {value >> 48: text(value & 0xFFFFFFFF) for value in tags.get(DT_SCE_IMPORT_LIB, [])}
    info.libraries = sorted(set(libraries.values()))
    size = tags.get(DT_SCE_SYMTABSZ, [0])[0]
    watched: dict[str, set[str]] = {}
    for i in range(min(size // 24, 200000)):
        name_offset, _info, _other, shndx = struct.unpack_from("<IBBH", image, symtab + i * 24)
        name = text(name_offset)
        if shndx != 0 or name.count("#") != 2:
            continue
        info.imports += 1
        hit = WATCH_NIDS.get(name.split("#")[0])
        if hit:
            watched.setdefault(hit[0], set()).add(hit[1])
    info.watched = {group: sorted(names) for group, names in watched.items()}


def _payload_imports(elffile_module, image: bytes, info: Executable) -> None:
    """A payload names its imports in plain text."""
    import io
    elf = elffile_module.ELFFile(io.BytesIO(image))
    wanted = {name: group for group, names in WATCH.items() for name in names}
    watched: dict[str, set[str]] = {}
    for segment in elf.iter_segments():
        if segment.header.p_type != "PT_DYNAMIC":
            continue
        for tag in segment.iter_tags():
            if tag.entry.d_tag == "DT_NEEDED":
                info.libraries.append(tag.needed)
        for symbol in segment.iter_symbols():
            if symbol.entry.st_shndx == "SHN_UNDEF" and symbol.name:
                info.imports += 1
                if symbol.name in wanted:
                    watched.setdefault(wanted[symbol.name], set()).add(symbol.name)
    info.watched = {group: sorted(names) for group, names in watched.items()}


def _has_soname(image: bytes) -> bool:
    """Whether a plain ELF names itself as a shared library (DT_SONAME)."""
    try:
        dynamic = next((x for x in _segments(image) if x[0] == 2), None)
        if dynamic is None:
            return False
        return any(struct.unpack_from("<q", image, dynamic[2] + i * 16)[0] == 14
                   for i in range(min(dynamic[5] // 16, 4096)))
    except struct.error:
        return False


def _executable_ranges(image: bytes) -> list[tuple[int, int]]:
    return [(s[2], s[5]) for s in _segments(image) if s[0] == 1 and s[1] & 1 and s[2] + s[5] <= len(image)]


def _path_to(md, code: bytes, base: int, position: int):
    """Instructions on a decoding path that reaches `position` exactly: (earlier ones, the one there)."""
    for start in range(max(0, position - 24), max(0, position - 18)):
        earlier = []
        for instruction in md.disasm(code[start:position + 16], base + start):
            where = instruction.address - base
            if where == position:
                return earlier, instruction
            if where > position:
                break
            earlier.append(instruction)
    return None, None


def _covering(md, code: bytes, base: int, position: int):
    """The instruction whose bytes include `position`, on a path started well before it."""
    for start in range(max(0, position - 24), max(0, position - 20)):
        for instruction in md.disasm(code[start:position + 16], base + start):
            where = instruction.address - base
            if where <= position < where + instruction.size:
                return instruction
            if where > position:
                break
    return None


def _code_facts(capstone, image: bytes, info: Executable, count_syscalls: bool) -> None:
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    immediate = capstone.x86.X86_OP_IMM
    register = capstone.x86.X86_OP_REG
    ports, addresses = Counter(), 0
    for offset, size in _executable_ranges(image):
        code = image[offset:offset + size]
        if count_syscalls:
            for match in re.finditer(rb"\x0f\x05", code):
                earlier, instruction = _path_to(md, code, offset, match.start())
                if instruction is None or instruction.mnemonic != "syscall":
                    continue
                number, stub = None, False
                for previous in earlier[-4:]:
                    operands = previous.operands
                    if previous.mnemonic == "mov" and len(operands) == 2 and operands[0].type == register:
                        target = previous.reg_name(operands[0].reg)
                        if target in ("eax", "rax") and operands[1].type == immediate:
                            number = operands[1].imm & 0xFFFFFFFF
                        if target == "r10" and operands[1].type == register:
                            stub = True
                if number is not None or stub:
                    key = number if number is not None and number < 1024 else -1
                    info.syscalls[key] = info.syscalls.get(key, 0) + 1
        for port in LOADER_PORTS:
            host, network = struct.pack("<H", port), struct.pack(">H", port)
            for match in re.finditer(re.escape(host) + b"|" + re.escape(network), code):
                instruction = _covering(md, code, offset, match.start())
                if instruction is None:
                    continue
                for operand in instruction.operands:
                    if operand.type != immediate:
                        continue
                    value = operand.imm & 0xFFFFFFFF
                    swapped = struct.unpack("<H", network)[0]
                    if value >> 16 == swapped and (value >> 8) & 0xFF == 2:     # the start of a socket address
                        addresses += 1
                    elif value in (port, swapped) and instruction.mnemonic in ("mov", "movabs", "push"):
                        ports[port] += 1
    if addresses:
        info.routes.add("loader")
        info.loader.append(f"builds a socket address for the loader's port in code ({addresses} place(s))")
    loopback = b"127.0.0.1" in image
    connects = any(name in ("connect", "sceNetConnect") for names in info.watched.values() for name in names)
    for port, count in sorted(ports.items()):
        if loopback and connects:
            # A number alone can be anything; a library shared by several apps has one such constant.
            info.maybe.append(f"may connect to the payload loader: the constant {port} is in its code "
                              f"({count} place(s)), it names 127.0.0.1 and it can connect")
        else:
            info.notes.append(f"the constant {port} appears in code ({count} place(s)); by itself this means little")


def _apply_rules(compiled, data: bytes, info: Executable) -> None:
    for match in compiled.match(data=data):
        examples: list[str] = []
        for string in match.strings:
            for instance in string.instances:
                shown = instance.matched_data
                text = shown.decode("ascii") if all(32 <= b < 127 for b in shown) else shown.hex(" ")
                if text not in examples:
                    examples.append(text)
        info.rules.append((match.rule, match.meta.get("level", "notice"), match.meta.get("says", match.rule),
                           examples[:MAX_LISTED]))
        if match.rule == "loader_address_in_data":
            info.routes.add("loader")
            info.loader.append("holds the loader's address (127.0.0.1 and its port) as data")
        if match.rule == "elevation_request":
            info.routes.add("service")
            info.loader.append("asks a resident jailbreak service to lift its sandbox ("
                               + ", ".join(f"`{e}`" for e in examples[:3]) + ")")


def _embedded(data: bytes) -> list[int]:
    """Offsets of x86-64 ELF headers after the start of a file."""
    found = []
    for match in re.finditer(rb"\x7fELF\x02\x01\x01", data):
        at = match.start()
        if at and data[at + 18:at + 20] == b"\x3e\x00" and data[at + 16:at + 18] in (b"\x02\x00", b"\x03\x00",
                                                                                 b"\x10\xfe", b"\x18\xfe"):
            found.append(at)
    return found[:64]


def inspect_executable(path: str, data: bytes, scan: Scan, compiled=None) -> Executable | None:
    """Everything the scan can say about one executable file; None when it isn't one."""
    kind = file_kind(data[:8])
    if kind not in ("elf", "self"):
        return None
    info = Executable(path=path, role="module", sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    try:
        image = unwrap_self(data)
        if len(image) < 64 or image[4] != 2 or struct.unpack_from("<H", image, 18)[0] != 0x3E:
            raise ScanError("not a 64-bit x86 executable")
        elf_type = struct.unpack_from("<H", image, 16)[0]
    except ScanError as error:
        info.notes.append(f"could not be read: {error}")
        scan.add("warning", f"`{path}` could not be read as an executable: {error}")
        return info
    name = path.rsplit("/", 1)[-1].lower()
    if elf_type == ET_SCE_DYNEXEC:
        info.role = "title executable" if name == "eboot.bin" else "executable"
    elif elf_type == ET_SCE_DYNAMIC:
        info.role = "module"
    else:
        # A plain ELF. One built against the console's system libraries is a payload: what the
        # payload loader runs, outside the sandbox. Anything else is code the app loads itself
        # (an emulator core, a plug-in), which runs with the app's own rights. A library names
        # itself one; a payload carries the SDK's kernel routines in its start-up code.
        links = re.search(rb"libkernel(_web|_sys)?\.s?prx\0", image)
        kernel = re.search(rb"KERNEL_ADDRESS_|kernel_copyin|kernel_set_ucred", image)
        shared = name.endswith((".so", ".prx", ".sprx")) or _has_soname(image)
        info.role = "payload" if kernel or (links and not shared) else "library"
    elftools, capstone, _yara = _libraries()
    try:
        if info.role in ("payload", "library"):
            if elftools:
                _payload_imports(elftools, image, info)
        else:
            _sce_imports(image, info)
    except Exception as error:      # a damaged table must not stop the scan
        info.notes.append(f"imports could not be read: {type(error).__name__}")
    ranges = _executable_ranges(image)
    info.entropy = max((entropy(image[o:o + min(s, 4 << 20)]) for o, s in ranges), default=0.0)
    if info.entropy > 7.3:
        info.notes.append(f"its code has very high entropy ({info.entropy:.1f} of 8): packed or encrypted")
    info.embedded = _embedded(image)
    info.hosts = sorted({m.group(1).decode().lower().rstrip(".")
                         for m in re.finditer(rb"https?://([A-Za-z0-9][A-Za-z0-9.-]{2,80})", image)})[:200]
    if compiled is not None:
        _apply_rules(compiled, image, info)
        if info.role == "library" and any(rule == "payload_sdk_kernel_access" for rule, *_ in info.rules):
            info.role = "payload"
    if capstone:
        try:
            _code_facts(capstone, image, info, count_syscalls=info.role not in ("payload", "library"))
        except Exception as error:
            info.notes.append(f"code could not be examined: {type(error).__name__}")
    info.loader = list(dict.fromkeys(info.loader))
    return info


def scan_archive(path: Path, titleid: str, expected_sha256: str | None = None) -> Scan:
    """Scan a release archive on disk. Nothing in it is executed, and nothing is written."""
    scan = Scan(titleid)
    size = path.stat().st_size
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    scan.sha256 = digest.hexdigest()
    if expected_sha256 and scan.sha256 != expected_sha256:
        scan.add("warning", "the downloaded file's sha256 is not the record's; the scan describes the file as it is now")
    if size > MAX_ARCHIVE_BYTES:
        scan.add("error", "the archive is larger than a release asset can be")
        return scan
    elftools, capstone, yara = _libraries()
    for module, name, part in ((elftools, "pyelftools", "payload imports"), (capstone, "capstone", "code examination"),
                               (yara, "yara-python", "pattern rules")):
        if module is None:
            scan.skipped.append(f"{part} ({name} is not installed)")
    compiled = yara.compile(filepath=str(RULES)) if yara else None
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        scan.add("error", f"not a readable ZIP archive: {error}")
        return scan
    with archive:
        members = archive.infolist()
        scan.entries = len(members)
        scan.unpacked = sum(m.file_size for m in members)
        if scan.entries > MAX_ENTRIES or scan.unpacked > MAX_UNPACKED_BYTES:
            scan.add("error", f"the archive unpacks to {scan.entries} entries and {scan.unpacked:,} bytes, over the limit")
            return scan
        tops, unsafe = set(), []
        for member in members:
            name = member.filename
            parts = name.replace("\\", "/").split("/")
            if name.startswith(("/", "\\")) or ".." in parts or "\\" in name or (len(parts[0]) == 2 and parts[0][1] == ":"):
                unsafe.append(name)
            if stat.S_ISLNK(member.external_attr >> 16):
                unsafe.append(f"{name} (a link)")
            if member.flag_bits & 1:
                unsafe.append(f"{name} (encrypted)")
            tops.add(parts[0])
        if unsafe:
            scan.add("error", "the archive has entries that could be written outside the app's folder, or hidden: "
                     + ", ".join(f"`{n}`" for n in unsafe[:MAX_LISTED]))
            return scan
        names = {m.filename for m in members}
        roots = sorted({n[:-len("eboot.bin")] for n in names
                        if n == "eboot.bin" or n.endswith(f"{titleid}/eboot.bin")}, key=len)
        if not roots:
            scan.add("warning", f"no `{titleid}/eboot.bin` (or `eboot.bin` at the top) in the archive")
        else:
            root = roots[0]
            if root != f"{titleid}/" or tops != {titleid}:
                where = f"`{root}`" if root else "the top level, with no folder"
                scan.add("notice", f"the app's files are in {where}; the archive's top level holds "
                                   f"{', '.join(f'`{t}`' for t in sorted(tops)[:6])}")
            if f"{root}sce_sys/param.json" not in names:
                scan.add("warning", f"no `{root}sce_sys/param.json` in the archive")
        images = [n for n in names if n.lower().endswith((".ffpfsc", ".ffpkg", ".pkg", ".exfat", ".iso", ".img"))]
        if images:
            scan.add("notice", "holds disk or package images the scan can't look inside: "
                     + ", ".join(f"`{n}`" for n in images[:MAX_LISTED]))
        foreign: dict[str, list[str]] = {}
        for member in members:
            if member.is_dir():
                continue
            with archive.open(member) as handle:
                head = handle.read(8)
                kind = file_kind(head)
                scan.kinds[kind] += 1
                if kind in ("windows program", "macOS program", "script", "windows shortcut"):
                    foreign.setdefault(kind, []).append(member.filename)
                if kind not in ("elf", "self"):
                    if member.file_size <= MAX_FILE_SCAN and member.filename.lower().endswith(
                            (".png", ".jpg", ".jpeg", ".dds", ".at9", ".dat", ".bin", ".pak", ".pk3", ".wad", ".ttf")):
                        hidden = _embedded(head + handle.read())
                        if hidden:
                            scan.add("warning", f"`{member.filename}` is not an executable but has "
                                                f"{len(hidden)} executable image(s) inside it")
                    continue
                if member.file_size > MAX_FILE_SCAN:
                    scan.add("warning", f"`{member.filename}` is an executable too large to examine "
                                        f"({member.file_size:,} bytes)")
                    continue
                data = head + handle.read()
            info = inspect_executable(member.filename, data, scan, compiled)
            if info:
                scan.executables.append(info)
        for kind, paths in sorted(foreign.items()):
            shown = ", ".join(f"`{p}`" for p in paths[:4]) + (" and others" if len(paths) > 4 else "")
            if kind == "script":
                scan.add("notice", f"{len(paths)} script file(s): {shown}")
            else:
                scan.add("warning", f"{len(paths)} {kind} file(s). They can't run on a PS5, so check why "
                                    f"they are there: {shown}")
    _conclude(scan)
    return scan


def _conclude(scan: Scan) -> None:
    for info in scan.executables:
        name = f"`{info.path}`"
        if info.role == "payload":
            scan.add("warning", f"{name} is a payload: code the payload loader runs outside the sandbox "
                                f"(sha256 `{info.sha256}`)")
        for evidence in info.loader + info.maybe:
            if info.role != "payload":
                scan.add("warning", f"{name} {evidence}")
        if info.embedded and info.role != "payload":
            scan.add("warning", f"{name} has {len(info.embedded)} other executable image(s) inside it")
        if info.role == "payload":
            # A payload is already the finding; what the rules see in it is one line of detail.
            seen = [says for rule, _level, says, _examples in info.rules
                    if rule not in ("loader_address_in_data", "elevation_request")]
            if seen:
                scan.add("notice", f"{name}, as a payload: {'; '.join(seen)}")
        else:
            for rule, level, says, examples in info.rules:
                if rule in ("loader_address_in_data", "elevation_request"):
                    continue
                shown = f": {', '.join(f'`{e}`' for e in examples[:6])}" if examples else ""
                scan.add(level, f"{name} {says}{shown}")
        sensitive = sorted(SENSITIVE_SYSCALLS[n] for n in info.syscalls if n in SENSITIVE_SYSCALLS)
        if len(info.syscalls) >= STUB_TABLE:
            # A system library linked in whole: every call has a stub, used or not.
            scan.add("notice", f"{name} carries a full table of system call stubs ({sum(info.syscalls.values())}), "
                               "as a statically linked system library does; which ones it uses can't be told")
        elif sensitive:
            scan.add("warning", f"{name} makes these system calls itself: {', '.join(sensitive)}")
        if info.role == "library":
            scan.add("notice", f"{name} is code the app loads itself (a plain ELF library)")
        for note in info.notes:
            if "entropy" in note:
                scan.add("warning", f"{name}: {note}")
    if not any(x.role in ("title executable", "executable") for x in scan.executables):
        scan.add("warning", "no title executable was found to examine")


def load_approved(path: Path = APPROVED_HELPERS) -> dict[str, dict]:
    """The approved helpers, by sha256. A helper is a payload a maintainer has read and accepted."""
    import json
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {entry["sha256"]: entry for entry in data.get("helpers", [])
            if isinstance(entry, dict) and re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", "")))}


def check_helpers(scan: Scan, approved: dict[str, dict]) -> int:
    """Say which payloads are on the approved list; returns how many are not."""
    unknown = 0
    for info in scan.payloads:
        entry = approved.get(info.sha256)
        if entry:
            scan.add("notice", f"`{info.path}` is on the approved helper list: {entry.get('name', 'unnamed')}")
        else:
            unknown += 1
            scan.add("warning", f"`{info.path}` is NOT on the approved helper list (sha256 `{info.sha256}`): "
                                "read its source before listing, then add it to `helpers/approved.json`")
    return unknown


def attested_build(archive: Path, repository: str) -> tuple[bool | None, str | None, str]:
    """(verified, workflow, note): whether GitHub holds a build attestation for exactly this file.

    `gh attestation verify` checks the signature, that it names this file's digest and that it was
    made by a workflow of `repository`. None when it can't be checked here (no gh, or no token).
    """
    import json
    import os
    import shutil
    import subprocess
    if not shutil.which("gh") or not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        return None, None, "build attestation not checked (needs the gh tool and a token)"
    try:
        done = subprocess.run(["gh", "attestation", "verify", str(archive), "--repo", repository, "--format", "json"],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, None, f"build attestation not checked ({type(error).__name__})"
    if done.returncode != 0:
        if "unknown command" in done.stderr:
            return None, None, "build attestation not checked (this gh is too old)"
        return False, None, "no verified build attestation: nothing ties this file to a workflow run"
    workflow = None
    try:
        result = json.loads(done.stdout)[0]["verificationResult"]
        certificate = (result.get("signature") or {}).get("certificate") or {}
        workflow = certificate.get("buildSignerURI") or None
        if not workflow:
            parameters = result["statement"]["predicate"]["buildDefinition"]["externalParameters"]["workflow"]
            workflow = f"{parameters['repository']}/{parameters['path']}@{parameters['ref']}"
        workflow = str(workflow).removeprefix("https://github.com/")[:300]
    except (ValueError, LookupError, TypeError):
        pass
    return True, workflow, "built by a GitHub Actions workflow of its repository (attestation verified)"


def compare(old: Scan, new: Scan) -> list[str]:
    """What a reviewer should know changed between the listed release and the proposed one."""
    lines = []
    if old.sandbox != new.sandbox:
        lines.append(f"**Verdict changed:** {old.verdict} → {new.verdict}")
    for route in new.routes:
        if route not in old.routes:
            lines.append(f"**New way out of the sandbox:** {route}")
    before = {x.path.rsplit('/', 1)[-1]: x for x in old.executables}
    for info in new.executables:
        name = info.path.rsplit("/", 1)[-1]
        earlier = before.pop(name, None)
        if earlier is None:
            lines.append(f"New {info.role}: `{info.path}` (sha256 `{info.sha256}`)")
            continue
        if info.role == "payload" and info.sha256 != earlier.sha256:
            lines.append(f"Payload `{name}` changed (was `{earlier.sha256[:16]}…`, now `{info.sha256[:16]}…`)")
        if info.role != earlier.role:
            lines.append(f"`{name}` was a {earlier.role} and is now a {info.role}")
        added = sorted(set(info.libraries) - set(earlier.libraries))
        if added:
            lines.append(f"`{name}` now links to: {', '.join(added)}")
        for group in sorted(info.watched):
            fresh = sorted(set(info.watched[group]) - set(earlier.watched.get(group, [])))
            if fresh:
                lines.append(f"`{name}` now imports ({group}): {', '.join(f'`{n}`' for n in fresh)}")
        hosts = sorted(set(info.hosts) - set(earlier.hosts))
        if hosts:
            shown = ", ".join(f"`{h}`" for h in hosts[:MAX_LISTED]) + (" and more" if len(hosts) > MAX_LISTED else "")
            lines.append(f"`{name}` names new hosts: {shown}")
        rules = sorted({r[2] for r in info.rules} - {r[2] for r in earlier.rules})
        for says in rules:
            lines.append(f"`{name}` newly {says}")
        if not earlier.embedded and info.embedded:
            lines.append(f"`{name}` now has another executable inside it")
        if info.size > earlier.size * 1.5 or info.size < earlier.size * 0.5:
            lines.append(f"`{name}` changed size a lot: {earlier.size:,} → {info.size:,} bytes")
    for name, gone in sorted(before.items()):
        lines.append(f"Removed {gone.role}: `{gone.path}`")
    return lines


def summary(scan: Scan) -> dict:
    """What the website and the store API need from a scan, as plain data."""
    return {
        "scanner": SCANNER,
        "sha256": scan.sha256,
        "titleid": scan.titleid,
        "sandbox": scan.sandbox,
        "routes": scan.routes,
        "payloads": [{"path": x.path, "sha256": x.sha256} for x in scan.payloads],
        "network": any("network" in x.watched for x in scan.executables),
        "attested": scan.attested,
        "workflow": scan.workflow,
    }


def read_summary(data, sha256: str) -> dict | None:
    """A kept summary, checked field by field: it was written by a job that handles unreviewed files."""
    if not isinstance(data, dict) or data.get("scanner") != SCANNER or data.get("sha256") != sha256:
        return None
    if data.get("sandbox") not in SANDBOX or not isinstance(data.get("network"), bool):
        return None
    routes, payloads = data.get("routes"), data.get("payloads")
    if not isinstance(routes, list) or any(r not in ROUTES for r in routes) or not isinstance(payloads, list):
        return None
    clean = []
    for item in payloads[:64]:
        if not isinstance(item, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
            return None
        clean.append({"path": str(item.get("path", ""))[:200], "sha256": item["sha256"]})
    attested, workflow = data.get("attested"), data.get("workflow")
    if attested not in (True, False, None) or not (workflow is None or isinstance(workflow, str)):
        return None
    if workflow is not None and not re.fullmatch(r"[A-Za-z0-9_.@/+-]{1,300}", workflow):
        workflow = None
    return {"scanner": SCANNER, "sha256": sha256, "titleid": str(data.get("titleid", ""))[:9],
            "sandbox": data["sandbox"], "routes": [r for r in ROUTES if r in routes], "payloads": clean,
            "network": data["network"], "attested": attested, "workflow": workflow if attested else None}


def markdown(scan: Scan, title: str) -> str:
    """The report for a pull request's job summary."""
    lines = [f"## Release scan: {title}", ""]
    verdict = f"**{scan.verdict[0].upper()}{scan.verdict[1:]}.**"
    if scan.elevates:
        verdict += " Review how, below, before listing it."
    elif scan.unclear:
        verdict += " The evidence below is weak either way; the source should settle it."
    lines += [verdict, "",
              f"Archive: {scan.entries} entries, {scan.unpacked:,} bytes unpacked, sha256 `{scan.sha256}`. "
              "Nothing from it was run.", ""]
    if scan.attested is True:
        lines += [f"Build: attested. GitHub holds a signed statement that a workflow of the app's repository "
                  f"built exactly this file{f' (`{scan.workflow}`)' if scan.workflow else ''}.", ""]
    elif scan.attested is False:
        lines += ["Build: not attested. Nothing ties this file to a workflow run, so it may have been built "
                  "anywhere, from any source.", ""]
    if scan.compared_with:
        lines += [f"### Changes since {scan.compared_with}", ""]
        lines += [f"- {line}" for line in scan.comparison] or ["- Nothing the scan looks at changed."]
        lines.append("")
    order = {"error": 0, "warning": 1, "notice": 2}
    if scan.findings:
        lines += ["| Level | Finding |", "| --- | --- |"]
        lines += [f"| {level} | {text.replace('|', chr(92) + '|')} |"
                  for level, text in sorted(scan.findings, key=lambda f: order[f[0]])]
        lines.append("")
    for info in scan.executables:
        lines += [f"### `{info.path}` ({info.role}, {info.size:,} bytes)", ""]
        if info.libraries:
            lines.append(f"- Links to: {', '.join(info.libraries)}")
        lines.append(f"- Imports {info.imports} system function(s)" + ("" if info.watched else "; none on the watch list"))
        for group, names in sorted(info.watched.items()):
            lines.append(f"  - {group}: {', '.join(f'`{n}`' for n in names)}")
        if info.syscalls:
            known = ", ".join(f"{n}×{c}" for n, c in sorted(info.syscalls.items()) if n >= 0)
            total = sum(info.syscalls.values())
            lines.append(f"- {total} system call instruction(s) of its own" + (f" (numbers: {known})" if known else ""))
        if info.hosts:
            shown = ", ".join(info.hosts[:MAX_LISTED]) + (f" and {len(info.hosts) - MAX_LISTED} more"
                                                          if len(info.hosts) > MAX_LISTED else "")
            lines.append(f"- Hosts named in URLs: {shown}")
        if info.embedded:
            lines.append(f"- Other executable images inside, at offsets {', '.join(hex(o) for o in info.embedded[:8])}")
        for note in info.notes:
            lines.append(f"- Note: {note}")
        lines.append("")
    if scan.skipped:
        lines += ["Not examined: " + "; ".join(scan.skipped) + ".", ""]
    lines += ["A scan like this can't prove an app is harmless: code can hide from every check here. "
              "It shows what honest code does, in the same way for every release.", ""]
    return "\n".join(lines)
