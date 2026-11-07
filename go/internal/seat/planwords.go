package seat

import (
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/lifecycle"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/screen"
)

// stopWords is the output a stop answers for, shared by its marks and the last look before keys.
func stopWords(rules *screen.Rules, tail string) string {
	var output []string
	for _, line := range rules.Said(tail) {
		if !promptOpened.MatchString(line) {
			output = append(output, line)
		}
	}
	return config.Fold(strings.Join(output, " "))
}

// stopEpisode is watch.stop_episode: a blocking hook judges real turns itself, so only changed
// words buy another continuation; a harness without that hook counts each turn separately.
func stopEpisode(own string, file *run.Object) (any, error) {
	nudged, err := lifecycle.Nudged(own)
	if err != nil {
		return nil, ErrUnread
	}
	said := file.Str("stop_said")
	if !nudged {
		return said, nil
	}
	var began any
	if _, dated := file.Num("turn_began"); dated {
		began = file.Get("turn_began")
	}
	return []any{began, said}, nil
}

// goesBack is watch.goes_back. A draft or an unread screen takes no continuation, and a question,
// usage recovery or a stall the tick holds has its own rule.
func (facts climbing) goesBack() (bool, error) {
	if facts.own == "" || facts.file.Str("stop_said") == "" || facts.found.state != "at_prompt" ||
		facts.found.authority == "" || facts.file.Truthy("unasked") || facts.file.Truthy("usage_refusal") || facts.stallHeld() {
		return false, nil
	}
	episode, err := stopEpisode(facts.own, facts.file)
	return !run.Equal(facts.file.Get("stop_nudged"), episode), err
}

func openWork(facts climbing, line string) (*answer, error) {
	if line == "" {
		return nil, nil
	}
	back, err := facts.goesBack()
	if err != nil || !back {
		return nil, err
	}
	return &answer{word: "working", reason: "going back to its open work: " + line, since: facts.found.began}, nil
}

// nudgeOpenWork runs under Health's announce lock, as watch.stop_nudge does. Only an open plan
// with no recorded reason to stop or queued news joins this path; the existing confirmed send
// rechecks the composer and hook under the typing lock before its first key.
func (seat Seat) nudgeOpenWork(state string, found sight, log func(string)) (sight, error) {
	flight, _ := found.turnInFlight(seat.own)
	if flight || found.interrupted || found.stall != nil || found.login != nil {
		return found, nil
	}
	facts := climbingOf(state, seat, found, 0)
	back, err := facts.goesBack()
	if err != nil || !back || facts.notice != nil {
		return found, err
	}
	line, _, err := plan.OwedLine(seat.Name)
	if err != nil || line == "" {
		return found, err
	}
	// News owns the next prompt, including results arriving while we wait for the typing lock.
	newsOwed := func(latest climbing) bool {
		now := time.Now()
		runs, known := lookRuns(nil)(now)
		if !known {
			return true
		}
		latest.mine, latest.now = runs[seat.Name], seconds(now)
		news, err := telling(latest)
		return news != nil || err != nil
	}
	if newsOwed(facts) {
		return found, nil
	}
	_, record, err := config.ResolveSession(seat.Name)
	if err != nil {
		return found, err
	}
	ends, _, err := RecordedEnding(seat.Name, nil, record, false)
	if err != nil || ends {
		return found, err
	}
	episode, err := stopEpisode(seat.own, facts.file)
	if err != nil {
		return found, err
	}
	const why = "stopped with work open, no question and no run"
	if drying != nil {
		log("would resume " + seat.Name + ", " + why + ", with 'continue'")
		return found, nil
	}
	at := seatAt{seat.Name, seat.own, "=" + seat.Name + ":"}
	stale := func(current string) bool {
		pane := at.capture()
		latest := climbingOf(state, seat, at.sight(pane), 0)
		// Confirmed send also rechecks with our line already in the composer.
		if latest.found.state == "draft" && latest.found.typedByAk {
			latest.found.state = "at_prompt"
		}
		back, err := latest.goesBack()
		now, unread := stopEpisode(seat.own, latest.file)
		owed, failed := plan.Owes(current)
		return current != seat.Name || err != nil || unread != nil || !back || !run.Equal(now, episode) ||
			latest.found.interrupted || latest.notice != nil || newsOwed(latest) || failed != nil || !owed ||
			stopWords(eyeOf(seat.own).rules, screen.Tail(pane)) != facts.file.Str("stop_said")
	}
	if typeAtPrompt(seat.Name, "continue", nil, func(*run.Object) error { return nil }, log, stale) {
		if err := Write(seat.Name, "stop_nudged", episode); err != nil {
			return found, err
		}
		log(seat.Name + ": " + why + "; typed 'continue'")
		return seat.look(state, seconds(time.Now()))
	}
	return found, nil
}
