package cli

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/menu"
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

// noticeLines are the messages wrapped at words to width, each line in from indent, the home
// written ~ (Python's show_notices).
func noticeLines(messages []string, width int, indent string) []string {
	var lines []string
	for _, message := range messages {
		for _, part := range terminal.Wrap(strings.ReplaceAll(message, config.UserHome()+string(os.PathSeparator), "~/"), width-len(indent)) {
			lines = append(lines, indent+part)
		}
	}
	return lines
}

// showMenuNotices is Python's show_notices on the screen the menu holds: the messages in the note
// frame (pause), wrapped two spaces in, whose pages ↑ and ↓ turn so none of a note taller than the
// screen is lost, until Enter, Esc or a click on `esc back` goes on to the menu; false where the
// keyboard is gone.
func showMenuNotices(messages []string, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	top := 0
	var clicks terminal.Clicks
	for {
		s := keyboard.Screen()
		body, clock := noticeLines(messages, s.LayoutWidth(), "  "), time.Now().Format("15:04")
		page := max(1, s.Height()-len(menu.Panel(s, "note", clock, nil, "esc back"))-1)
		top = max(0, min(top, len(body)-page))
		lines := menu.Panel(s, "note", clock, body[top:min(top+page, len(body))], "esc back")
		painter.Write(lines, s)
		switch key := keyboard.ReadKey(); {
		case key.Name == "enter" || key.Name == "esc":
			return true
		case key.Name == "eof":
			keyboard.Give()
			return false
		case key.Name == "again":
			painter.Forget()
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			top -= page
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			top += page
		case key.Name == "pointer" && key.Mouse.Button&64 != 0:
			top += page * key.Mouse.Notches
		case key.Name == "pointer" && clicks.Click(key.Mouse) && key.Mouse.Row == len(lines):
			if _, on := terminal.Under(lines[len(lines)-1], key.Mouse.Column); on {
				return true // on `esc back`, the key line's one item and the panel's last line
			}
		}
	}
}
