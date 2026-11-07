package cli

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/hookfact"
	"agentkit/internal/lifecycle"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// orchestratorStop judges a seat's Stop as hooks/orchestrator-stop.sh does.  One sent back gets
// its reason on out (`stopHeld`); one that stands marks ended the questions the seat kept back
// for it.  Either way a Stop listing the harness's background tasks is written down, under the
// name the seat goes by now: only this hook knows whether the turn ended there.  The PreToolUse
// before a question card is `questionCard`'s.  A worker, a harness outside any seat, a path-like
// name and a sub-agent's event decide nothing.  What Go cannot read leaves it all to Python.
func orchestratorStop(payload []byte, out io.Writer) int {
	// when the Stop was heard, before anything that may wait on a lock: a prompt heard while this
	// judges is the newer fact
	heard, launched := float64(time.Now().UnixNano())/1e9, os.Getenv("AGENTKIT_SESSION")
	read, _ := run.Decode(payload)
	event, ok := read.(*run.Object)
	if !ok {
		event = run.NewObject() // what it was handed says nothing of the turn
	}
	if _, err := config.SessionPath(launched); err != nil || os.Getenv("AK_RUN_ROLE") == "worker" ||
		first(event, subAgent...) != nil {
		return 0
	}
	name, record, err := config.ResolveSession(launched)
	if err != nil {
		name, record = launched, nil
	}
	if event.Str("hook_event_name") == "PreToolUse" {
		return questionCard(name, event, out)
	}
	harness := config.SeatHarness(name)
	back, err := stopHeld(launched, name, record, harness, event)
	if err != nil {
		return leftToPython()
	}
	if back == "" {
		seat.TurnEnded(name)
	}
	if _, listed := lifecycle.HandedOver(event); listed {
		fact := lifecycle.StopFact(launched, event, heard, back != "")
		hookfact.Record(name, fact, lifecycle.Keeps(harness, fact))
		seat.LookSoon(nil)
	}
	if back != "" {
		reply := run.NewObject()
		reply.Set("decision", "block")
		reply.Set("reason", back)
		fmt.Fprintln(out, run.Line(reply))
	}
	return 0
}

// latch is the turn's latch, which `ak hook seat-state` writes fresh on each prompt under the name
// the seat's harness was launched with: when the turn began, and what the stop hook sent back in
// it.
func latch(launched string) string {
	return filepath.Join(config.Home(), "state", "stop-"+launched+".json")
}

// relatch rewrites the turn's latch whole in one replace, so a reader never sees half of it.
func relatch(launched, record string) error {
	path := latch(launched)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	tmp := fmt.Sprintf("%s.tmp.%d", path, os.Getpid())
	err := os.WriteFile(tmp, []byte(record+"\n"), 0o600)
	if err == nil {
		err = os.Rename(tmp, path)
	}
	if err != nil {
		os.Remove(tmp)
	}
	return err
}
