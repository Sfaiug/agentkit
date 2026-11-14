package cli

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/terminal"
)

// menuNotices is what jobs left the screen, Python's orch.job_notices: an update's result, then
// the lines orch.leave_notice appends to notices, each shown once. The result is removed; notices
// is emptied under the lock leave_notice writes under, so a line being left is taken whole or on
// the next turn, and is never made.
func menuNotices() []string {
	state := filepath.Join(config.Home(), "state")
	var text []byte
	result := filepath.Join(state, "update-result")
	if data, err := os.ReadFile(result); err == nil && os.Remove(result) == nil {
		text = data
	}
	if notices, err := lock.Edit(filepath.Join(state, "notices")); err == nil {
		if data, err := io.ReadAll(notices); err == nil {
			text = append(text, data...)
			notices.Truncate(0)
		}
		notices.Close()
	}
	var messages []string
	for _, line := range strings.Split(string(text), "\n") {
		if line = strings.TrimSpace(line); line != "" {
			messages = append(messages, line)
		}
	}
	return messages
}

func noticeLines(messages []string, width int) []string {
	var lines []string
	for _, message := range messages {
		for _, part := range terminal.Wrap(strings.ReplaceAll(message, config.UserHome()+string(os.PathSeparator), "~/"), width-1) {
			lines = append(lines, " "+part)
		}
	}
	return lines
}

// Python's pause prints notices where the menu gives the terminal back. Its keyboard still
// answers Esc immediately, and the next menu frame forgets what was on the alternate screen.
func showMenuNotices(messages []string, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	lines := noticeLines(messages, keyboard.Screen().LayoutWidth())
	keyboard.Give()
	keyboard.TakeKeys()
	fmt.Fprintln(os.Stdout, strings.Join(lines, "\n"))
	fmt.Fprint(os.Stdout, "esc back ")
	for {
		switch key := keyboard.ReadKey(); key.Name {
		case "enter", "esc", "eof":
			keyboard.Give()
			if key.Name == "eof" {
				return false
			}
			keyboard.Take()
			painter.Forget()
			return true
		}
	}
}
