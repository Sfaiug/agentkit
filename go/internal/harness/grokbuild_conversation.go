package harness

import (
	"cmp"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// grokSession is the folder Grok Build keeps a conversation of that working directory in
// (grokbuild.py `session_dir`): under GROK_HOME, read directly, else ~/.grok, the whole directory
// quoted as Python's quote(safe="") quotes it, a space as %20.
func grokSession(cwd, conversation string) string {
	home := cmp.Or(os.Getenv("GROK_HOME"), filepath.Join(config.UserHome(), ".grok"))
	return filepath.Join(home, "sessions", strings.ReplaceAll(url.QueryEscape(cwd), "+", "%20"), conversation)
}

// grokTyped is what the user side typed in that conversation, dated (grokbuild.py `user_messages`).
func grokTyped(record map[string]any, conversation string) (typed []Prompt, err error) {
	said, _, err := grokRead(record, conversation)
	for _, message := range said {
		if message.who == "user" {
			typed = append(typed, Prompt{message.at, message.text})
		}
	}
	return typed, err
}

// grokAnswered is the conversation the record names, whatever vouched for it (Harness.conversation),
// as its seat's done check reads it: its messages, the user side's and the model's (grokbuild.py
// `said`), and each question the owner answered on its cards (`answers`).
func grokAnswered(record map[string]any) ([]Turn, []Card, error) {
	conversation, _ := record["conversation"].(string)
	said, cards, err := grokRead(record, conversation)
	if err != nil {
		return nil, nil, err
	}
	var turns []Turn
	for _, message := range said {
		turns = append(turns, Turn{message.who, message.text})
	}
	return turns, cards, nil
}

// A grokMessage is one message of a Grok Build conversation: the user side's or the model's, when
// its first chunk came, and its chunks' words joined.
type grokMessage struct {
	who  string
	at   float64
	text string
}

// grokRead reads that conversation of the record's checkout once from its session's updates.jsonl,
// the durable UI record, which outlives model-context compaction (grokbuild.py `read_by`): its
// messages, oldest first, and each question the owner answered on its cards.  None where the record
// names no checkout or the file is gone; the error where it is there and cannot be read, beside
// what was read before it.
func grokRead(record map[string]any, conversation string) (said []grokMessage, cards []Card, err error) {
	cwd, _ := record["cwd"].(string)
	if conversation == "" || cwd == "" {
		return nil, nil, nil
	}
	var current *grokMessage
	var key []any
	asked := map[string]any{}
	err = Entries(filepath.Join(grokSession(cwd, conversation), "updates.jsonl"), func(entry *run.Object) {
		chunk, next, ends := grokChunk(entry, conversation, key)
		if current != nil && ends {
			said, current = append(said, *current), nil
		}
		switch {
		case chunk.text != "" && current != nil:
			current.text += chunk.text
		case chunk.text != "":
			current, key = &chunk, next
		}
		cards = append(cards, grokCards(entry, conversation, asked)...)
	})
	if current != nil {
		said = append(said, *current)
	}
	return said, cards, err
}

// grokChunk is that line as a chunk of a message (grokbuild.py `messages`): its words where it is
// a dated text chunk of the conversation's user side or model, displayText before text; the key of
// the message it is a chunk of, all of a prompt's chunks one message; and whether it ends the
// message `key` names, as every other line does and every interjection.  A host turn, a shell
// command and any other update are no chunk.
func grokChunk(entry *run.Object, conversation string, key []any) (chunk grokMessage, next []any, ends bool) {
	params := grokDict(entry, "params")
	update := grokDict(params, "update")
	meta, content := grokDict(update, "_meta"), grokDict(update, "content")
	shown := grokDict(content, "_meta")
	who := map[string]string{"user_message_chunk": "user", "agent_message_chunk": "model"}[update.Str("sessionUpdate")]
	spoken := entry.Get("method") == "session/update" && params.Get("sessionId") == conversation && who != "" && !meta.Truthy("hostTurn")
	interjection := any(false)
	if meta.Has("interjection") {
		interjection = meta.Get("interjection")
	}
	next = []any{who, meta.Get("promptIndex"), interjection}
	ends = !spoken || !run.Equal(next, key) || meta.Truthy("interjection")
	if !spoken || content.Get("type") != "text" || shown.Get("bashCommand") != nil {
		return grokMessage{}, next, ends
	}
	text := content.Get("text")
	if shown.Has("displayText") {
		text = shown.Get("displayText")
	}
	chunk = grokMessage{who: who, at: Moment(entry.Get("timestamp"))}
	if chunk.at != 0 {
		chunk.text, _ = text.(string)
	}
	return chunk, next, ends
}

// grokCards is each question that line answers on a card asked before it, adding the card it asks
// itself, by its call (grokbuild.py `answers`): the call's dated `completed` update settles its card,
// and its result holds the only record of the owner's answers (grokGiven).  A line any part of which
// read here has another shape answers nothing and asks nothing.
func grokCards(entry *run.Object, conversation string, asked map[string]any) []Card {
	params := grokDict(entry, "params")
	update := grokDict(params, "update")
	call, named := update.Get("toolCallId").(string)
	if !named || entry.Get("method") != "session/update" || params.Get("sessionId") != conversation {
		return nil
	}
	switch update.Get("sessionUpdate") {
	case "tool_call":
		tool, input := grokDict(grokDict(update, "_meta"), "x.ai/tool"), grokDict(update, "rawInput")
		if tool.Get("name") == "ask_user_question" && input.Has("questions") {
			asked[call] = input.Get("questions")
		}
	case "tool_call_update":
		questions, ok := asked[call]
		at := Moment(entry.Get("timestamp"))
		if !ok || update.Get("status") != "completed" || at == 0 {
			return nil
		}
		delete(asked, call)
		return grokGiven(questions, grokDict(grokDict(update, "rawOutput"), "UserAnswered").Get("message"), at)
	}
	return nil
}

// grokGiven is each of the card's questions an answered card's message answers, at that time, with
// its choices and the owner's answer (grokbuild.py `given`, as Harness.answers keeps them): the
// label picked or the labels ticked, then any words typed on a line of their own.  A card with a
// question or a label that is not text, or a message that is not, answers nothing, and neither does
// a question with a description that is not text.
//
// Grok Build 1.0.46 lists the questions answered in the order asked, joined by ", ", each as
// `"<question>"="<chosen>"`, nothing escaped: the label picked, the labels ticked joined by ", ",
// or "Other" where they only typed, then ` user notes: ` and any words typed.  Each question is
// read only with what it offered, so a label, or words typed, holding the message's own
// punctuation, or a question's opening with an answer it did not offer, read whole.  Python takes
// "Other" only where ` user notes: ` follows it, a lookahead Go's regexp has not: here that is an
// alternative of its own after the labels', and leftmost-first matching picks the groups Python's
// backtracking does.
func grokGiven(questions, message any, at float64) []Card {
	type asking struct {
		question  string
		choices   []Choice
		described bool
	}
	var asked []asking
	pattern := ""
	listed, _ := questions.([]any)
	for _, each := range listed {
		question, _ := each.(*run.Object)
		if question == nil {
			return nil
		}
		text, isText := question.Get("question").(string)
		if !isText {
			return nil
		}
		ask := asking{question: text, described: true}
		var labels []string
		if question.Truthy("options") {
			options, listed := question.Get("options").([]any)
			if !listed {
				return nil
			}
			for _, value := range options {
				option, _ := value.(*run.Object)
				if option == nil {
					return nil
				}
				label, labelled := option.Get("label").(string)
				if !labelled {
					return nil
				}
				description := any("")
				if option.Has("description") {
					description = option.Get("description")
				}
				said, described := description.(string)
				ask.described = ask.described && described
				ask.choices = append(ask.choices, Choice{label, said})
				labels = append(labels, regexp.QuoteMeta(label))
			}
		}
		label := strings.Join(labels, "|")
		pattern += `(?:(?:\A|, )"` + regexp.QuoteMeta(text) + `"=(?:"((?:` + label + `)(?:, (?:` + label + `))*)"(?: user notes: (.*?))?` +
			`|"(Other)" user notes: (.*?)))?`
		asked = append(asked, ask)
	}
	const head, tail = "User has answered your questions: ", ". You can now continue with the user's answers in mind."
	text, _ := message.(string)
	body, opened := strings.CutPrefix(text, head)
	body, closed := strings.CutSuffix(body, tail)
	whole, err := regexp.Compile(`(?s)\A(?:` + pattern + `)\z`)
	if !opened || !closed || err != nil {
		return nil
	}
	found := whole.FindStringSubmatchIndex(body)
	if found == nil {
		return nil
	}
	var cards []Card
	for i, ask := range asked {
		group := func(n int) (string, bool) {
			at := found[2+8*i+2*n:]
			if at[0] < 0 {
				return "", false
			}
			return body[at[0]:at[1]], true
		}
		picked, chose := group(0)
		typed, wrote := group(1)
		if !chose {
			picked, chose = group(2)
			typed, wrote = group(3)
		}
		if !chose {
			continue
		}
		if picked == "Other" && wrote {
			picked = ""
		}
		answer := strings.Join(slices.DeleteFunc([]string{picked, typed}, func(said string) bool { return said == "" }), "\n")
		if ask.described && strings.TrimFunc(answer, config.Space) != "" {
			cards = append(cards, Card{at, ask.question, answer, ask.choices})
		}
	}
	return cards
}

// grokDict is the key's object, an empty one for anything else.
func grokDict(object *run.Object, key string) *run.Object {
	return cmp.Or(object.Dict(key), run.NewObject())
}
