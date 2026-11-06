//go:build linux

package box

import (
	"cmp"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"syscall"

	"agentkit/internal/config"
	"agentkit/internal/host"
)

// drainFlag tells the box's first process it runs a check.
const drainFlag = "--drain"

// RunCheck runs argv as a check, Python's box.command with home_overlay and drain: the worker's
// walls in the workspace, with throwaway writes in the account's homes, its stdin empty and its
// output into output, until its output's end, or ctx ends or the watch stops it, and the box's
// first process with it: how it ended, the shell's 126 for a box that never started, and what
// the watch says ended it.  The watch counts silence from the box being up and finds a declared
// `timeout` among the box's own processes.
func RunCheck(ctx context.Context, watch host.Watch, argv []string, env map[string]string, workspace, out string, output *os.File) (int, string, error) {
	file := filepath.Join(config.Resolve(out), "box-processes.json")
	homes := []string{config.Resolve(cmp.Or(env["HOME"], config.UserHome()))}
	if account, err := user.Current(); err == nil {
		homes = append(homes, config.Resolve(account.HomeDir))
	}
	cmd, done, err := command(append([]string{exe, file, drainFlag}, argv...), env, workspace, out, nil, nil, nil, homes)
	if err != nil {
		return 0, "", err
	}
	defer done()
	nothing, err := os.Open(os.DevNull)
	if err != nil {
		return 0, "", err
	}
	defer nothing.Close()
	cmd.Dir, cmd.Stdin, cmd.Stdout, cmd.Stderr = workspace, nothing, output, output
	box := &look{report: file}
	watch.Began, watch.Declared = box.up, box.declared
	ctx, watched := watch.Stop(ctx)
	code, _, err := supervised(ctx, cmd, box)
	stopped := watched()
	if _, unreported := os.Stat(file); err == nil && unreported != nil && code == 1 {
		return 126, stopped, nil // bubblewrap exits 1 when it cannot build the box: no exit of the command
	}
	return code, stopped, err
}

// overlays are those of homes the box may write as a throwaway overlay: no place of its own or
// writable already, and none with a mount inside, which overlayfs refuses: a box's arguments must
// not grow with a home's entries to rebuild it, so such a home stays read-only.
func overlays(homes []string, own map[string]string, writable []string) []string {
	if len(homes) == 0 {
		return nil
	}
	data, _ := os.ReadFile("/proc/self/mountinfo")
	var mounts []string
	for _, line := range config.SplitLines(string(data)) {
		if fields := strings.Fields(line); len(fields) > 4 {
			mounts = append(mounts, octal(fields[4]))
		}
	}
	var found []string
	for _, home := range homes {
		_, kept := own[home]
		child := slices.ContainsFunc(mounts, func(mount string) bool { return strings.HasPrefix(mount, home+"/") })
		if !kept && !child && !slices.Contains(writable, home) && !slices.Contains(found, home) {
			found = append(found, home)
		}
	}
	return found
}

// octal is a mountinfo path with its `\NNN` escapes read back.
func octal(path string) string {
	var out strings.Builder
	for i := 0; i < len(path); i++ {
		if path[i] == '\\' && i+3 < len(path) {
			if value, err := strconv.ParseUint(path[i+1:i+4], 8, 8); err == nil {
				out.WriteByte(byte(value))
				i += 3
				continue
			}
		}
		out.WriteByte(path[i])
	}
	return out.String()
}

// drain is run for a check: its output comes through this process, which stays until that
// output's end, so a child holding it after the command exited still faces the silence watchdog.
// A check runs again and a killed one is retried, as a seat's conversation or a turn cannot be,
// so wherever memory runs out the kernel ends a check first; children inherit the score.
func drain(argv []string) (int, map[int]string) {
	os.WriteFile("/proc/self/oom_score_adj", []byte("1000"), 0o666)
	read, write, err := os.Pipe()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 126, nil
	}
	command, err := startCommand(argv, write)
	write.Close()
	if err != nil {
		return commandFailed(err)
	}
	drained := make(chan struct{})
	go func() {
		io.Copy(os.Stdout, read)
		close(drained)
	}()
	return supervise(command.Pid, drained)
}

// startCommand starts the command in a session of its own, its output into output.
func startCommand(argv []string, output *os.File) (*os.Process, error) {
	path, err := exec.LookPath(argv[0])
	if err != nil {
		path = argv[0]
	}
	return os.StartProcess(path, argv, &os.ProcAttr{
		Files: []*os.File{os.Stdin, output, output},
		Sys:   &syscall.SysProcAttr{Setsid: true},
	})
}
