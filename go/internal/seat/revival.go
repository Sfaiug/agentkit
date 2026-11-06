package seat

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/hookfact"
	"agentkit/internal/lifecycle"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

const (
	// QuestionContinue is watch.ASKED_LINE, also recognized by the tick's held-lines row.
	QuestionContinue = "Your process was ended, not by you, while your question to the owner was still open. Ask it again."
	freshContinue    = "; this seat was started fresh because its earlier conversation could not be resumed"
	deathBackoff     = 600
	deathWindow      = 3600
	revivalWarmup    = 10 * time.Second
)

// Warmup is the time a newly opened harness gets before its first line (watch.INBOX_WARMUP).
const Warmup = 10 * time.Second

// Revival is a seat at the revival row's reading, including those only their records hold.
type Revival struct {
	Name                string
	Live, Closed, Owing bool
	CanOpen, Fresh      bool // reopened as its number opens it, on its own conversation or a fresh one
	Supported           bool // Go opens this harness and owns this death's recovery
	Failed              bool // a failed revival still needs the owner
	File                *run.Object
}

func (home Home) Revivals() []Revival {
	var seats []Revival
	for _, each := range home.Seats {
		_, record, _ := config.ResolveSession(each.Name)
		file, _ := run.ReadJSON(seatFile(each.Name))
		if file == nil {
			file = run.NewObject()
		}
		state := filepath.Join(config.Home(), "state")
		back, canOpen := comingBack(state, each.Name, record, each.held, false)
		supported := each.supportsRunRevival(record)
		seats = append(seats, Revival{Name: each.Name, Live: each.live, Closed: each.closed || each.asleep,
			Owing:   !each.restingGone(),
			CanOpen: canOpen, Supported: supported, Fresh: back.conversation == "" || !back.opened, File: file,
			Failed: revivalFailure(notify.Last(each.Name))})
	}
	return seats
}

// A failed automatic reopen outranks its runs: only the owner can bring this seat back.
func failedRevival(facts climbing) (*answer, error) {
	if facts.gone != nil && !facts.gone.closed && revivalFailure(facts.notice) {
		return &answer{word: "needs you", reason: config.Fold(facts.notice.Str("text")), since: facts.notice.Get("time")}, nil
	}
	return nil, nil
}

func revivalFailure(notice *run.Object) bool {
	return notice != nil && strings.HasPrefix(notice.Str("source"), "revive:")
}

// Files a launch leaves remain readable when that harness dies again.
func revivalKind(kind, suffix string) bool {
	return suffix == "md" && slices.Contains([]string{"rulebook", "held", "change", "rules", "handover"}, kind) ||
		suffix == "txt" && slices.Contains([]string{"live", "refused"}, kind) || kind == "notify" && suffix == "json"
}

// restingGone is whether the revival leaves a seat gone (watch.revive_seats): one its end cut off
// nothing of, where its own question standing is a turn cut off that a conversation of its own
// reopens on (watch.cut_off), as one its revival was paged as failing stays the revival's; any
// other needs you is no turn of its.
func (seat Seat) restingGone() bool {
	if seat.live || seat.closed {
		return true
	}
	notice := notify.Last(seat.Name)
	if seat.Word == "working" || !seat.unowned && notify.OwnerQuestion(notice) || revivalFailure(notice) {
		return false
	}
	return seat.cutNothing()
}

// cutNothing is whether the seat's end cut off no turn, question or background work its last look
// or newer hook says it had (watch.cut_off).
func (seat Seat) cutNothing() bool {
	file := revivalFile(seat.Name)
	fact := seat.reader.HookFact(seat.Name)
	hooked, event, err := lifecycle.State(seat.own, fact)
	found := sight{state: file.Str("state"), rule: file.Str("rule"), hooked: file.Str("hooked"), hookedEvent: file.Str("hooked_event")}
	if hooked != "" && fact.At != 0 && fact.At != at(file.Get("hooked_at")) {
		found = sight{state: hooked, hooked: hooked, hookedEvent: event}
	}
	flight, _ := found.turnInFlight(seat.own)
	return err == nil && found.state != "asking" && !flight && len(hookfact.Standing(seat.Name).Holds) == 0 &&
		!file.Truthy("holds") && !file.Truthy("reopened_at")
}

func revivalFile(name string) *run.Object {
	file, _ := run.ReadJSON(seatFile(name))
	if file == nil {
		return run.NewObject()
	}
	return file
}

func (seat Seat) hasActiveRun() bool {
	return slices.ContainsFunc(seat.mine, func(each ran) bool { return run.Active(each.record) || each.going() })
}

// Only an owned, unanswered question with no background work joins this recovery pass. Its
// old screen and hooks cannot change the continuation: the standing question comes first.
func (seat Seat) revivalQuestion() bool {
	file := revivalFile(seat.Name)
	record, _ := run.ReadJSON(ownFile("session", seat.Name))
	return record != nil && conversationOwned(seat.reader, record) && notify.UnansweredQuestion(seat.Name) && !file.Truthy("holds") &&
		len(hookfact.Standing(seat.Name).Holds) == 0 && !seat.hasActiveRun()
}

// Question revival leaves a project's refresh to Reopen.
func (seat reopening) launchable(record map[string]any) bool {
	opens := harness.Relaunches(seat.model.Harness)
	_, checkout := os.Lstat(filepath.Join(seat.cwd, ".git"))
	repo, _ := record["repo"].(string)
	return opens && repo == "" && checkout != nil
}

// ReviveQuestions is watch.revive_seats at each seat's turn. Other interrupted work stays
// Python's; reviving names the seats the run revival takes. A live seat clears its death history,
// and a stopped or sleeping seat stays down.
func (home Home) ReviveQuestions(now time.Time, reviving map[string]string, log func(string), errOut io.Writer) (bool, error) {
	for _, seat := range home.Seats {
		file := revivalFile(seat.Name)
		if seat.live {
			if file.Truthy("reopened_at") {
				if err := Write(seat.Name, "reopened_at", nil); err != nil {
					return true, err
				}
			}
			continue
		}
		if seat.closed || seat.asleep || seat.restingGone() || seat.waitsGone() || reviving[seat.Name] != "" {
			continue
		}
		if !seat.revivalQuestion() {
			return false, nil
		}
		carried := false
		err := under(filepath.Join(config.Home(), "state", "watch.lock"), func() error {
			var err error
			carried, err = seat.reviveQuestion(now, log, errOut)
			return err
		})
		if err != nil || !carried {
			return carried, err
		}
	}
	return true, nil
}

func (seat Seat) reviveQuestion(now time.Time, log func(string), errOut io.Writer) (bool, error) {
	file := revivalFile(seat.Name)
	if file.Truthy("stopped_at") || file.Truthy("closed_by_owner") {
		return true, nil
	}
	deaths, ok := revivalDeaths(file.Get("reopened_at"))
	if !ok {
		return false, nil
	}
	died := seconds(now)
	if len(deaths) > 2 || len(deaths) > 0 && died-at(deaths[len(deaths)-1]) < deathBackoff {
		return true, nil
	}
	deaths = slices.DeleteFunc(deaths, func(when any) bool { return died-at(when) >= deathWindow })
	if len(deaths) == 2 {
		if err := Write(seat.Name, "reopened_at", append(deaths, run.Float(died))); err != nil {
			return true, err
		}
		return seat.revivalFailed(died, "it died again both times it was reopened within the hour", log, errOut)
	}
	_, record, err := config.ResolveSession(seat.Name)
	if err != nil || record == nil {
		return false, nil
	}
	back, known := comingBack(filepath.Join(config.Home(), "state"), seat.Name, record, seat.held, true)
	if !known || !back.launchable(record) || file.Truthy("owed_lines") && !revivalLines(file) {
		return false, nil
	}
	text, err := Rulebook(seat.Name)
	if err != nil {
		return false, nil
	}
	rulebook := filepath.Join(config.Home(), "state", "rulebook-"+seat.Name+".md")
	if err := os.WriteFile(rulebook, []byte(text), 0o666); err != nil {
		return true, err
	}
	cmd, conversation, known := back.command([]string{"AGENTKIT_RULEBOOK=" + rulebook})
	if !known {
		return false, nil
	}
	held, exited, known := find(seat.Name, record)
	if !known {
		return false, nil
	}
	if err := reconcile(filepath.Join(config.Home(), "state"), []Seat{seat}, true); err != nil {
		return true, err
	}
	if err := Write(seat.Name, "reopened_at", append(deaths, run.Float(died))); err != nil {
		return true, err
	}
	name, line := seat.Name, QuestionContinue
	started := !held || exited
	if started {
		back.held = held
		log(back.said())
		name, err = back.launch(filepath.Join(config.Home(), "state"), rulebook, cmd, conversation)
		if err != nil {
			return seat.revivalFailed(died, err.Error(), log, errOut)
		}
		if !back.opened {
			line += freshContinue
		}
	}
	if err := oweRevivalLine(name, line); err != nil {
		return true, err
	}
	if started {
		time.Sleep(revivalWarmup)
	}
	carried, err := tellRevivalLine(name, log)
	log("reopened " + name + " and asked it to go on with its turn")
	return carried, err
}

func (seat Seat) revivalFailed(died float64, why string, log func(string), errOut io.Writer) (bool, error) {
	text := fmt.Sprintf("Its orchestrator session %s is gone in the middle of a turn or a question to you. agentkit tried to reopen the seat and could not: %s. Press its number in the menu, then say: continue.", seat.Name, why)
	source := "revive:" + seat.Name + ":turn:" + strconv.FormatInt(int64(died), 10)
	carried, err := notify.Needs(seat.Name, text, source, true, Published, errOut)
	if err == nil && carried {
		log("could not reopen " + seat.Name + "; asked the user to go on with its turn")
	}
	return carried, err
}

// Older installs kept one death rather than a list. Keep its value, then use Python's
// backoff, lifetime bound and hour window before adding another death.
func revivalDeaths(value any) ([]any, bool) {
	if value == nil {
		return nil, true
	}
	deaths, listed := value.([]any)
	if !listed {
		deaths = []any{value}
	}
	return slices.Clone(deaths), !slices.ContainsFunc(deaths, func(when any) bool {
		_, known := run.Num(when)
		return !known
	})
}
