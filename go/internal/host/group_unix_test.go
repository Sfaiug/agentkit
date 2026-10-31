//go:build unix

package host

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"syscall"
	"testing"
	"time"
)

// A child that leads a process group of its own, as `timeout` makes one, goes with the command.
func TestGroupEndsTheWholeSession(t *testing.T) {
	if os.Getenv("AK_GROUP_HELPER") != "" {
		child := exec.Command("sleep", "60")
		child.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
		if child.Start() == nil {
			fmt.Println(child.Process.Pid)
		}
		time.Sleep(time.Minute)
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestGroupEndsTheWholeSession$")
	cmd.Env = append(os.Environ(), "AK_GROUP_HELPER=1")
	Group(cmd)
	out, _ := cmd.StdoutPipe()
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	line, _ := bufio.NewReader(out).ReadString('\n')
	child, err := strconv.Atoi(line[:max(0, len(line)-1)])
	if err != nil {
		cancel()
		cmd.Wait()
		t.Fatalf("the helper named no child: %q", line)
	}
	cancel()
	cmd.Wait()
	for deadline := time.Now().Add(5 * time.Second); time.Now().Before(deadline); time.Sleep(20 * time.Millisecond) {
		if stat, ok := ReadStat(child); syscall.Kill(child, 0) != nil || ok && stat.Exited() {
			return
		}
	}
	syscall.Kill(child, syscall.SIGKILL)
	t.Fatal("a child leading its own group outlived the command")
}
