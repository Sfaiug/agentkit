package harness

import (
	"encoding/json"
	"io"
)

// loginEnd writes a harness's `login-end` answer, {email, ends, plan}, on one line as jq -c writes
// it, an empty word null; it exits 0, as the scripts' `login-end` does whatever the login holds.
func loginEnd(out io.Writer, email string, ends any, plan string) int {
	word := func(text string) any {
		if text == "" {
			return nil
		}
		return text
	}
	line := json.NewEncoder(out)
	line.SetEscapeHTML(false)
	line.Encode(struct {
		Email any `json:"email"`
		Ends  any `json:"ends"`
		Plan  any `json:"plan"`
	}{word(email), ends, word(plan)})
	return 0
}
