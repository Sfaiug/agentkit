//go:build unix

package loop

import "os/exec"

// taskRoom is the host's room for n more tasks, a process or thread each, proven by as many
// processes at once: a `true` it starts holds its task, ended or not, until it is waited for.
func taskRoom(n int) error {
	var started []*exec.Cmd
	defer func() {
		for _, held := range started {
			held.Wait()
		}
	}()
	for range n {
		held := exec.Command("true")
		if err := held.Start(); err != nil {
			return err
		}
		started = append(started, held)
	}
	return nil
}
