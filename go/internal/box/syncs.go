//go:build linux

package box

import (
	"runtime"
	"unsafe"

	"golang.org/x/sys/unix"
)

// calls are, for each machine ak answers syncs on, its audit architecture and the numbers there
// of fsync, fdatasync, sync, syncfs, msync and sync_file_range: Python's syncs.CALLS.
var calls = map[string]struct {
	arch    uint32
	numbers []uint32
}{
	"amd64": {unix.AUDIT_ARCH_X86_64, []uint32{74, 75, 162, 306, 26, 277}},
	"arm64": {unix.AUDIT_ARCH_AARCH64, []uint32{82, 83, 81, 267, 227, 84}},
}

// ignoreSyncs makes a sync to disk asked by this process or anything it starts return 0 at once,
// the kernel's filesystems never reached, as Python's syncs.ignored does for its box: nothing
// written in a box has to survive a crash of the machine, yet each fsync on ext4 commits the
// journal, holding up every writer on the host.  A seccomp program does it, so a program calling
// the kernel itself is answered too; bubblewrap has set no_new_privs, which loading it needs.
// On another machine, or where the kernel refuses the program, the box stays as it was.
func ignoreSyncs() {
	machine, ok := calls[runtime.GOARCH]
	if !ok {
		return
	}
	// Classic BPF over seccomp_data, whose call number is at 0 and architecture at 4: a call of
	// another architecture, a 32-bit program's, numbers its calls otherwise and passes.
	const load, equal, ret = unix.BPF_LD | unix.BPF_W | unix.BPF_ABS, unix.BPF_JMP | unix.BPF_JEQ | unix.BPF_K, unix.BPF_RET | unix.BPF_K
	n := uint8(len(machine.numbers))
	program := []unix.SockFilter{{Code: load, K: 4}, {Code: equal, Jf: n + 1, K: machine.arch}, {Code: load, K: 0}}
	for i, call := range machine.numbers {
		program = append(program, unix.SockFilter{Code: equal, Jt: n - uint8(i), K: call})
	}
	program = append(program, unix.SockFilter{Code: ret, K: unix.SECCOMP_RET_ALLOW}, unix.SockFilter{Code: ret, K: unix.SECCOMP_RET_ERRNO})
	// Every thread of this process, so whichever starts the command passes it on.
	unix.Syscall(unix.SYS_SECCOMP, unix.SECCOMP_SET_MODE_FILTER, unix.SECCOMP_FILTER_FLAG_TSYNC,
		uintptr(unsafe.Pointer(&unix.SockFprog{Len: uint16(len(program)), Filter: &program[0]})))
}
