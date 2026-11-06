package notify

import "agentkit/internal/run"

// A done's receipt survives intervening work. Only a completion covering new
// outcomes opens another episode, including when the word stayed done throughout.
func planCard(name string, card *run.Object, word string, since any, outcomes func(string) ([]any, error)) (bool, error) {
	if word != "done" {
		if card.Str("word") != "done" || word == "" || word == "needs you" {
			return false, nil
		}
		at, dated := finite(since)
		if !dated || at <= number(card, "since") {
			since = run.Float(clock())
		}
		return true, writeCard(name, episode(card, word, since, since))
	}
	work, err := outcomes(name)
	if err != nil {
		return false, nil
	}
	record, err := run.ReadJSON(seatFile("session", name, "json"))
	if err != nil || record == nil {
		return false, nil
	}
	var completion any
	covered := false
	if record.Get("created") != nil && len(work) > 0 {
		completion, covered, err = doneCompletion(name, record.Get("created"), work, card)
		if err != nil {
			return false, err
		}
	}
	newWord := card.Str("word") != "done" || completion != nil && card.Truthy("completed") &&
		card.Truthy("sent") && !run.Equal(card.Get("completed"), completion)
	if !newWord && (card.Truthy("sent") || completion == nil && card.Str("closed") == "Done") {
		return true, nil
	}
	if _, dated := finite(since); !dated {
		since = run.Float(clock())
	}
	ended := card
	if newWord {
		card = episode(card, "done", since, since)
	}
	seat, _ := run.ReadJSON(seatFile("seat", name, "json"))
	past := cardHistory(card) || seat != nil && seat.Truthy("closed_by_owner")
	covered = covered || run.Equal(card.Get("completed"), completion)
	var done *intent
	if !past && (completion == nil || !covered) {
		if done, err = intentOf(name, work); err != nil {
			return false, nil
		}
	}
	if newWord && ended.Str("word") == "needs you" {
		if err := retire(ended); err != nil {
			return false, err
		}
	}
	if past {
		if newWord {
			return true, writeCard(name, card)
		}
		return true, nil
	}
	card.Set("closed", "Done")
	if completion == nil {
		done.record()
		return true, writeCard(name, card)
	}
	if covered {
		run.SetAll(card, "sent", true, "completed", completion)
		return true, writeCard(name, card)
	}
	done.record()
	return true, sendDone(name, card, completion)
}
