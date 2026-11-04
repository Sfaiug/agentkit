package notify

import (
	"context"
	"errors"
	"io"
	"os"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// UnansweredQuestion leaves a question with a newer owner message to Python's answer pass.
func UnansweredQuestion(name string) bool {
	notice := Last(name)
	if !OwnerQuestion(notice) {
		return false
	}
	if _, dated := finite(notice.Get("time")); !dated {
		return false
	}
	said, err := OwnerSaid(name)
	return err == nil && !slices.ContainsFunc(said, func(at float64) bool { return at > spokenAt(notice) })
}

// TurnedQuestion carries only a standing question on record. Dialogs, answered episodes and
// history stay Python's; the tick reads the word again under the same lock as a command's page.
func TurnedQuestion(name string, said func(string) (string, any)) (bool, error) {
	if os.Getenv("AK_RUN_ROLE") == "worker" {
		return true, nil
	}
	carried := false
	err := Held(context.Background(), name, func(current string) error {
		word, since := said(current)
		if word != "needs you" || !UnansweredQuestion(current) {
			return nil
		}
		notice := Last(current)
		file, err := readObject(seatFile("seat", current, "json"))
		if err != nil {
			return err
		}
		if notice == nil || file == nil || file.Str("state") == "asking" || file.Truthy("closed_by_owner") ||
			config.Fold(file.Str("reason")) != config.Fold(notice.Str("text")) {
			return nil
		}
		card, err := readObject(seatFile("card", current, "json"))
		if err != nil && !errors.Is(err, errNotObject) {
			return err
		}
		if card == nil {
			card = run.NewObject()
		}
		now := clock()
		at, dated := finite(since)
		if !dated || card.Str("word") != "needs you" && card.Get("word") != nil && at <= number(card, "since") {
			at = now
		}
		at = max(at, number(notice, "time"))
		fresh := card.Str("word") != "needs you"
		if fresh {
			if card.Str("word") == "done" {
				return nil
			}
			card = episode(card, "needs you", run.Float(at), run.Float(at))
		}
		began := card.Get("began")
		if !card.Has("began") {
			began = card.Get("since")
		}
		start, known := finite(began)
		if _, dated := finite(card.Get("since")); !dated || !known || start < installedAt() ||
			max(number(card, "answered_at"), number(notice, "earlier_answer_at")) > number(card, "since") {
			return nil
		}
		activity, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "="+current+":",
			"#{session_attached}\t#{session_activity}")
		parts := strings.Fields(activity)
		if err != nil || len(parts) != 2 {
			return nil
		}
		last, err := strconv.ParseInt(parts[1], 10, 64)
		if err != nil {
			return nil
		}
		carried = true
		if card.Truthy("sent") {
			return nil
		}
		present := parts[0] != "0"
		changed := card.Truthy("present") != present
		if changed {
			card.Set("present", present)
			card.Set("left", run.Float(now))
		}
		if fresh || changed {
			if err := writeCard(current, card); err != nil {
				return err
			}
		}
		if present || now-number(card, "left") < cardWait || now-max(number(card, "since"), float64(last)) < cardWait {
			return nil
		}
		_, err = sendCard(current, card, notice, io.Discard)
		return err
	})
	return carried, err
}
