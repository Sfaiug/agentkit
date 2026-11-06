package notify

import (
	"context"
	"errors"
)

// TurnedKeptQuestion is the tick's card transition of a seat at work whose question still stands
// (notify.transition's `kept`): its needs you keeps its episode through a turn a run's result
// opens, as the same question asked again at that turn's stop is no news, so nothing is written.
// False where its card or its word is another, or no question of its own stands.
func TurnedKeptQuestion(name string, said func(string) (string, any)) (bool, error) {
	carried := false
	err := Held(context.Background(), name, func(current string) error {
		card, err := readObject(seatFile("card", current, "json"))
		if err != nil && !errors.Is(err, errNotObject) {
			return err
		}
		notice := Last(current)
		if card == nil || card.Str("word") != "needs you" || !OwnerQuestion(notice) || notice.Get("time") == nil {
			return nil
		}
		word, _ := said(current)
		carried = word == "working"
		return nil
	})
	return carried, err
}
