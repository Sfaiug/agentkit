package cli

import (
	"bytes"
	"cmp"
	"errors"
	"io"
	"os"
	"os/exec"
	"regexp"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/menu"
	"agentkit/internal/plan"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

var firstSentence = regexp.MustCompile(`(?s)^.*?[.!?](?:\s|$)`)

func pastRow(each seat.Seat, now time.Time) (menu.PastSeat, bool) {
	closed, restart, known := each.PastReady(now)
	done, total := plan.Progress(each.Name)
	said := strings.TrimSpace(plan.FirstDone(each.Name))
	if sentence := firstSentence.FindString(said); sentence != "" {
		said = strings.TrimSpace(sentence)
	}
	return menu.PastSeat{Seat: menu.Seat{Name: each.Name, Checkout: each.Checkout(), Model: each.Orchestrator,
		Done: done, Total: total, Said: said}, Closed: closed, Restart: restart}, known
}

func sortPast(past []menu.PastSeat) {
	slices.SortStableFunc(past, func(a, b menu.PastSeat) int { return cmp.Compare(b.Closed, a.Closed) })
}

func menuPast(saved *[]menu.PastSeat, settle func(), dry, overlay bool, keyboard *terminal.Keyboard, painter *terminal.Painter, errOut io.Writer) (bool, int) {
	past, highlight := slices.Clone(*saved), menu.Highlight{}
	defer func() { *saved = past }()
	for len(past) > 0 {
		screen := keyboard.Screen()
		drawn := menu.DrawPast(screen, past, highlight, time.Now(), screen.Width(), screen.Height())
		if len(drawn.Lines) == 0 {
			keyboard.Give()
			return true, notImplemented(errOut, "attach")
		}
		painter.Write(drawn.Lines, screen)
		key := keyboard.ReadKey()
		rows := make([]menu.Seat, len(past))
		for i := range past {
			rows[i] = past[i].Seat
		}
		choice := menuChoice(key, drawn, rows, keyboard)
		switch {
		case choice != "":
			settle()
			keyboard.Give()
			known, err := seat.ReopenPast(choice, dry, os.Stdout, errOut)
			if !known {
				return true, notImplemented(errOut, "attach")
			}
			keyboard.Take()
			painter.Forget()
			if err != nil {
				model := past[slices.IndexFunc(past, func(each menu.PastSeat) bool { return each.Name == choice })].Model
				pastNote("resume: "+model+": "+err.Error(), keyboard, painter)
				return false, 0
			}
			past = slices.DeleteFunc(past, func(each menu.PastSeat) bool { return each.Name == choice })
			if overlay {
				keyboard.Give()
			}
			return overlay, 0
		case highlight.Move(key, drawn):
		case key.Name == "esc" || key.Name == "eof":
			return false, 0
		case key.Name == "again":
			painter.Forget()
		case key.Name == "char" && strings.EqualFold(key.Char, "x"):
			if highlight.Hidden {
				highlight.Hidden = false
				continue
			}
			name := drawn.Open(terminal.Key{Name: "enter"})
			accepted, known := confirmMenu(keyboard, painter, name, "Remove "+name+" from past sessions?",
				"It can no longer be reopened.", "Remove", func(s terminal.Screen) menu.Frame {
					return menu.DrawPast(s, past, menu.Highlight{Cursor: name, Hidden: true}, time.Now(), s.Width(), s.Height())
				})
			if !known {
				keyboard.Give()
				return true, notImplemented(errOut, "attach")
			}
			if accepted {
				settle()
				known, err := removePast(name, dry)
				if !known {
					keyboard.Give()
					return true, notImplemented(errOut, "attach")
				}
				if err != nil {
					pastNote("stop: "+err.Error(), keyboard, painter)
					return false, 0
				}
				past = slices.DeleteFunc(past, func(each menu.PastSeat) bool { return each.Name == name })
			}
		}
	}
	return false, 0
}

// The menu's owner asks for removal even when the popup runs over another seat. The child
// enters the one stop path with Python's owner_env; no seat's stop authority is widened.
func removePast(name string, dry bool) (bool, error) {
	if dry {
		return true, nil
	}
	self, err := os.Executable()
	env, unread := config.ChildEnv()
	if err != nil || unread != nil {
		return true, errors.Join(err, unread)
	}
	call := exec.Command(self, "orch", "stop", name)
	call.Env = host.Unmarked(slices.DeleteFunc(env, func(pair string) bool { return strings.HasPrefix(pair, "AGENTKIT_SESSION=") }))
	var note bytes.Buffer
	call.Stderr = &note
	err = call.Run()
	if exit := (*exec.ExitError)(nil); errors.As(err, &exit) && exit.ExitCode() == 3 {
		return false, nil
	}
	if err != nil {
		return true, errors.New(cmp.Or(strings.TrimSpace(note.String()), err.Error()))
	}
	return true, nil
}

func pastNote(note string, keyboard *terminal.Keyboard, painter *terminal.Painter) {
	for {
		screen := keyboard.Screen()
		body := terminal.Wrap(note, screen.LayoutWidth())
		body = body[:min(len(body), max(1, screen.Height()-4))]
		painter.Write(append(body, "", "esc back"), screen)
		switch key := keyboard.ReadKey(); key.Name {
		case "esc", "eof":
			return
		case "again":
			painter.Forget()
		}
	}
}
