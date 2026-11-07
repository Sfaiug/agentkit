package seat

import (
	"cmp"
	"os"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

// A Comeback is a seat a reboot cut off owing work, as watch.resume_after_boot finds it: where it
// ran, and the line it goes on with once back, "" for none.
type Comeback struct {
	Name, Cwd, Line string
	back            reopening
}

// AfterBoot is every seat resume_after_boot reopens, by name, but those attempted: absent, its
// conversation its own, not closed by the owner, and cut off owing (owing) or owing work
// (watch.owes_work).  False where one hangs on what Go does not read, or opens it as Go does not:
// runs of its own, a project's checkout.
func (home Home) AfterBoot(attempted []any) ([]Comeback, bool) {
	state := filepath.Join(config.Home(), "state")
	seats := slices.SortedFunc(slices.Values(home.records), func(a, b Seat) int { return cmp.Compare(a.Name, b.Name) })
	var back []Comeback
	for _, seat := range seats {
		record, _ := run.ReadJSON(ownFile("session", seat.Name))
		if seat.held || seat.live || slices.Contains(attempted, any(seat.Name)) || record == nil ||
			!conversationOwned(seat.reader, record) || revivalFile(seat.Name).Truthy("closed_by_owner") {
			continue
		}
		cut, known := seat.owing()
		owes, err := seat.owesWork()
		if !known || cut.line == "" && err != nil {
			return nil, false
		}
		if cut.line == "" && !owes {
			continue
		}
		_, fields, _ := config.ResolveSession(seat.Name)
		comeback, known := comingBack(state, seat.Name, fields, false, true)
		if !known || !comeback.launchable(fields) || !owedReadable(revivalFile(seat.Name)) {
			return nil, false
		}
		back = append(back, Comeback{seat.Name, seat.path, cut.line, comeback})
	}
	return back, true
}

// owesWork is whether a seat nobody is in still owes work (watch.owes_work): a notice standing, its
// plan owing a line or a question kept back (still_owed); ErrUnread where only its own runs could
// say.
func (seat Seat) owesWork() (bool, error) {
	if notify.Last(seat.Name) != nil || revivalFile(seat.Name).Truthy("unasked") {
		return true, nil
	}
	if _, owes, err := plan.OwedLine(seat.Name); owes || err != nil {
		return owes, err
	}
	if len(seat.mine) > 0 {
		return false, ErrUnread
	}
	return false, nil
}

// Resume opens the seat again where it ran, on the conversation its record names, as orch.resume
// does for the tick, claim run just before its launch: where that conversation has a past it opens
// on the comeback's line, which the rebooted turns row is marked to see through (watch.relaunched).
// False, with nothing claimed, where Go has no command for it.
func (comeback Comeback) Resume(boot string, claim func() error) (bool, error) {
	text, err := Rulebook(comeback.Name)
	if err != nil {
		return false, nil
	}
	state := filepath.Join(config.Home(), "state")
	rulebook := filepath.Join(state, "rulebook-"+comeback.Name+".md")
	if err := os.WriteFile(rulebook, []byte(text), 0o666); err != nil {
		return true, err
	}
	back := comeback.back
	if back.conversation != "" && back.opened {
		back.line = comeback.Line
	}
	cmd, conversation, known := back.command([]string{"AGENTKIT_RULEBOOK=" + rulebook})
	if !known {
		return false, nil
	}
	if err := claim(); err != nil {
		return true, err
	}
	at := seconds(time.Now())
	if _, err := back.launch(state, rulebook, cmd, conversation); err != nil || back.line == "" {
		return true, err
	}
	return true, relaunched(comeback.Name, back.model.Harness, back.line, at, boot)
}
