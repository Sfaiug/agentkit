package notify

import (
	"errors"
	"slices"
	"strings"

	"agentkit/internal/run"
)

// Unask retires the seat's questions that begin with prefix, standing or kept back, every other
// question keeping its words and dates, as notify.clear does with a prefix and no wait.  `unkeep`
// takes them from what the seat kept back.  ErrUnread, with nothing written, where it cannot be
// carried out now as Go reads it: while another holds the seat's notice lock, or a retirement waits
// for that lock's next holder, as Python leaves one (`session_lock` carries it out, which no holder
// of Go's does), and where Go cannot read a file it touches as Python does.
func Unask(name, prefix string, unkeep func(current, prefix string) error) error {
	held := false
	err := TryHeld(name, func(current string) error {
		held = true
		if !retirementsDrained() || !touchable(current) {
			return ErrUnread
		}
		if err := unkeep(current, prefix); err != nil {
			return err
		}
		return unasked(current, prefix)
	})
	if err == nil && !held {
		return ErrUnread
	}
	return err
}

// touchable is whether Go reads the seat's file, notice and card as Python does, and its card's
// outbox event.
func touchable(name string) bool {
	_, seatErr := run.ReadJSON(seatFile("seat", name, "json"))
	_, noticeErr := run.ReadJSON(seatFile("notify", name, "json"))
	card, cardErr := readObject(seatFile("card", name, "json"))
	if errors.Is(seatErr, run.ErrLoneSurrogate) || errors.Is(noticeErr, run.ErrLoneSurrogate) ||
		cardErr != nil && !errors.Is(cardErr, errNotObject) {
		return false
	}
	if card == nil {
		return true
	}
	_, err := readEvent(cardKey(card.Get("episode")))
	return err == nil
}

// unasked takes the questions that begin with prefix from the seat's notice, which, asking nothing
// else, is over.
func unasked(name, prefix string) error {
	notice, _ := run.ReadJSON(seatFile("notify", name, "json"))
	if notice == nil || notice.Str("kind") != "needs" || notice.Truthy("seen") {
		return nil
	}
	if _, asks := notice.Get("text").(string); !asks {
		return nil
	}
	asked := questions(notice)
	left := slices.DeleteFunc(slices.Clone(asked), func(q string) bool { return strings.HasPrefix(q, prefix) })
	switch len(left) {
	case len(asked):
		return nil
	case 0:
		return over(name, notice)
	}
	notice = notice.Copy()
	listed := make([]any, len(left))
	for i, q := range left {
		listed[i] = q
	}
	notice.Set("session", name)
	notice.Set("text", strings.Join(left, also))
	notice.Set("questions", listed)
	for _, key := range []string{"asked_at", "question_times", "question_ids"} {
		if dates := notice.Dict(key); dates != nil {
			kept := run.NewObject()
			for _, at := range dates.Keys() {
				if slices.ContainsFunc(left, func(q string) bool { return questionKey(q) == at }) {
					kept.Set(at, dates.Get(at))
				}
			}
			notice.Set(key, kept)
		}
	}
	return writeNotice(name, notice)
}
