package seat

import (
	"cmp"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
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
// conversation its own, not closed by the owner, and cut off owing (watch.cut_off) or owing work
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
		line, known := seat.cutLine()
		owes, err := seat.owesWork()
		if !known || line == "" && err != nil {
			return nil, false
		}
		if line == "" && !owes {
			continue
		}
		_, fields, _ := config.ResolveSession(seat.Name)
		comeback, known := comingBack(state, seat.Name, fields, false, true)
		if !known || !comeback.launchable(fields) || !owedReadable(revivalFile(seat.Name)) {
			return nil, false
		}
		back = append(back, Comeback{seat.Name, seat.path, line, comeback})
	}
	return back, true
}

// cutLine is the line a seat cut off owing is told once back (watch.cut_off): it asked, its
// question on its screen or standing in its notices, or it was in a turn; after either, or alone,
// the background work its process held, which alone owes unless it is only a watch.  "" where it
// owes none of it.
func (seat Seat) cutLine() (string, bool) {
	found, err := seat.lastSeen()
	if err != nil {
		return "", false
	}
	var said []string
	if found.state == "asking" || notify.OwnerQuestion(notify.Last(seat.Name)) {
		said = append(said, QuestionContinue)
	} else if flight, _ := found.turnInFlight(seat.own); flight {
		said = append(said, MidturnContinue)
	}
	work := holding(seat.Name)
	if len(said) == 0 && !slices.ContainsFunc(work, func(kind string) bool { return kind != "monitor" }) {
		return "", true
	}
	if len(work) > 0 {
		said = append(said, fmt.Sprintf(heldContinue, strings.Join(work, ", ")))
	}
	return strings.Join(said, " "), true
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
	back, told := comeback.back, []string{"AGENTKIT_RULEBOOK=" + rulebook}
	resumed := back.conversation != "" && back.opened
	if resumed && comeback.Line != "" {
		told = append(told, "AGENTKIT_FIRST_PROMPT="+comeback.Line)
	}
	cmd, conversation, known := back.command(told)
	if !known {
		return false, nil
	}
	if err := claim(); err != nil {
		return true, err
	}
	at := seconds(time.Now())
	if _, err := back.launch(state, rulebook, cmd, conversation); err != nil || !resumed || comeback.Line == "" {
		return true, err
	}
	mark := run.Fields("boot", boot, "at", run.Float(at), "name", comeback.Name, "line", comeback.Line)
	if launch, _ := config.Section(back.model.Harness, "launch"); launch["first_prompt"] == true {
		mark.Set("launched", true)
	}
	return true, Write(comeback.Name, "midturn", mark)
}
