/*
 * Patterns the release scan (catalog/scan.py) looks for in every file of an
 * app's archive. Each rule says what it means in `says` and how loud it is in
 * `level` (warning or notice). A match is evidence for a reviewer, not a
 * verdict: honest apps elevate too, and a determined author can avoid every
 * pattern here.
 */

rule payload_sdk_kernel_access
{
    meta:
        level = "warning"
        says = "contains the payload SDK's kernel read/write routines"
    strings:
        $a = "KERNEL_ADDRESS_" ascii
        $b = "kernel_copyin" ascii
        $c = "kernel_copyout" ascii
        $d = "kernel_setlong" ascii
        $e = "kernel_getlong" ascii
        $f = "KERNEL_OFFSET_" ascii
        $g = "kernel_get_proc" ascii
        $h = "kernel_dynlib" ascii
    condition:
        2 of them
}

rule credential_patching
{
    meta:
        level = "warning"
        says = "can change a process's credentials (authority ID, capabilities, jail or root directory)"
    strings:
        $a = "kernel_set_ucred" ascii
        $b = "kernel_set_proc_rootdir" ascii
        $c = "kernel_set_proc_jaildir" ascii
        $d = "UCRED_CR_SCEAUTHID" ascii
        $e = "UCRED_CR_SCECAPS" ascii
        $f = "kernel_set_qaflags" ascii
    condition:
        any of them
}

rule elevation_request
{
    meta:
        level = "warning"
        says = "asks a resident jailbreak service to lift its sandbox (a request file)"
    strings:
        $a = "elevate_proc" ascii
        $b = "etahen_jailbreak" ascii
    condition:
        any of them
}

rule loader_address_in_data
{
    meta:
        level = "warning"
        says = "holds the payload loader's address (127.0.0.1, port 9021 or 9020) as a ready socket address"
    strings:
        // sockaddr_in: length or zero, AF_INET, port in network order, 127.0.0.1
        $a = { (00 | 10) 02 23 3D 7F 00 00 01 }
        $b = { (00 | 10) 02 23 3C 7F 00 00 01 }
    condition:
        any of them
}

rule kernel_memory_and_flash_devices
{
    meta:
        level = "warning"
        says = "names raw memory, flash or disk devices"
    strings:
        $a = "/dev/sflash" ascii
        $b = "/dev/kmem" ascii
        $c = "/dev/mem" ascii fullword
        $d = "/dev/ssd0" ascii
        $e = "/dev/da0" ascii
        $f = "/dev/nvme" ascii
        $g = "/dev/sbram" ascii
        $h = "/dev/icc" ascii
    condition:
        any of them
}

rule system_partitions
{
    meta:
        level = "notice"
        says = "names system folders"
    strings:
        $a = "/system/" ascii
        $b = "/system_ex/" ascii
        $c = "/system_data/" ascii
        $d = "/system_tmp/" ascii
        $e = "/preinst/" ascii
        $f = "/preinst2/" ascii
        $g = "/update/" ascii
        $h = "/user/home/" ascii
        $i = "/user/appmeta" ascii
        $j = "/system_data/priv" ascii
    condition:
        any of them
}

rule mounting
{
    meta:
        level = "notice"
        says = "has what it needs to mount or unmount file systems"
    strings:
        $a = "fspath" ascii fullword
        $b = "fstype" ascii fullword
        $c = "nmount" ascii fullword
        $d = "/dev/lvd" ascii
        $e = "pfs_" ascii
    condition:
        2 of them
}

rule jailbreak_tools_by_name
{
    meta:
        level = "notice"
        says = "mentions jailbreak tools or the loader by name"
    strings:
        $a = "etaHEN" ascii nocase
        $b = "kstuff" ascii nocase
        $c = "elfldr" ascii nocase
        $d = "payload loader" ascii nocase
        $e = "ps5-payload" ascii nocase
        $f = "lapy" ascii nocase fullword
        $g = "jailbreak" ascii nocase
    condition:
        any of them
}
