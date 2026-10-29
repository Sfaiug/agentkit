package cli

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/agent"
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

// seatless is whether Python ak would find no seat: no session record or rename pointer, on
// ak's own server only sessions it did not open running no agent, and no marked session on the
// default server. Finding one, its listing writes seat state, which Go does not do yet.
func seatless() bool {
	files, _ := os.ReadDir(filepath.Join(config.Home(), "state"))
	for _, file := range files {
		if strings.HasPrefix(file.Name(), "session-") && strings.HasSuffix(file.Name(), ".json") {
			return false
		}
	}
	var strangers []string
	for _, session := range tmux.Sessions(tmux.Own()) {
		if session.Mark == "1" {
			return false
		}
		strangers = append(strangers, session.Name)
	}
	for _, session := range tmux.Sessions(tmux.Default) {
		if session.Mark == "1" {
			return false
		}
	}
	return agent.Agentless(tmux.Own(), strangers)
}
