package harness

import (
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// codexAsked is how long a tick waits on a seat's server for what it holds: a server that has not
// answered by then leaves the seat's last Stop standing, and the tick goes on.
const codexAsked = 2 * time.Second

// codexHolds is the type of each piece of background work the seat's thread runs now (codex.py
// `holds`), asked of its own app server through the connection its launch wrote in the seat's
// home: no work's end starts a turn whose Stop would list it afresh.  False where that server
// cannot be asked, in time or at all.
func codexHolds(record *run.Object) ([]string, bool) {
	thread, _ := codexThread(record)
	receipt := codexReceipt(record)
	if thread == "" || receipt == nil || !launchToken.MatchString(receipt.Str("remote")) {
		return nil, false
	}
	remote := receipt.Str("remote")
	tasks, ok := codexInFlight(filepath.Join(config.Home(), "state", "codex-remote-"+remote), thread, time.Now().Add(codexAsked))
	if !ok {
		return nil, false
	}
	held := []string{}
	for _, task := range tasks {
		held = append(held, task.(*run.Object).Str("type"))
	}
	return held, true
}
