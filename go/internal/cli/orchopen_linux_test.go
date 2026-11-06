package cli

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"syscall"
	"testing"

	"golang.org/x/sys/unix"
)

// A person's open Go hands over leaves the home as it was from the command's way in, ak's folders
// included: they are made only once the seat is Go's.
func TestAnOpenFromATerminalHandedOverLeavesTheHomeAsItWas(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("an open needs tmux")
	}
	home := sandbox(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.acme]\nharness='echo'\nmodel='echo-1'\neffort='low'\nprovider='test'\n"+
		"[providers.test]\nmode='subscription'\n[defaults]\nefforts = { acme = { effort = 'high' } }\n")
	stdin := os.Stdin
	os.Stdin = terminalIn(t)
	t.Cleanup(func() { os.Stdin = stdin })
	before := tree(t, home)
	var out, errOut bytes.Buffer
	if code := orchOpen([]string{"crew", "--workers", "acme"}, &out, &errOut); code != 3 || !reflect.DeepEqual(before, tree(t, home)) {
		t.Fatalf("got %d (%q), home changed: %v; want a hand-over leaving it as it was", code, errOut.String(),
			!reflect.DeepEqual(before, tree(t, home)))
	}
}

// terminalIn is a pty's own end, the stdin of a command a person types.
func terminalIn(t *testing.T) *os.File {
	master, err := os.OpenFile("/dev/ptmx", os.O_RDWR|syscall.O_NOCTTY, 0)
	if err != nil {
		t.Skip("no pty here")
	}
	t.Cleanup(func() { master.Close() })
	number, err := unix.IoctlGetUint32(int(master.Fd()), unix.TIOCGPTN)
	if err == nil {
		err = unix.IoctlSetPointerInt(int(master.Fd()), unix.TIOCSPTLCK, 0)
	}
	var own *os.File
	if err == nil {
		own, err = os.OpenFile(fmt.Sprintf("/dev/pts/%d", number), os.O_RDWR|syscall.O_NOCTTY, 0)
	}
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { own.Close() })
	return own
}
