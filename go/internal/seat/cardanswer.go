package seat

import (
	"context"
	"errors"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/history"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// errPython ends a card's answer with nothing written: Python records it as Go does not.
var errPython = errors.New("left to Python")

// cardWait is how long a card's answer waits for the seat's notice lock before Python's hook,
// which waits off the harness's path, is left to record it.
const cardWait = 2 * time.Second

// AnswerCard is watch.hook_look for the owner's answer on the harness's own question card at
// `at`, each reply the words of a question it answers and the choices it showed with them
// (notify.answered): what the seat kept back that they answer is the owner's time and leaves it,
// and with no notice then, a needs you only the screen said is what was answered.  Only a hook in
// the seat's own pane answers.  False, with nothing written, where that is Python's to record: a
// notice standing, whose questions the card may answer; a question kept back for a turn since
// ended, which it asks first; a conversation Go cannot name; a history or seat file that cannot
// take what it writes; and a notice lock not had in time.
func AnswerCard(name string, at float64, replies [][]string) bool {
	if _, own := inPane(name); !own {
		return true
	}
	ctx, cancel := context.WithTimeout(context.Background(), cardWait)
	defer cancel()
	held := false
	err := notify.Held(ctx, name, func(current string) error {
		held = true
		return answerCard(current, at, replies)
	})
	return held && !errors.Is(err, errPython)
}

// answerCard is AnswerCard under the seat's notice lock, which the caller holds: the owner's rows
// and the questions they answer leaving the seat are one commit, so where either cannot be
// written neither is, and the answer is Python's.
func answerCard(name string, at float64, replies [][]string) error {
	file, _ := run.ReadJSON(seatFile(name))
	var kept []*run.Object
	if file != nil {
		kept = questionsKept(file.Dict("unasked"), nil)
	}
	answered, left := answeredKept(kept, replies, at)
	conversation, known := conversationOf(name)
	if notify.Standing(name) || firstOpen(left) > 0 || !known {
		return errPython
	}
	if len(answered) > 0 && history.OwnerTime(conversation, ownerTime(answered, at), func() error {
		return dropKept(name, answered)
	}) != nil {
		return errPython
	}
	if err := askKept(name, true); err != nil || notify.Standing(name) {
		return err
	}
	return notify.ScreenAnswered(name, at)
}

// answeredKept is what watch.answered_kept finds of what the seat keeps back: the questions the
// replies name, kept before `at`, every copy of each, and those left.
func answeredKept(kept []*run.Object, replies [][]string, at float64) (answered, left []*run.Object) {
	latest := map[string]*run.Object{}
	for _, question := range kept {
		latest[notify.QuestionKey(question.Str("text"))] = question
	}
	for _, question := range kept {
		// a question its card named by id is that card's, which a reply names only by that id,
		// unless a newer copy of its words went up on a card naming none
		since, dated := question.Num("at")
		named := !question.Truthy("id") || !latest[notify.QuestionKey(question.Str("text"))].Truthy("id")
		if dated && since < at && named && slices.ContainsFunc(replies, func(reply []string) bool {
			return replied(reply, question.Str("text"))
		}) {
			answered = append(answered, question)
		} else {
			left = append(left, question)
		}
	}
	return answered, left
}

// ownerTime is the owner's time those questions took, as history.owner_time writes it: each asked
// when its words were first kept, then each answered at `at`.
func ownerTime(answered []*run.Object, at float64) []history.Moment {
	asked, keys := map[string]float64{}, []string{}
	for _, question := range answered {
		key := notify.QuestionKey(question.Str("text"))
		since, _ := question.Num("at")
		if first, seen := asked[key]; seen {
			since = min(first, since)
		} else {
			keys = append(keys, key)
		}
		asked[key] = since
	}
	var moments []history.Moment
	for _, key := range keys {
		moments = append(moments, history.Moment{Kind: "asked", At: asked[key]})
	}
	for _, key := range keys {
		moments = append(moments, history.Moment{Kind: "answered", At: at, Waited: at - asked[key]})
	}
	return moments
}

// dropKept has those questions leave what the seat keeps back, and any kept since stay.
func dropKept(name string, answered []*run.Object) error {
	path := seatFile(name)
	return put(path, strings.TrimSuffix(path, ".json")+".lock", run.Line, false, func(data *run.Object) bool {
		var left []*run.Object
		for _, question := range questionsKept(data.Dict("unasked"), nil) {
			if !slices.ContainsFunc(answered, func(each *run.Object) bool {
				return each.Str("text") == question.Str("text") && run.Equal(each.Get("id"), question.Get("id")) &&
					run.Equal(each.Get("at"), question.Get("at"))
			}) {
				left = append(left, question)
			}
		}
		var rest any
		if len(left) > 0 {
			rest = keptRecord(left)
		}
		return set([]field{{"unasked", rest}}, field{"session", name})(data)
	})
}

// replied is notify.replied for a reply on the harness's card: it names that question by its
// words, alone or followed by exactly the choices the card showed with them, however the seat
// listed those; first words alone are another question's.
func replied(reply []string, question string) bool {
	if len(reply) == 0 {
		return false
	}
	said := []string{reply[0]}
	if shown := reply[1:]; len(shown) > 0 {
		for _, sep := range []string{", ", "; ", " · "} {
			for _, end := range []string{"", "."} {
				said = append(said, reply[0]+" Options: "+strings.Join(shown, sep)+end)
			}
		}
	}
	asked := notify.QuestionKey(shownWords(question))
	return slices.ContainsFunc(said, func(text string) bool { return notify.QuestionKey(shownWords(text)) == asked })
}

// conversationOf is notify.conversation_of as an owner row names it, `<harness>:<id>`, nil where
// the seat's harness says it holds none; false where Go cannot say which it holds, among them a
// seat of no record, which watch.hook_look does not find.
func conversationOf(name string) (any, bool) {
	current, record, err := config.ResolveSession(name)
	if err != nil || record == nil {
		return nil, false
	}
	own := config.SeatHarness(current)
	conversation, known := harness.Owned(own, record)
	if own == "" || !known || conversation == "" {
		return nil, own != "" && known
	}
	return own + ":" + conversation, true
}
