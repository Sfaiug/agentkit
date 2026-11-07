package notify

import (
	"slices"
	"strings"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// CardNamed is notify.card_answered: the questions that notice asks which an answer on the
// harness's own question card names, each said before `at`.  One asked on a card is that card's,
// which names it only by its id, never by words, unless the seat kept its words back since under a
// card naming none (`renewed`, each kept question's latest card by its key); any other is named by
// its words (`names`).
func CardNamed(notice *run.Object, at float64, renewed map[string]any, names func(question string) bool) []string {
	ids, read := copied(notice, "question_ids", run.NewObject())
	asked, dated := copied(notice, "asked_at", run.NewObject())
	if !read || !dated {
		return nil
	}
	dates, read := copied(notice, "question_times", asked)
	if !read {
		return nil
	}
	for key, id := range renewed {
		ids.Set(key, id)
	}
	var named []string
	for _, question := range questions(notice) {
		key, said := questionKey(question), notice.Get("time")
		if dates.Has(key) {
			said = dates.Get(key)
		}
		if since, dated := run.Num(said); dated && since < at && !ids.Truthy(key) && names(question) {
			named = append(named, question)
		}
	}
	return named
}

// CardAnswered is notify.answered for an answer on the harness's own question card at `at`, under
// the seat's notice lock, which the caller holds, once what the seat kept back that it answers is
// gone: of the seat's own notice standing, only the questions the card names (CardNamed) are
// answered, each the owner's time since it was asked, in the seat's `conversation`, and every other
// stands, the notice rewritten without them.  A notice whose every question the card names is
// answered as an owner's prompt answers it; with none standing, the needs you only the screen said
// is what was answered.  Whether the notice was answered whole.
func CardAnswered(name string, at float64, renewed map[string]any, names func(question string) bool, conversation any) (bool, error) {
	notice := open(name)
	if notice == nil {
		return false, ScreenAnswered(name, at)
	}
	answered := map[string]bool{}
	for _, question := range CardNamed(notice, at, renewed, names) {
		answered[questionKey(question)] = true
	}
	if notice.Get("watcher") == true || len(answered) == 0 {
		return false, nil
	}
	left := slices.DeleteFunc(questions(notice), func(question string) bool { return answered[questionKey(question)] })
	if len(left) > 0 {
		if err := writeNotice(name, without(notice, answered, left)); err != nil {
			return false, err
		}
	} else if whole, err := answerNotice(name, notice, at); !whole || err != nil {
		return false, err
	}
	// each row after the notice that answers it, so no answer heard again counts it twice
	if asked := notice.Dict("asked_at"); asked != nil {
		for _, key := range asked.Keys() {
			if since, dated := asked.Num(key); dated && answered[key] {
				history.OwnerTime("answered", at, at-since, conversation)
			}
		}
	}
	return len(left) == 0, nil
}

// without is the notice asking only the questions left, the dates and cards of those answered
// gone with them.
func without(notice *run.Object, answered map[string]bool, left []string) *run.Object {
	rest := notice.Copy()
	rest.Set("text", strings.Join(left, also))
	listed := make([]any, len(left))
	for at, question := range left {
		listed[at] = question
	}
	rest.Set("questions", listed)
	for _, field := range []string{"asked_at", "question_times", "question_ids"} {
		kept := run.NewObject()
		if dated := notice.Dict(field); dated != nil {
			for _, key := range dated.Keys() {
				if !answered[key] {
					kept.Set(key, dated.Get(key))
				}
			}
		}
		rest.Set(field, kept)
	}
	return rest
}
