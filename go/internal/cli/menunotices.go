package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/terminal"
)

func menuNotices() []string {
	path := filepath.Join(config.Home(), "state", "update-result")
	data, err := os.ReadFile(path)
	if err != nil || os.Remove(path) != nil {
		return nil
	}
	var messages []string
	for _, line := range strings.Split(string(data), "\n") {
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
