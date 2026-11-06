package cli

import (
	"fmt"
	"io"
	"os"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

func newMenuRow() (*menu.Draft, bool) {
	names, known := seat.ReadNames().Reservations()
	if !known {
		return nil, false
	}
	hint, _ := characterName(func(name string) (bool, bool) { return names[name], true })
	draft, err := menu.NewDraft(hint, names)
	return draft, err == nil
}

func startMenuRow(model *menu.Model, dry, overlay bool, keyboard *terminal.Keyboard, painter *terminal.Painter, errOut io.Writer) (bool, int) {
	d := model.New
	// Another menu may have taken the name while this one was being typed.
	taken, known := seat.ReadNames().Reservations()
	if !known {
		keyboard.Give()
		return true, notImplemented(errOut, "attach")
	}
	d.Taken = taken
	if d.Typed == "" && d.Refusal() != "" {
		name, _ := characterName(func(name string) (bool, bool) { return taken[name], true })
		d.Hint = name
	}
	if d.Refusal() != "" {
		return false, 0
	}
	keyboard.Give()
	if dry {
		fmt.Fprintf(os.Stdout, "would start %s: %s, workers %s, reviewers %s\n", d.Name(), d.Orchestrator,
			strings.Join(d.Workers, " "), strings.Join(d.Reviewers, " "))
		model.New = nil
		if overlay {
			return true, 0
		}
		keyboard.Take()
		painter.Forget()
		return false, 0
	}
	cwd, err := os.Getwd()
	if err == nil {
		err = config.EnsureDirs()
	}
	known = false
	if err == nil {
		known, err = seat.Open(d.Name(), d.Orchestrator, d.Models, d.Workers,
			config.Resolve(cwd), d.Typed == "", d.Reviewers)
	}
	if err == nil && !known {
		return true, notImplemented(errOut, "attach")
	}
	if err != nil {
		fmt.Fprintf(errOut, "ak attach: %s\n", err)
		keyboard.Take()
		painter.Forget()
		return false, 0
	}
	leave, code := openMenuSeat(d.Name(), dry, overlay, keyboard, painter, errOut)
	if !leave {
		model.Highlight, model.New = menu.Highlight{Cursor: d.Name()}, nil
	}
	return leave, code
}
