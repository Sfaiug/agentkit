package cli

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/terminal"
	"agentkit/internal/tmux"
)

func init() { commands["orch list"] = orchList }

// orchList answers where no seat exists: how to open one, then where the agents run.
func orchList(_ []string, out, errOut io.Writer) int {
	if !seatless() {
		return notImplemented(errOut, "orch list")
	}
	fmt.Fprintln(out, "no orchestrator session; `ak orch <name>` starts one")
	for _, line := range terminal.Wrap(host.SliceLine(), terminal.For(out).ContentWidth()) {
		fmt.Fprintln(out, terminal.Dim(out, line))
	}
	return 0
}

// seatless is whether Python ak would find no seat: no session on ak's own server, no marked
// one on the default server, no session record or rename pointer. Finding one, its listing
// writes seat state, which Go does not do yet.
func seatless() bool {
	files, _ := os.ReadDir(filepath.Join(config.Home(), "state"))
	for _, file := range files {
		if strings.HasPrefix(file.Name(), "session-") && strings.HasSuffix(file.Name(), ".json") {
			return false
		}
	}
	if len(tmux.Sessions(tmux.Own())) > 0 {
		return false
	}
	for _, session := range tmux.Sessions(tmux.Default) {
		if session.Mark == "1" {
			return false
		}
	}
	return true
}
