package harness

import "math"

// opencodeTyped is what the user side typed in that session, as opencode.py's `user_messages`
// reads opencode.db (opencodeMessages): each user row's `text`, dated when OpenCode wrote it, in
// milliseconds; none where the database holds none, and the error where it cannot be read.
func opencodeTyped(session string) ([]Prompt, error) {
	rows, err := opencodeMessages(session)
	var typed []Prompt
	for _, row := range rows {
		created, dated := sqlNumber(row.created)
		if at := created / 1000; row.user && dated && !math.IsInf(at, 0) {
			if text, _ := row.data.Get("text").(string); text != "" {
				typed = append(typed, Prompt{at, text})
			}
		}
	}
	return typed, err
}
