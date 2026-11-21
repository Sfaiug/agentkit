"""Linux v6.12's own numbers, for each machine ak answers syncs on: its audit architecture
(audit.h, elf-em.h) and its calls fsync, fdatasync, sync, syncfs, msync and sync_file_range
(scripts/syscall.tbl, which newer machines take, and each other machine's syscall.tbl)."""

SHARED = (82, 83, 81, 267, 227, 84)
SYNCS = {"x86_64": (62 | 0xC0000000, (74, 75, 162, 306, 26, 277)),
         "aarch64": (183 | 0xC0000000, SHARED), "riscv64": (243 | 0xC0000000, SHARED),
         "loongarch64": (258 | 0xC0000000, SHARED),
         "ppc64le": (21 | 0xC0000000, (118, 148, 36, 348, 144, 308)),
         "s390x": (22 | 0x80000000, (118, 148, 36, 338, 144, 307))}
