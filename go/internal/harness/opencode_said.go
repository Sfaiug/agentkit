package harness

import "strings"

// opencodeSaid is that session as OpenCode shows it (opencode.py `said`), read loosely, as
// questions.unseen reads it: a database that cannot be read shows nothing.
func opencodeSaid(session string) (said []Turn) {
	rows, _ := opencodeMessages(session)
	for _, row := range rows {
		if turn, shown := row.turn(); shown {
			said = append(said, turn)
		}
	}
	return said
}

// turn is that row as OpenCode shows it (opencode.py `messages`): a user row's `text`, or an
// answer's text parts, never its reasoning or tools; false where it shows none.
func (row opencodeMessage) turn() (Turn, bool) {
	if row.user {
		text, _ := row.data.Get("text").(string)
		return Turn{"user", text}, text != ""
	}
	var texts []string
	for _, part := range row.parts {
		if text, isText := part.Get("text").(string); isText && part.Get("type") == "text" {
			texts = append(texts, text)
		}
	}
	text := strings.Join(texts, "\n")
	return Turn{"model", text}, text != ""
}
