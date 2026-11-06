package tick

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// AuditReport gives the tick a report and its loss from the CLI's one scoreboard reader.
type AuditReport func(time.Time) (lines []string, loss string)

// audit carries a weekly report with no history database. Existing audit deliveries remain
// Python's; a fresh seat uses the same launch as an owner's, and a gone one comes back as its
// number opens it.
func (t *ticking) audit() error {
	roles, on, err := config.Audit()
	if err != nil || !on {
		return err
	}
	if !run.Historyless() {
		return errLeft
	}
	file := statePath("audit.json")
	state, err := run.ReadJSON(file)
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	if state == nil {
		state = run.NewObject()
	}
	if state.Truthy("typed") && !state.Truthy("delivered") {
		return errLeft
	}
	now := t.clock().UTC()
	year, week := now.ISOWeek()
	stamp := fmt.Sprintf("%d-W%02d", year, week)
	write := func() error { return replaceFile(file, run.Encode(state)+"\n") }
	if state.Str("week") != stamp {
		if t.report == nil {
			return errLeft
		}
		body, loss := t.report(now)
		report := statePath(filepath.Join("audit", stamp+".md"))
		if err := os.MkdirAll(filepath.Dir(report), 0o777); err != nil {
			return err
		}
		lines := append([]string{"# ak's week " + stamp, ""}, body...)
		lines = append(lines, "", strings.ToUpper(loss[:1])+loss[1:]+".")
		if err := replaceFile(report, strings.Join(lines, "\n")+"\n"); err != nil {
			return err
		}
		line := "ak's week " + stamp + ": " + loss + "; the board is at " + report + ". Build the smallest " +
			"change to ak that moves it, through the line. Quality, then speed, then cost: a gain in speed or cost while a quality measure gets worse is no win."
		state = run.Fields("week", stamp, "report", report, "line", line, "typed", nil, "delivered", nil)
		if err := write(); err != nil {
			return err
		}
		t.log.line("audit: week " + stamp + "'s board is at " + report + "; " + loss)
	}
	if state.Truthy("delivered") {
		return nil
	}
	name, record, err := config.ResolveSession("audit")
	if err != nil {
		return err
	}
	mark, _ := run.ReadJSON(statePath("seat-" + name + ".json"))
	if mark != nil && mark.Truthy("closed_by_owner") {
		if !state.Truthy("held") {
			state.Set("held", true)
			if err := write(); err != nil {
				return err
			}
			t.log.line("audit: the " + name + " seat was closed by the owner; its line about week " +
				state.Str("week") + " waits for them to open it")
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
	return reopenAudit(name)
}
