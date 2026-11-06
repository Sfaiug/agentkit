package seat

import (
	"errors"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/history"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// errNoticed ends a card's answer once a notice stands: which of a notice's questions a card
// answers is Python's (notify.card_answered).
var errNoticed = errors.New("a notice stands")

// CardCarried is whether Go records the owner's answer on that seat's own question card as Python
// does: not where a notice stands, or waits to be asked of what the seat kept back for a turn since
// ended, for that card to answer, nor where Go cannot say which conversation the seat holds, which
// the owner's rows name.
func CardCarried(name string) bool {
	file, _ := run.ReadJSON(seatFile(name))
	if notify.Standing(name) || file != nil && firstOpen(questionsKept(file.Dict("unasked"), nil)) > 0 {
		return false
	}
	_, known := conversationOf(name)
	return known
}

// cardAnswered is notify.answered for the owner's answer on the harness's own question card at
// `at`, each reply the words of a question it answers and the choices it showed with them: what
// the seat kept back that they answer is the owner's time, what it kept back for a turn since
// ended is asked, and with no notice then, a needs you only the screen said is what was answered.
func cardAnswered(name string, at float64, replies [][]string) error {
	_, err := notify.Answered(name, at, nil, func(current string) error {
		if err := answeredKept(current, replies, at); err != nil {
			return err
		}
		if err := askKept(current, true); err != nil || !notify.Standing(current) {
			return err
		}
		return errNoticed
	})
	if errors.Is(err, errNoticed) {
		return nil
	}
	return err
}

// answeredKept is watch.answered_kept, under the seat's notice lock, which the caller holds: the
// replies answer only the questions they name, kept before `at`, every copy of each, and those
// leave what the seat keeps back.  Each question answered is the owner's time, asked when it was
// first kept and answered at `at`.
func answeredKept(name string, replies [][]string, at float64) error {
	var answered []*run.Object
	path := seatFile(name)
	err := put(path, strings.TrimSuffix(path, ".json")+".lock", run.Line, false, func(data *run.Object) bool {
		kept := questionsKept(data.Dict("unasked"), nil)
		latest := map[string]*run.Object{}
		for _, question := range kept {
			latest[notify.QuestionKey(question.Str("text"))] = question
		}
		var left []*run.Object
		answered = nil
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
		if len(answered) == 0 {
			return false
		}
		var rest any
		if len(left) > 0 {
			rest = keptRecord(left)
		}
		return set([]field{{"unasked", rest}}, field{"session", name})(data)
	})
	if err != nil || len(answered) == 0 {
		return err
	}
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
	conversation, _ := conversationOf(name)
	history.Owner(conversation, moments, nil)
	return nil
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

// conversationOf is notify.conversation_of as an owner row names it, `<harness>:<id>`: nil where
// the seat has no record or its harness says it holds no conversation; false where Go cannot say
// which it holds.
func conversationOf(name string) (any, bool) {
	current, record, err := config.ResolveSession(name)
	if err != nil {
		return nil, false
	}
	if record == nil {
		return nil, true
	}
	own := config.SeatHarness(current)
	conversation, known := harness.Owned(own, record)
	if own == "" || !known || conversation == "" {
		return nil, own != "" && known
	}
	return own + ":" + conversation, true
}
