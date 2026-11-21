#!/usr/bin/env python3
# w2k-pae-pte-fix.py: patches a Windows 2000 PAE kernel (ntkrnlpa.exe or
# ntkrpamp.exe) to write the page-table entries of its hyperspace and
# page-zeroing mappings high doubleword first, as Windows XP does, instead of
# low doubleword (the one with the valid bit) first. See README.md.
#
# Usage: python3 w2k-pae-pte-fix.py IN OUT
#
# IN is not modified. Each of the four sites must be found exactly once,
# either unpatched or already patched, or nothing is written. The PE checksum
# of OUT is recomputed.

import struct
import sys

# Each site: its name, then one or more variants (the unpatched bytes and the
# patched bytes, the same length; the surrounding bytes pin the place down).
# Only the two stores of the entry swap places, with the instructions between
# them kept in front of both stores.
SITES = [
    ("MiMapPageInHyperSpace", [
        # or edx,ecx / mov [esi+4],edx / mov [esi],eax / mov eax,esi
        ("8b4df481e7ff0f00000bc783e1f0 89060bd18bc6895604 c1e009",
         "8b4df481e7ff0f00000bc783e1f0 0bd18956048906 8bc6 c1e009"),
        ("81e7ff0f00000bc783e1f0 89060bd18bc6895604 c1e009",
         "81e7ff0f00000bc783e1f0 0bd18956048906 8bc6 c1e009"),
    ]),
    ("zero page mapping (0xC0880000)", [
        # multiprocessor kernel: mov [ebx+4],edx / mov [ebx],eax
        ("81e6ff0f000083e7f00bc60bd7 8903895304 5b5eb8000088c0",
         "81e6ff0f000083e7f00bc60bd7 8953048903 5b5eb8000088c0"),
        # uniprocessor kernel: mov [esi+4],edx / mov [esi],eax
        ("0bc70bd3 8906895604 5b5eb8000088c0",
         "0bc70bd3 8956048906 5b5eb8000088c0"),
    ]),
    ("PTE fill loop 1", [
        # multiprocessor kernel
        ("8b55e08945ec 8903894df0894b04 83c308",
         "8b55e08945ec 894df0894b048903 83c308"),
        # uniprocessor kernel
        ("8bca894df08945ec 8903894b04 8b4de083c308",
         "8bca894df08945ec 894b048903 8b4de083c308"),
    ]),
    ("PTE fill loop 2", [
        ("81c700100000 8918894804 83c008",
         "81c700100000 8948048918 83c008"),
    ]),
]


def hexbytes(s):
    return bytes.fromhex(s.replace(" ", ""))


def pe_checksum(data, offset):
    total = 0
    for i in range(0, len(data) - 1, 2):
        if i == offset or i == offset + 2:
            continue
        total += data[i] | data[i + 1] << 8
        total = (total & 0xFFFF) + (total >> 16)
    if len(data) & 1:
        total += data[-1]
        total = (total & 0xFFFF) + (total >> 16)
    total = (total & 0xFFFF) + (total >> 16)
    return total + len(data)


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: w2k-pae-pte-fix.py IN OUT")
    data = bytearray(open(sys.argv[1], "rb").read())
    if data[:2] != b"MZ":
        sys.exit("not a PE file")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        sys.exit("not a PE file")
    checksum_offset = pe + 24 + 64

    patched = 0
    for name, variants in SITES:
        found = []
        for old, new in variants:
            old, new = hexbytes(old), hexbytes(new)
            for pattern, state in ((old, "unpatched"), (new, "already patched")):
                at = data.find(pattern)
                while at != -1:
                    found.append((at, pattern, state, new))
                    at = data.find(pattern, at + 1)
        # A shorter variant matches where a longer one does too: the same
        # place, which both end at.
        ends = {}
        for at, pattern, state, new in found:
            ends.setdefault(at + len(pattern), (at, pattern, state, new))
        if len(ends) != 1:
            sys.exit(f"{name}: found {len(ends)} times, expected once: not a kernel this patch knows; nothing written")
        at, pattern, state, new = next(iter(ends.values()))
        print(f"{name}: {state} at file offset {at:#x}")
        if state == "unpatched":
            data[at:at + len(new)] = new
            patched += 1

    struct.pack_into("<I", data, checksum_offset, pe_checksum(data, checksum_offset))
    open(sys.argv[2], "wb").write(data)
    print(f"{patched} site(s) patched; PE checksum {struct.unpack_from('<I', data, checksum_offset)[0]:#x}; written to {sys.argv[2]}")


main()
