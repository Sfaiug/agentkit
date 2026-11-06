package harness

import (
	"errors"
	"fmt"
	"io"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/run"
)

// antigravityInteractive is the line adapters/antigravity.sh prints, its status line Go's own:
// `ak hook status` where that adapter puts the status script under hooks/, which only Python's
// look follows, in front of the owner's command as the adapter read it.  The rest of the line is
// the adapter's, its exit too; a line whose status line Go cannot find is handed back unprinted.
func antigravityInteractive(root string, args []string, out, errOut io.Writer) int {
	shell := exec.Command(filepath.Join(config.Repo(), "adapters", "antigravity.sh"), append([]string{"interactive"}, args...)...)
	shell.Stderr = errOut
	printed, err := shell.Output()
	if exit := (*exec.ExitError)(nil); errors.As(err, &exit) {
		return exit.ExitCode()
	}
	line, split := commandhelp.ShellSplit(strings.TrimFunc(string(printed), config.Space))
	at := slices.Index(line, "--settings") + 1
	var settings, status *run.Object
	if split && at > 0 && at < len(line) {
		read, _ := run.Decode([]byte(line[at]))
		if settings, _ = read.(*run.Object); settings != nil {
			status = settings.Dict("statusLine")
		}
	}
	if err != nil || status == nil {
		fmt.Fprintln(errOut, "ak adapter: antigravity interactive printed no status line Go reads")
		return 2
	}
	command := StatusCommand(root) + " >/dev/null"
	if _, owner, piped := strings.Cut(status.Str("command"), " | { "); piped {
		command = StatusCommand(root) + " | { " + owner
	}
	status.Set("command", command)
	line[at] = run.Line(settings)
	fmt.Fprintln(out, commandhelp.ShellJoin(line))
	return 0
}
