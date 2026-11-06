package seat

import (
	"context"
	"errors"
	"os"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	script "agentkit/internal/transcript"
)

// promptWritten is how long a prompt's own message is given to reach the seat's conversation: a
// harness may write it only after its prompt hook returns (notify.PROMPT_WRITTEN).
const promptWritten = 2 * time.Second

// A Prompt is what a seat's prompt hook heard: when, and the words.
type Prompt struct {
	At   float64
	Said string
}

// LookSoon has the seat this hook runs in looked at again, off the harness's path, as
// hooks/seat-state.sh starts it; heard, the look checks whether the prompt answers its question.
// The words go on its stdin: on its command line, a long one would never run it.
func LookSoon(heard *Prompt) {
	seat, _, _, ok := paneOf()
	if !ok {
		return
	}
	if heard == nil {
		if look := startLook(seat, ""); look != nil {
			look.Process.Release()
		}
		return
	}
	read, write, err := os.Pipe()
	if err != nil {
		return
	}
	defer read.Close()
	defer write.Close()
	look, err := lookCommand(seat, "", strconv.FormatFloat(heard.At, 'f', -1, 64))
	if err != nil {
		return
	}
	look.Stdin = read
	if look.Start() != nil {
		return
	}
	write.WriteString(heard.Said)
	look.Process.Release()
}

// answering is the part of watch.hook_look that records the owner's answer, before its word is told:
// a prompt that is no line ak typed answers by the seat's conversation, or by itself where its
// harness cannot say whose its messages are; any other look asks that conversation too.
func answering(state, name string, heard *Prompt) error {
	if heard == nil || notify.AkPrompt(name, heard.Said, notify.Last(name)) {
		_, _, err := answerWritten(state, name, seconds(time.Now()), 0)
		return err
	}
	if _, known, err := answerWritten(state, name, heard.At, promptWritten); known || err != nil {
		return err
	}
	_, err := answered(state, name, heard.At, nil)
	return err
}

// answerWritten is notify.answer_written: a message of the owner's in the seat's conversation,
// written after what it asked them, answers it.  One kept back whose turn's end is on record is
// asked first, and one whose turn still runs waits for the look that asks it.  Whether it was
// answered, and false for known where its harness cannot say whose its messages are.
func answerWritten(state, name string, at float64, wait time.Duration) (done, known bool, err error) {
	if Kept(name) {
		if err := notify.Held(context.Background(), name, func(current string) error { return askKept(current, true) }); err != nil {
			return false, true, err
		}
	}
	since, asked := notify.AskedAt(name)
	if !asked {
		return false, true, nil
	}
	_, record, err := config.ResolveSession(name)
	if err != nil || record == nil {
		return false, false, nil
	}
	if conversation, _, read := script.Typed(config.SeatHarness(name), record); !read || conversation == nil || conversation == "" {
		return false, false, nil
	}
	for deadline := time.Now().Add(wait); asked && !Kept(name); since, asked = notify.AskedAt(name) {
		said, err := notify.OwnerSaid(name)
		if errors.Is(err, notify.ErrUnread) {
			return false, false, nil
		}
		if len(said) > 0 && slices.Max(said) > since {
			typed := slices.Max(said)
			done, err := answered(state, name, at, &typed)
			return done, true, err
		}
		if !time.Now().Before(deadline) {
			break
		}
		time.Sleep(200 * time.Millisecond)
	}
	return false, true, nil
}

// answered is notify.answered, with what it lets go of once its lock is down (watch.forget): whether
// a question was answered.
func answered(state, name string, at float64, typed *float64) (bool, error) {
	done, err := notify.Answered(name, at, typed, func(current string) error { return askKept(current, true) })
	if err != nil || !done {
		return done, err
	}
	return true, nextGeneration(state, name, time.Now())
}

// askKeptBack is watch.ask_kept_back: a look that finds the seat's turn ended, at a prompt, a draft
// there or a Stop on background work, never a dialog, asks what it kept back during it.  The end goes
// on record first: a look that finds the notice lock taken leaves the asking to whoever next holds it.
func (seat Seat) askKeptBack(found sight) error {
	if !Kept(seat.Name) || found.state == "asking" || !found.composerOpen(seat.own) {
		return nil
	}
	if err := TurnEnded(seat.Name); err != nil {
		return err
	}
	return notify.TryHeld(seat.Name, func(current string) error { return askKept(current, false) })
}

// askKept is notify.ask_kept, under the notice lock: the questions the seat kept back become its
// notice, dated at their turn's end.  With `ended` it asks only those whose end is on record, which
// are the first kept: one kept since, in a turn still going, waits for its own.
func askKept(name string, ended bool) error {
	file, _ := run.ReadJSON(seatFile(name))
	if file == nil {
		return nil
	}
	kept := questionsKept(file.Dict("unasked"), nil)
	if ended {
		kept = kept[:firstOpen(kept)]
	}
	if len(kept) == 0 {
		return nil
	}
	asked := make([]notify.Kept, len(kept))
	for at, question := range kept {
		asked[at] = notify.Kept{Text: question.Str("text"), At: question.Get("at"), Ended: question.Get("ended"), ID: question.Get("id")}
	}
	if err := notify.AskKept(name, asked); err != nil {
		return err
	}
	return keptAsked(name, kept)
}

// firstOpen is the place of the first question whose turn's end is not on record.
func firstOpen(kept []*run.Object) int {
	if at := slices.IndexFunc(kept, func(question *run.Object) bool { return !question.Has("ended") }); at >= 0 {
		return at
	}
	return len(kept)
}

// keptAsked is watch.kept_asked: those questions, the first the record keeps, are a notice now, so
// they go and any kept since stay; a record replaced meanwhile drops nothing, and what was asked
// already is asked once.
func keptAsked(name string, kept []*run.Object) error {
	path := seatFile(name)
	return put(path, strings.TrimSuffix(path, ".json")+".lock", run.Line, false, func(data *run.Object) bool {
		current := questionsKept(data.Dict("unasked"), nil)
		if len(current) < len(kept) || !slices.EqualFunc(current[:len(kept)], kept, func(a, b *run.Object) bool { return a.Str("text") == b.Str("text") }) {
			return false
		}
		var left any
		if rest := current[len(kept):]; len(rest) > 0 {
			left = keptRecord(rest)
		}
		return set([]field{{"unasked", left}}, field{"session", name})(data)
	})
}

// lookKinds are what a seat its panes run on may hold beside `kinds`: what the ladder and its hooks
// read, or its look writes through a temporary beside it, or what no word hangs on.
var lookKinds = map[string][]string{"session": {"tmp"}, "seat": {"tmp"}, "hook": {"json", "tmp"}, ".hook": {"lock"}, "notify": {"json", "tmp"},
	"card": {"json", "tmp"}, "input": {"jsonl"}, "rulebook": {"md"}, "held": {"md"}, "change": {"md"}, "rules": {"md"},
	"title": {"json"}, "live": {"txt"}}

// looksKind is whether a live seat's file of that kind is one lookKinds names, or its prompt hook's
// latch mid-replace.
func looksKind(kind, suffix string) bool {
	return slices.Contains(lookKinds[kind], suffix) || kind == "stop" && strings.HasPrefix(suffix, "json.tmp.")
}

// lookFields are the seat file's keys only a look at a seat its panes run on reads: its wait and what
// it kept back, what its look writes beside its word, and what the tick keeps about its turns, which
// no word hangs on while it has no plan.
var lookFields = []string{"wait", "unasked", "holds", "switched", "stop_nudged", "parked_nudged", "reopened_at"}
