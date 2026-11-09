package host

import (
	"context"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
)

// within is the seconds a machine that does not answer holds the tick, all of them asked at once
// (Python's machines.TIMEOUT).
const within = 10

// SSH is ssh running line on alias, never asking for a password and giving up on reaching it
// within the tick's wait, options before the alias (Python's machines.SSH).
func SSH(alias, line string, options ...string) []string {
	ssh := []string{"ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=" + strconv.Itoa(within)}
	return append(append(ssh, options...), "--", alias, line)
}

// Ask is what each of commands, all run at once, printed, nil where it failed or had not answered
// whole within the tick's wait, which ends everything it started (Python's machines.ask).
func Ask(commands [][]string) []*string {
	ctx, cancel := context.WithTimeout(context.Background(), within*time.Second)
	defer cancel()
	answers := make([]*string, len(commands))
	var asking sync.WaitGroup
	for i, command := range commands {
		cmd := exec.CommandContext(ctx, command[0], command[1:]...)
		stop := Group(cmd)
		var out strings.Builder
		cmd.Stdout = &out
		if cmd.Start() != nil {
			continue
		}
		waited := make(chan error, 1)
		go func() { waited <- cmd.Wait() }()
		asking.Add(1)
		go func() {
			defer asking.Done()
			select {
			case err := <-waited:
				if err == nil {
					said := out.String()
					answers[i] = &said
				}
			// exec stops watching the deadline once the first process is gone, and a child it
			// left holding the output would hold Wait for as long as it lives
			case <-ctx.Done():
				stop()
			}
		}()
	}
	asking.Wait()
	return answers
}
