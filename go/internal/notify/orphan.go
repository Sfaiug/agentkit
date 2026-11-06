package notify

import (
	"context"
	"errors"
	"fmt"
	"io"

	"agentkit/internal/run"
)

// Orphan asks the owner what a seat nothing is left of would be asked, as Python's shaped does
// with the event `source`: kept as the seat's notice once for that event, beside any question
// still standing there, and carded at once by the transition on the word `word` climbs the
// seat's ladder to under its lock.  `taken` is told once the ask is Go's, before anything is
// written for it.  It answers the exit code and whether Go decided it: where a file it reads is
// one Go cannot read as Python does, `word` cannot climb or `taken` fails, nothing is written;
// where the word is no `needs you`, the notice stands for Python's transition to card.
func Orphan(name, text, source string, word func(string) (string, any), taken func() error, out, errOut io.Writer) (int, bool) {
	if Suppressed(false, errOut) {
		return 0, taken() == nil // a worker asks nothing, which Python's announce counts as said
	}
	_, ownerErr := secret("AGENTKIT_DISCORD_USER_ID", "discord_user_id")
	if _, webhookErr := webhook(false, io.Discard); ownerErr != nil || webhookErr != nil {
		return 0, false
	}
	code, decided := 0, false
	err := Held(context.Background(), name, func(current string) error {
		previous, err := run.ReadJSON(seatFile("notify", current, "json"))
		if errors.Is(err, run.ErrLoneSurrogate) {
			return nil
		}
		if previous != nil {
			if _, asks := previous.Get("text").(string); previous.Str("kind") != "needs" || !asks {
				previous = nil // no question of the seat's: what Python's last reads as none
			}
		}
		notice := previous // its event's notice is recorded once
		if previous == nil || !run.Equal(previous.Get("source"), source) {
			var readable bool
			if notice, readable = said(current, []Kept{{Text: text}}, previous, false); !readable {
				return nil
			}
			notice.Set("source", source)
		}
		card, err := readObject(seatFile("card", current, "json"))
		if errors.Is(err, errNotObject) {
			card, err = nil, nil
		}
		if card == nil {
			card = run.NewObject()
		}
		_, eventErr := readEvent(cardKey(card.Get("episode")))
		if climbed, _ := word(current); err != nil || card.Str("word") == "needs you" && eventErr != nil || climbed == "" || taken() != nil {
			return nil
		}
		decided, code = true, 1
		if notice != previous {
			if err := writeNotice(current, notice); err != nil {
				fmt.Fprintf(errOut, "notify: record could not be persisted (%s); retry required\n", failed(err))
				return nil
			}
		}
		if climbed, _ := word(current); climbed != "needs you" {
			decided, code = false, 0
			return nil
		}
		if code, err = page(current, card, notice, false, errOut); err != nil {
			code = 1
			fmt.Fprintf(out, "WARN card transition for %s failed (%s); retry required\n", current, failed(err))
		}
		return nil
	})
	if err != nil && decided {
		return 1, true
	}
	return code, decided
}
