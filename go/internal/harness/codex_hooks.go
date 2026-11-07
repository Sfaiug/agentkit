package harness

import (
	"fmt"
	"io"
	"os"
	"regexp"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/handover"
	"agentkit/internal/hookfact"
	"agentkit/internal/lifecycle"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

var codexQuestion = regexp.MustCompile("^(?:" + codexQuestions + ")$")

// codexHookEvent reads what Codex hands a seat's hook, as codex-seat.py's hook verbs do, before the
// shared seat hook writes it down.  SessionStart fills in the launch's receipt first (`capture`),
// then binds the thread it proves in the seat's record (codexReconcile), which Go's listing leaves
// to a tick or Python's (codexRecord): the seat's bar reads it from its first answer.
// A Stop names the work its thread still has in flight, where the seat's server says.  A question
// going up is refused where the seat may not ask now, and an async card's questions are Python's
// to keep; a Plan-mode one is the seat asking.  A call's end is news only while the seat's fact
// is a question, which the owner's answer or approval let run: any other ends in a turn already
// running, or in one that ended, a shell the owner's Esc left running or a sub-agent's call after
// the seat's Stop, which it would bring back.
func codexHookEvent(event *run.Object, out io.Writer, refused func(seat string) (string, error),
	reconciled func(seat string)) (*run.Object, int) {
	launched, worker := os.Getenv("AGENTKIT_SESSION"), os.Getenv("AK_RUN_ROLE") == "worker"
	name, _, err := config.ResolveSession(launched)
	switch event.Str("hook_event_name") {
	case "SessionStart":
		if path := os.Getenv(codexCaptureEnv); path != "" {
			codexCapture(path, event)
			if err == nil {
				reconciled(name)
			}
		}
	case "Stop":
		// the seat's own Codex home, as its server runs this hook
		if tasks, ok := codexInFlight(os.Getenv("CODEX_HOME"), event.Str("session_id"), time.Time{}); ok {
			event.Set("background_tasks", tasks)
		}
	case "PreToolUse":
		tool := event.Str("tool_name")
		if worker || launched == "" || !codexQuestion.MatchString(tool) {
			break
		}
		why := ""
		if err == nil {
			why, err = refused(name)
		}
		switch {
		case err != nil:
			return nil, handover.Exit("adapter codex hook", handover.Here(0))
		case why != "":
			fmt.Fprintln(out, run.Line(run.Fields("decision", "block", "reason", strings.TrimRight(why, ".")))) // Codex adds its own
			return nil, 0
		case tool != "request_user_input":
			return nil, handover.Exit("adapter codex hook", handover.Here(0))
		}
	case "PostToolUse":
		if worker || launched == "" || err != nil {
			return nil, 0
		}
		if state, _, err := lifecycle.State("codex", hookfact.Standing(name)); err != nil || state != "asking" {
			return nil, 0
		}
	}
	return event, 0
}

// codexCapture records the SessionStart Codex hands this launch in its receipt, as codex.py
// `capture` does: never an id of anyone's making, and two starts that disagree leave it ambiguous.
// In place under the receipt's lock, so a stop unlinking it wins even while this runs; the hook
// never makes one.  A compaction starts a session too, and replaces no evidence.
func codexCapture(path string, event *run.Object) {
	file, err := lock.Edit(path)
	if err != nil {
		return
	}
	defer file.Close()
	data, _ := io.ReadAll(file)
	read, _ := run.Decode(data)
	receipt, _ := read.(*run.Object)
	if receipt == nil {
		return
	}
	if old := receipt.Dict("event"); old != nil && len(old.Keys()) > 0 && !run.Equal(old, event) {
		same := run.Equal(old.Get("transcript_path"), event.Get("transcript_path"))
		if was, now := old.Str("transcript_path"), event.Str("transcript_path"); !same && was != "" && now != "" {
			// Codex resolves the launch's transcript link as it resumes
			wasInfo, err := os.Stat(was)
			nowInfo, err2 := os.Stat(now)
			same = err == nil && err2 == nil && os.SameFile(wasInfo, nowInfo)
		}
		if !same || !run.Equal(old.Get("session_id"), event.Get("session_id")) || !run.Equal(old.Get("cwd"), event.Get("cwd")) {
			receipt.Set("ambiguous", true)
		}
	}
	if source := event.Get("source"); !receipt.Truthy("ambiguous") && (source == "startup" || source == "resume") {
		receipt.Set("event", event)
	}
	// the hook runs under the TUI's own login
	receipt.Set("home", codexResolved(codexHome(os.Environ())))
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return
	}
	written, err := file.WriteString(run.Encode(receipt))
	if err == nil {
		file.Truncate(int64(written))
	}
}
