# Windows 2000 PAE instability with RAM above 4 GiB on newer Intel P-cores

## Symptoms

Windows 2000 booted with `/PAE`, with RAM above 4 GiB, running on the
performance cores of Intel's Golden Cove (Alder Lake) and later processors
under KVM with EPT, fails within minutes, often within a minute. Programs fail to start
("entry point not found", "failed to initialize properly", 0xC0000145), Dr.
Watson and Application Error boxes appear, and stop errors occur.

It does not happen:

- with the non-PAE kernel;
- with all RAM below 4 GiB;
- with EPT off;
- on the E-cores;
- with Windows XP, as reported (not tested here).

## Cause

Windows 2000's PAE kernel writes some valid page-table entries as two 32-bit
stores, the low half (with the valid bit) first. Between the two stores, the
entry is valid and points at the page's physical address with bits 32 and up
dropped, which is another page below 4 GiB.

The processor may cache a translation from any valid entry at any time,
including for prefetches and speculative accesses (Intel SDM 325462-093 Vol.
3A, 5.10.2.3). These P-cores do. The wrong translation then stays in the TLB,
and Windows reads or zeroes the wrong page.

With EPT off, KVM traps every guest page-table write, so the hardware never
walks the half-written entry. That is why EPT off hides the problem.

Windows XP SP3 writes the high half first in the same functions:

| Function (ntkrpamp.exe)            | Windows 2000 (5.00.2195.7394) | XP SP3            |
|------------------------------------|-------------------------------|-------------------|
| MiMapPageInHyperSpace              | low first (0x804535C0)        | high first        |
| Zero-page mapping (VA 0xC0880000)  | low first (0x80453631)        | high first        |
| PTE fill loops                     | low first (0x80436D96, 0x8043B6C3) | not compared |

Windows 2000's page-fault path already writes the high half first.

## Evidence

The runs used the same method throughout: KVM, P-cores only, 4 GiB, one boot
plus up to 6 log-off/log-on cycles.

| Kernel                                    | Result                             |
|-------------------------------------------|------------------------------------|
| Unpatched                                 | 2 of 2 failed (at 35 s and 90 s)   |
| Patched (the four sites, high half first) | 4 of 4 passed all 6 cycles         |
| Patched, booted through `/KERNEL=`        | 1 of 1 passed all 6 cycles         |

All runs were on an Arrow Lake P-core (Core Ultra 7 265K). The problem was
first seen under QEMU/KVM on Alder Lake.

## Patch

`w2k-pae-pte-fix.py` (Python 3, no dependencies) swaps the two stores at the
four sites, so the high half is written first. It finds the sites by their
surrounding bytes and recomputes the PE checksum. It writes nothing unless it
finds every site exactly once, and it recognises an already-patched file.

    python3 w2k-pae-pte-fix.py ntkrnlpa.exe ntkrpafx.exe

Take `ntkrnlpa.exe` from `%SystemRoot%\system32`. That is the PAE kernel
whichever HAL is installed; Setup copies `ntkrpamp.exe` there under this name
on multiprocessor systems.

The kernels it has been checked against:

- **Tested:** 5.00.2195.7394 multiprocessor PAE kernel (`NTKRPAMP.EXE`).
- **Patched but not tested:** the 5.00.2195.7394 uniprocessor PAE kernel
  (`NTKRNLPA.EXE`), whose same four sites differ only in registers.
- **Any other build:** the script refuses it if the patterns don't match.

### Installing

1. Copy the patched kernel into `%SystemRoot%\system32` under a new name,
   e.g. `ntkrpafx.exe`.
2. In `boot.ini`, add `/KERNEL=ntkrpafx.exe` to a copy of the `/PAE` entry:

       multi(0)disk(0)rdisk(0)partition(1)\WINNT="Windows 2000 PAE (fixed)" /fastdetect /PAE /KERNEL=ntkrpafx.exe

The original kernel and entry stay as a fallback, and Windows File Protection
has nothing to restore.

### Manual hex edit

For 5.00.2195.7394 only, at these file offsets. The script also fixes the PE
checksum, which a hex edit leaves stale.

| Kernel | Offset  | Original                     | Patched                      |
|--------|---------|------------------------------|------------------------------|
| MP     | 0x535C0 | 89 06 0B D1 8B C6 89 56 04   | 0B D1 89 56 04 89 06 8B C6   |
| MP     | 0x53631 | 89 03 89 53 04               | 89 53 04 89 03               |
| MP     | 0x36D96 | 89 03 89 4D F0 89 4B 04      | 89 4D F0 89 4B 04 89 03      |
| MP     | 0x3B6C3 | 89 18 89 48 04               | 89 48 04 89 18               |
| UP     | 0x50C2F | 89 06 0B D1 8B C6 89 56 04   | 0B D1 89 56 04 89 06 8B C6   |
| UP     | 0x50CC0 | 89 06 89 56 04               | 89 56 04 89 06               |
| UP     | 0x3490D | 89 03 89 4B 04               | 89 4B 04 89 03               |
| UP     | 0x392ED | 89 18 89 48 04               | 89 48 04 89 18               |

## Not known

- **What caches the half-written entry.** It isn't an access the program
  orders after the stores: a test program doing that never caught it. A
  hardware prefetcher is suspected.
- **Bare metal:** whether it fails there too is untested.
- **Other kernel builds:** untested.
