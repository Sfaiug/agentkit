package seat

import (
	"cmp"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/hookfact"
	"agentkit/internal/lifecycle"
	"agentkit/internal/run"
	"agentkit/internal/screen"
	script "agentkit/internal/transcript"
)

// hookState is lifecycle.state: the state the harness's manifest gives the fact, the event as a
// mark names it, the fact's words and when it was heard; none for a fact no moment dates.
func hookState(own string, fact hookfact.Fact) (state, event, spoken string, when float64) {
	state, event, _ = lifecycle.State(own, fact)
	if state == "" || fact.At == 0 {
		return "", "", "", 0
	}
	return state, event, cmp.Or(config.Fold(fact.Text), config.Fold(fact.Event)), fact.At
}

// classify is watch.classify: what a live seat is doing, since when, and what decided it.  The hook
// decides the states its manifest reserves for it, except where a rule positively names another.  A
// harness reports a question going up and nothing when it comes down, so where its hooks own
// `working`, a rule reading anything but a question means the question was answered and the turn
// that asked runs on.  With neither a hook fact nor a rule, nothing says `working`, and nothing knows
// since when.  `ended` is when the owner stopped the turn with no Stop, nil for never.
func classify(own string, read screen.Reading, fact hookfact.Fact, previous *run.Object, now float64, ended *float64) sight {
	authority := eyeOf(own).authority
	hooked, event, spoken, when := hookState(own, fact)
	if hooked == "asking" && read.State != "" && read.State != "asking" && authority["working"] == "hooks" {
		hooked, spoken = "working", "its question was answered; the turn that asked it runs on"
	}
	stopped := (hooked == "working" || hooked == "asking") && ended != nil && *ended >= when
	if stopped { // Esc ends a turn with no Stop, a question's turn too: the dialog goes with it
		hooked, spoken = "at_prompt", "the owner interrupted its turn"
	}
	found := sight{state: "at_prompt", rule: "none", evidence: "no hook fact and no screen rule matched"}
	switch {
	case hooked != "" && authority[hooked] == "hooks" && (read.State == "" || read.State == hooked):
		found = sight{state: hooked, authority: "hook", rule: event, evidence: spoken}
		found.since, found.began = run.Float(when), run.Float(when)
	case read.State != "":
		found = sight{state: read.State, authority: "screen", rule: read.Rule, evidence: read.Evidence}
		var began any = run.Float(now)
		opened, dated := run.Num(previous.Get("opened_at"))
		_, carried := run.Num(previous.Get("began"))
		switch {
		case previous.Str("state") == found.state && carried:
			began = previous.Get("began")
		case previous.Get("state") == nil && dated && opened <= now:
			// first sight: it has been so at least since it was last opened
			began = previous.Get("opened_at")
		}
		found.since, found.began = began, began
	}
	found.interrupted = stopped || slices.Contains(lifecycle.Marked(own, "interrupt"), event)
	if hooked != "" {
		found.hooked, found.hookedAt, found.hookedEvent = hooked, run.Float(when), event
	}
	return found
}

// endedAt is when the owner stopped the turn its hooks say runs or asked in, as its conversation
// records that (watch.interrupted_at), or as a prompt put back in the composer word for word says
// it, which nothing records (watch.cancelled): seen now, and never before the turn it ends.  Nil
// for neither, and for a fact that spoke while this read, which is a newer turn.
func endedAt(name, own string, record *run.Object, rules *screen.Rules, pane string, fact hookfact.Fact, now float64) *float64 {
	hooked, _, _, when := hookState(own, fact)
	if hooked != "working" && hooked != "asking" {
		return nil
	}
	last := harness.LastMessage(own, record.Str("conversation"), record.Str("cwd"), record.Str("account"))
	if last == nil {
		return nil
	}
	ended := harness.Moment(last.Get("timestamp"))
	if !harness.Interrupts(own, last) || ended == 0 {
		asked := script.Prompted(own, last)
		held, drawn := rules.ComposerDraft(pane)
		if asked.Text == "" || asked.At == 0 || pane == "" || !drawn || held != screen.Unspaced(asked.Text) {
			return nil
		}
		ended = max(now, when)
	}
	if again := harness.For(own).HookFact(name); again.At != fact.At || again.Event != fact.Event || again.Kind != fact.Kind {
		return nil
	}
	return &ended
}

// turnInFlight is watch._turn_in_flight: whether a harness turn runs now, and since when.  A harness
// whose manifest reserves `working` to its hooks is the authority on its own turns, even while its
// screen still draws the composer; a Stop on background work is a wait whose end starts the next
// turn; and where `working` is the screen's, a screen nothing reads is no seat at its prompt.
func (found sight) turnInFlight(own string) (bool, any) {
	authority := eyeOf(own).authority
	if found.hooked == "working" && (authority["working"] == "hooks" || found.onBackground(own)) {
		return true, found.hookedAt
	}
	if found.state == "working" || authority["working"] == "screen" && found.state == "at_prompt" && found.rule == "none" {
		return true, found.began
	}
	return false, nil
}

// onBackground is whether a Stop on background work its manifest marks is the last the hooks said.
func (found sight) onBackground(own string) bool {
	return slices.Contains(lifecycle.Marked(own, "background"), found.hookedEvent)
}

// composerOpen is watch._composer_open: its turn is over, or it stopped on background work, whose
// composer takes a line at once.
func (found sight) composerOpen(own string) bool {
	flight, _ := found.turnInFlight(own)
	return !flight || found.onBackground(own)
}

// typedByAk is whether the composer holds whole the last line ak typed there, which is ak's own to
// send, not the owner's unsent text (watch.unsent's composer_holds).
func typedByAk(name string, rules *screen.Rules, pane string) bool {
	last := ""
	for sent := range script.Entries(ownFile("input", name)) {
		last = screen.Unspaced(sent.Str("text"))
	}
	held, drawn := rules.ComposerDraft(pane)
	return drawn && last != "" && held == last
}
