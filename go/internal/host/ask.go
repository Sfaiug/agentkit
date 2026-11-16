package host

import (
	"context"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Within is the seconds a machine that does not answer holds the tick, all of them asked at once
// (Python's machines.TIMEOUT).
const Within = 10

// SSH is ssh running line on alias, never asking for a password and giving up on reaching it
// within the tick's wait, options before the alias (Python's machines.SSH).
func SSH(alias, line string, options ...string) []string {
	ssh := []string{"ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=" + strconv.Itoa(Within)}
	return append(append(ssh, options...), "--", alias, line)
}

// An Answer is what a command Ask ran printed, nil where it failed or had not answered whole
// within the tick's wait, and what it said on stderr, nil where it had not ended.
type Answer struct{ Out, Said *string }

// Ask is each of commands' Answer, all run at once, the tick's wait or the end of ctx ending
// everything they started (Python's machines.ask).  One that cannot start says why on its stderr.
func Ask(ctx context.Context, commands [][]string) []Answer {
	ctx, cancel := context.WithTimeout(ctx, Within*time.Second)
	defer cancel()
	answers := make([]Answer, len(commands))
	var asking sync.WaitGroup
	for i, command := range commands {
		cmd := exec.CommandContext(ctx, command[0], command[1:]...)
		stop := Group(cmd)
		var out, said strings.Builder
		cmd.Stdout, cmd.Stderr = &out, &said
		if err := cmd.Start(); err != nil {
			why := err.Error()
			answers[i].Said = &why
			continue
		}
		waited := make(chan error, 1)
		go func() { waited <- cmd.Wait() }()
		asking.Add(1)
		go func() {
			defer asking.Done()
			select {
			case err := <-waited:
				if err != nil && ctx.Err() != nil {
					return // ended by the wait: it had not answered
				}
				stderr := said.String()
				answers[i].Said = &stderr
				if err == nil {
					stdout := out.String()
					answers[i].Out = &stdout
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
