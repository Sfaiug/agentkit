package notify

import (
	"context"
	"errors"
	"io"
	"os"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// questionTransition cards a need read under its typing lock. Only a question waits for the
// owner to leave the seat: another failure may need them even while they are there.  `taken` is
// told once the card is Go's, before anything is written for it.
func questionTransition(name string, said func(string) (string, any), clock func() float64, wait float64, errOut io.Writer, isQuestion bool, question func(string, *run.Object) *run.Object, taken func(current string) error) (bool, error) {
	if os.Getenv("AK_RUN_ROLE") == "worker" {
		return true, nil
	}
	carried := false
	err := Held(context.Background(), name, func(current string) error {
		word, since := said(current)
		if word != "needs you" {
			return nil
		}
		file, err := readObject(seatFile("seat", current, "json"))
		if err != nil {
			return err
		}
		if file == nil || file.Truthy("closed_by_owner") {
			return nil
		}
		notice := question(current, file)
		if notice == nil {
			return nil
		}
		present, last, gone, known := questionActivity(current)
		present = present && isQuestion
		// a question is the one its seat's look published; a need is what the ladder says now
		if !known || isQuestion && !gone && config.Fold(file.Str("reason")) != config.Fold(notice.Str("text")) {
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
		asked := number(notice, "time")
		fresh := card.Str("word") != "needs you"
		if fresh {
			if card.Str("word") == "done" {
				return nil
			}
			card = questionEpisode(current, card, asked, since, gone)
		}
		began := card.Get("began")
		if !card.Has("began") {
			began = card.Get("since")
		}
		_, known = finite(began)
		if _, dated := finite(card.Get("since")); !dated || !known ||
			max(number(card, "answered_at"), number(notice, "earlier_answer_at")) > number(card, "since") {
			return nil
		}
		carried = true
		if err := taken(current); err != nil {
			return err
		}
		if card.Truthy("sent") {
			return nil
		}
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
		if cardHistory(card) || present || now-number(card, "left") < cardWait || now-max(number(card, "since"), asked, last) < wait {
			return nil
		}
		if gone && isQuestion {
			notice = notice.Copy()
			notice.Set("text", file.Str("reason"))
		}
		_, err = sendCard(current, card, notice, errOut)
		return err
	})
	return carried, err
}
