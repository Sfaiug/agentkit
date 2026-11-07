package notify

import (
	"context"
	"errors"
	"math"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// A Kept is a question a seat kept back for its turn's end: its words, when it said them and when
// that turn ended, each null where its record holds none, and the card that asked it.
type Kept struct {
	Text          string
	At, Ended, ID any
}

// Last is the seat's notice while it stands, nil otherwise (notify.last).
func Last(seat string) *run.Object { return open(seat) }

// Questions are those a needs notice asks, in the order asked.
func Questions(notice *run.Object) []string { return questions(notice) }

// OwnerQuestion is whether the notice is a question of the seat's: only a watcher's alerts are not,
// which have their own latches (watch.owner_question).
func OwnerQuestion(notice *run.Object) bool {
	return notice != nil && notice.Str("kind") == "needs" && notice.Get("watcher") != true
}

// AkPrompt is whether the prompt is a line ak typed, not the owner's answer to the notice, nil for none.
func AkPrompt(name, said string, notice *run.Object) bool {
	return notice != nil && akPrompt(name, said, notice)
}

// TryHeld runs fn holding the seat's typing lock under the name it goes by now, or nothing while
// another holds it (notify.session_lock with wait=False): it never waits, as a typer may hold it.
func TryHeld(name string, fn func(current string) error) error {
	current, _, err := config.ResolveSession(name)
	if err != nil {
		return err
	}
	if err := config.EnsureDirs(); err != nil {
		return err
	}
	held, err := lock.Try(seatFile("notify", current, "lock"))
	if errors.Is(err, lock.ErrHeld) {
		return nil
	}
	if err != nil {
		return err
	}
	defer held.Close()
	if now, _, err := config.ResolveSession(name); err != nil || now != current {
		return err
	}
	return fn(current)
}

// latest is the latest of those moments, false where one of them is none.
func latest(asked []Kept, moment func(Kept) any) (float64, bool) {
	most, known := math.Inf(-1), len(asked) > 0
	for _, question := range asked {
		at, dated := run.Num(moment(question))
		known = known && dated
		most = max(most, at)
	}
	return most, known
}

// spokenAt is the latest moment any question the notice asks was said (notify.spoken_at).
func spokenAt(notice *run.Object) float64 {
	if at, said := notice.Num("said_at"); said {
		return at
	}
	return number(notice, "time")
}

// AskKept is the seat's kept questions as its notice, under its notice lock, which the caller holds.
func AskKept(name string, asked []Kept) error {
	previous, err := run.ReadJSON(seatFile("notify", name, "json"))
	if errors.Is(err, run.ErrLoneSurrogate) {
		return err
	}
	if previous != nil {
		if _, asks := previous.Get("text").(string); previous.Str("kind") != "needs" || !asks {
			previous = nil // no question of the seat's: what Python's last reads as none
		}
	}
	notice, readable := said(name, asked, previous, true)
	if !readable {
		return ErrUnread
	}
	return writeNotice(name, notice)
}

// AskedAt is when what the owner would answer in that seat was said: its own question standing, else
// a needs you only the screen said, unanswered; false where neither stands (notify.asked_at).
func AskedAt(name string) (float64, bool) {
	if notice := open(name); notice != nil {
		_, dated := notice.Num("time")
		return spokenAt(notice), dated && OwnerQuestion(notice)
	}
	card, _ := readObject(seatFile("card", name, "json"))
	if card == nil || card.Str("word") != "needs you" {
		return 0, false
	}
	since, dated := card.Num("since")
	return since, dated && number(card, "answered_at") <= since
}

// Answered is the owner submitting a prompt at `at` (notify.answered): only the seat's question
// already standing is answered, on the notice, so a later line of ak's own or a rename cannot reopen
// it.  With none standing, the needs you only the screen said is what was answered, and its card keeps
// the answer.  A question kept back whose turn's end is on record is the one they read at its stop:
// `ask` asks it here first, whoever held this lock when it ended.  `typed` dates a message of the
// owner's read from the conversation, which answers only what was asked before it.  Whether a question
// was answered.  The owner's time on the scoreboard (history.owner_time) is left to Python's database.
func Answered(name string, at float64, typed *float64, ask func(current string) error) (done bool, err error) {
	err = Held(context.Background(), name, func(current string) error {
		if err := ask(current); err != nil {
			return err
		}
		if typed != nil {
			since, asked := AskedAt(current)
			if !asked || !(*typed > since) {
				return nil
			}
		}
		notice := open(current)
		if notice != nil && notice.Get("watcher") == true {
			return nil
		}
		if notice == nil {
			return ScreenAnswered(current, at)
		}
		card, err := readObject(seatFile("card", current, "json"))
		if err != nil && !errors.Is(err, errNotObject) {
			return err
		}
		if card == nil {
			card = run.NewObject()
		}
		isNeeds := card.Str("word") == "needs you"
		since, dated := card.Num("since")
		answered := notice.Copy()
		answered.Set("answered_at", run.Float(at))
		if !resolved(answered) {
			return nil
		}
		if isNeeds && dated && at > since {
			if err := retire(card); err != nil {
				return err
			}
		}
		if err := writeNotice(current, answered); err != nil {
			return err
		}
		done = true
		return nil
	})
	return done, err
}

// ScreenAnswered is the owner answering at `at`, with no notice of the seat's standing, under its
// notice lock, which the caller holds: the needs you only the screen said is what was answered, and
// its card keeps the answer, retired where it went up before it.
func ScreenAnswered(name string, at float64) error {
	card, err := readObject(seatFile("card", name, "json"))
	if err != nil && !errors.Is(err, errNotObject) {
		return err
	}
	if card == nil || card.Str("word") != "needs you" {
		return nil
	}
	if since, dated := card.Num("since"); dated && at > since {
		if err := retire(card); err != nil {
			return err
		}
	}
	card.Set("answered_at", run.Float(at))
	return writeCard(name, card)
}
