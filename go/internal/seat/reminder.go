package seat

import (
	"regexp"
	"slices"
	"strings"

	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// Pending is questions.pending of the seat as it stands: each question recorded for the owner.
func Pending(name string) []string { return pending(name, notify.Last(name)) }

// Reminder is questions.reminder: what a closing message that said this must still say before it
// stops, each of those questions whose words it does not hold, "" for none.  The owner must see a
// question in the chat before `needs you` begins.
func Reminder(said string, asked []string) string {
	shown := []string{shownWords(said), shownWords(inline(said))}
	var missing []string
	for _, question := range asked {
		if !slices.ContainsFunc(shown, func(each string) bool { return strings.Contains(each, shownWords(question)) }) {
			missing = append(missing, question)
		}
	}
	if len(missing) == 0 {
		return ""
	}
	return "Write these unanswered questions and their choices in your closing assistant message, in the chat. " +
		"The owner must see them there before you stop. They are already recorded; do not register them again.\n\n" +
		strings.Join(missing, "\n\n")
}

// pending is questions.pending: the questions its standing notice asks, then those the seat kept
// back, each once.
func pending(name string, notice *run.Object) (once []string) {
	var asked []string
	if notify.OwnerQuestion(notice) {
		asked = notify.Questions(notice)
	}
	if file, _ := run.ReadJSON(seatFile(name)); file != nil {
		for _, question := range questionsKept(file.Dict("unasked"), nil) {
			asked = append(asked, question.Str("text"))
		}
	}
	for _, question := range asked {
		if !slices.Contains(once, question) {
			once = append(once, question)
		}
	}
	return once
}

var (
	optionsLabel = regexp.MustCompile(`\bOptions:\s*`)
	listMark     = regexp.MustCompile(`(?m)^\s*(?:[-*+]\s+|\d+[.)]\s+)`)
	listItem     = regexp.MustCompile(`^\s*(?:[-*+]|\d+[.)])\s+(.*\S)`)
	lineBreak    = regexp.MustCompile(`\r\n|\r|\n`)
)

// shownWords is questions.words: a text's words with neither a list's marks nor the "Options:" label a
// question's choices are drawn under, which are no question content.
func shownWords(text string) string {
	text = optionsLabel.ReplaceAllString(strings.ReplaceAll(text, "·", "\n"), "\n")
	text = listMark.ReplaceAllString(text, "")
	return strings.Join(strings.Fields(strings.NewReplacer("*", "", "`", "").Replace(text)), " ")
}

// inline is questions.listed: the text with each Markdown list written as the recorded inline list,
// `a, b.`.
func inline(text string) string {
	var lines, items []string
	joined := func() []string {
		if len(items) == 0 {
			return nil
		}
		return []string{strings.Join(items, ", ") + "."}
	}
	for _, line := range lineBreak.Split(text, -1) {
		if item := listItem.FindStringSubmatch(line); item != nil || strings.TrimSpace(line) == "" {
			if item != nil {
				items = append(items, item[1])
			}
			continue
		}
		lines = append(append(lines, joined()...), line)
		items = nil
	}
	return strings.Join(append(lines, joined()...), "\n")
}
