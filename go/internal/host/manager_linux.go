package host

import (
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"syscall"
	"time"
)

// userManager is whether a running `systemd --user` answers on its control socket in this PID
// namespace: a bus address may name anybody's socket, and a gone manager's refuses the connection.
func userManager() bool {
	if _, err := exec.LookPath("systemd-run"); err != nil {
		return false
	}
	runtime := os.Getenv("XDG_RUNTIME_DIR")
	if runtime == "" {
		runtime = filepath.Join("/run/user", strconv.Itoa(os.Getuid()))
	}
	conn, err := net.DialTimeout("unix", filepath.Join(runtime, "systemd/private"), 5*time.Second)
	if err != nil {
		return false
	}
	defer conn.Close()
	raw, err := conn.(*net.UnixConn).SyscallConn()
	if err != nil {
		return false
	}
	// An outside manager cannot resolve a box's PIDs: Linux reports its peer's as zero.
	pid := int32(0)
	raw.Control(func(fd uintptr) {
		if cred, err := syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED); err == nil {
			pid = cred.Pid
		}
	})
	return pid > 0
}
