package tick

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// AuditReport gives the tick a report and its loss from the CLI's one scoreboard reader.
type AuditReport func(time.Time) (lines []string, loss string)

// audit carries the audit seat's line into it, as Python's watch.tell_audit: the week's, its
// report written with a bare history (weekly), else a stall's (stuck), each through the same
// steps (tellAudit). A fresh seat uses the same launch as an owner's.
func (t *ticking) audit() error {
	roles, on, err := config.Audit()
	if err != nil || !on {
		return err
	}
	if !history.Bare() {
		return errLeft
	}
	file := statePath("audit.json")
	state, err := t.weekly(file)
	if err == nil && state == nil {
		file = statePath("stuck.json")
		state, err = t.stuck(file)
	}
	if err != nil || state == nil {
		return err
	}
	write := func() error { return keepLine(file, state) }
	name, record, err := config.ResolveSession("audit")
	if err != nil {
		return err
	}
	if leftTyped(state) {
		return errLeft
	}
	mark, _ := run.ReadJSON(statePath("seat-" + name + ".json"))
	if mark != nil && mark.Truthy("closed_by_owner") {
		if !state.Truthy("held") {
			state.Set("held", true)
			if err := write(); err != nil {
				return err
			}
			t.log.line("audit: the " + name + " seat was closed by the owner; its line about " +
				about(state) + " waits for them to open it")
		}
		return nil
	}
	if record == nil {
		carried, err := seat.Ensure(name, roles, config.Repo())
		if err != nil || carried {
			return err
		}
		return errLeft
	}
	return t.tellAudit(name, state, write)
}

// weekly is Python's audit.weekly: the week's record in file while its line is to be delivered,
// nil once it is in. A new week's is written once no earlier line waits in the composer for its
// Enter.
func (t *ticking) weekly(file string) (*run.Object, error) {
	// a stall's line in the composer is sent before the week's is written to go after it
	if stall, _ := run.ReadJSON(statePath("stuck.json")); stall != nil && stall.Truthy("typed") && !stall.Truthy("delivered") {
		return nil, nil
	}
	state, err := run.ReadJSON(file)
	if err != nil && !os.IsNotExist(err) {
		return nil, err
	}
	if state == nil {
		state = run.NewObject()
	}
	now := t.clock().UTC()
	year, week := now.ISOWeek()
	stamp := fmt.Sprintf("%d-W%02d", year, week)
	if state.Str("week") != stamp && (state.Truthy("delivered") || !state.Truthy("typed")) {
		if t.report == nil {
			return nil, errLeft
		}
		body, loss := t.report(now)
		report := statePath(filepath.Join("audit", stamp+".md"))
		if err := os.MkdirAll(filepath.Dir(report), 0o777); err != nil {
			return nil, err
		}
		lines := append([]string{"# ak's week " + stamp, ""}, body...)
		lines = append(lines, "", strings.ToUpper(loss[:1])+loss[1:]+".")
		if err := replaceFile(report, strings.Join(lines, "\n")+"\n"); err != nil {
			return nil, err
		}
		line := "ak's week " + stamp + ": " + loss + "; the board is at " + report + ". Build the smallest " +
			"change to ak that moves it, through the line. Quality, then speed, then cost: a gain in speed or cost while a quality measure gets worse is no win."
		state = run.Fields("week", stamp, "report", report, "line", line, "typed", nil, "delivered", nil)
		if err := keepLine(file, state); err != nil {
			return nil, err
		}
		t.log.line("audit: week " + stamp + "'s board is at " + report + "; " + loss)
	}
	if state.Truthy("delivered") {
		return nil, nil
	}
	return state, nil
}

// keepLine writes a line's record, the week's or a stall's, as Python's audit.write and stuck.write
// do.
func keepLine(file string, state *run.Object) error {
	return replaceFile(file, run.Encode(state)+"\n")
}

// about is what the line in state tells the seat about: its week, else its stall.
func about(state *run.Object) string {
	if state.Truthy("week") {
		return "week " + state.Str("week")
	}
	return state.Str("about")
}
