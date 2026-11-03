//go:build unix

package host

import (
	"context"
	"os/exec"
	"syscall"
	"testing"
)

// An adapter call runs in ak's session, in a group of its own, and a child of it leading another
// group goes with it.
func TestAnAdapterCallStaysInAksSession(t *testing.T) {
	cmd := exec.CommandContext(context.Background(), "sleep", "60")
	stop := AdapterCall(cmd)
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	session, _ := getsid(0)
	sid, _ := getsid(cmd.Process.Pid)
	group, _ := syscall.Getpgid(cmd.Process.Pid)
	stop()
	cmd.Wait()
	if sid != session || group != cmd.Process.Pid {
		t.Errorf("the call ran in session %d, group %d; ak's session is %d", sid, group, session)
	}
	endsWithItsGroups(t, AdapterCall)
}
