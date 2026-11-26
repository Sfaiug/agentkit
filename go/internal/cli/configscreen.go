package cli

import (
	"context"
	"fmt"
	"os"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/machines"
	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
	"agentkit/internal/update"
)

// menuConfig uses the popup's seat, never the main screen's highlighted row. An ordinary
// window edits what new seats take, and `a` gives them to the seats `main` reads as rows.
// False leaves a key beyond this milestone to the shadow build.  A seat's page holds each effort
// stepped on it till it closes, or a model is picked on it, which first applies what it holds
// (applyConfigHeld), as Python's config_matrix: the owner, 17 Nov 2026, "see the closing of the
// hover menu as kind of like 'apply'".
func menuConfig(session string, cells []menu.Cell, main func() *reading, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	c, err := matrix.Configured()
	if err != nil || len(c.Names) == 0 {
		return false
	}
	held := map[[2]string][2]string{}
	c.Held = held
	view := menu.ConfigView{Matrix: c, Scope: "new seats", Fresh: session == "", Cells: cells, Version: update.AgentkitVersion()}
	if view.Version == "" {
		view.Version = "?"
	}
	if session != "" {
		current, _, err := config.ResolveSession(session)
		if err != nil {
			return false
		}
		selected, err := seat.ConfigSelection(current)
		if err != nil && !os.IsNotExist(err) {
			return false
		}
		session = ""
		if selected != nil {
			c.Selected, session, view.Scope = selected, current, current
		}
	}
	catalogs := waitingConfigCatalog(keyboard, painter, cells)
	if err := catalogs.read(c); err != nil {
		return err == context.Canceled
	}
	if session != "" {
		// a seat's c takes no key typed while it opened, as Python's, which reads the seat's usage
		// first, lets each go (show_config's waited); a fresh window's keeps them
		keyboard.Drop()
	}
	defer painter.Forget()
	defer func() {
		// however else the page ends, as closing it does, it applies what it still holds: a page
		// Python takes over from here holds nothing of it
		if c != nil {
			applyConfigHeld(c, session, cardOn(session, &view, keyboard, painter))
		}
	}()
	nextKey := followSeat(session, keyboard)
	for {
		var known bool
		view.Options = configOptions(c, view.Options)
		if view.Row >= 0 && view.Row < len(c.Names) {
			columns := c.Columns(c.Names[view.Row])
			if !slices.Contains(columns, view.Column) {
				view.Column = max(0, view.Column-3)
			}
		}
		view.Clock = time.Now().Format("15:04")
		screen := keyboard.Screen()
		frame := menu.ConfigFrame(screen, view)
		if view.Row < frame.First { // its meter's grid gone at this width: onto the first model
			view.Row = 0
			frame = menu.ConfigFrame(screen, view)
		}
		view.Top = frame.Top
		painter.Write(frame.Lines, screen)
		key := nextKey(c)
		switch {
		case key.Name == "again": // a resize: drawn whole again, what was said and the pointer's place kept
			painter.Forget()
			continue
		case key.Name == "wake": // the seat's record changed, or a read landed: drawn again, what was said kept
			continue
		case view.Away && (key.Name == "space" || key.Name == "enter"):
			view.Away = false // pressed with no highlight drawn: it only comes back where the keys left it
			continue
		}
		view.Note, view.Away = "", false
		level := -1
		switch {
		case key.Name == "esc" || key.Name == "eof":
			// closing applies what the page holds; what that could not do keeps it open, said
			note, known := applyConfigHeld(c, session, cardOn(session, &view, keyboard, painter))
			if !known {
				return false
			}
			if note == "" {
				return true
			}
			view.Note = note
			continue
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			view.Row = max(frame.First, view.Row-1)
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			view.Row = min(len(c.Names)+len(view.Options)-1, view.Row+1)
		case key.Name == "left" || key.Name == "right":
			if view.Row >= 0 && view.Row < len(c.Names) {
				columns := c.Columns(c.Names[view.Row])
				step := -1
				if key.Name == "right" {
					step = 1
				}
				at := slices.Index(columns, view.Column)
				view.Column = columns[max(0, min(len(columns)-1, at+step))]
			}
		case key.Name == "pointer":
			mouse := key.Mouse
			if mouse.Button&64 != 0 {
				view.Row = max(frame.First, min(len(c.Names)+len(view.Options)-1, view.Row+mouse.Notches))
			} else if row, column, hit := frame.Hit(mouse); hit {
				if view.Row = row; row >= 0 { // a meter keeps the column the keys left
					view.Column = max(0, column)
				}
				if mouse.Released && mouse.Button&3 == 0 {
					if row < 0 || row >= len(c.Names) {
						key.Name = "enter"
					} else if column >= 0 {
						key.Name = "space"
					}
					if column >= 3 {
						level = frame.Level(mouse, c.Effort(c.Names[row], column-3))
					}
				}
			} else {
				view.Away = true
			}
		case key.Name == "char" && key.Char == "r":
			c.Held = nil // what each role uses is the record's, nothing held over it (menu.models_screen)
			known := menuModels(session, c, keyboard, painter)
			c.Held = held
			if !known {
				return false
			}
		case key.Name == "char" && key.Char == "a" && view.Fresh:
			if !applyDefaults(&view, main, keyboard, painter) {
				return false
			}
		}
		if key.Name == "enter" && view.Row < 0 {
			// what a meter offers is Python's (menu.meter_acts): one that offers nothing opens no list
			if len(view.Cells[len(view.Cells)+view.Row].Acts(false)) > 0 {
				return false
			}
			continue
		}
		if key.Name == "enter" && view.Row >= len(c.Names)+2 {
			if name := view.Options[view.Row-len(c.Names)].Name; name == "Machines" {
				// a read of config.toml that fails closes it, said here
				if view.Note, known = menuMachines(keyboard, painter); !known {
					return false
				}
			} else if !configPages[name](keyboard, painter) {
				return false
			}
			continue
		}
		if key.Name == "enter" && view.Row >= len(c.Names) {
			// Models and Subscriptions both change the models c shows, so it reads them again
			page := view.Row - len(c.Names)
			switch {
			case page == 0 && menuConfigModels(keyboard, painter):
			case page == 1 && menuSubscriptions(keyboard, painter):
			default:
				return false
			}
			c, err = matrix.Configured()
			if err != nil {
				return false
			}
			c.Held = held
			if err := catalogs.read(c); err != nil {
				return err == context.Canceled
			}
			if session != "" {
				if c.Selected, err = seat.ConfigSelection(session); err != nil || c.Selected == nil {
					return false
				}
			}
			view.Matrix, view.Row = c, len(c.Names)+page
			continue
		}
		if key.Name != "space" || view.Row < 0 || view.Row >= len(c.Names) {
			continue
		}
		if view.Column == 0 && c.Selected.Str("orchestrator") == c.Names[view.Row] {
			continue
		}
		if view.Column >= 3 {
			var known bool
			if view.Note, known = stepConfigEffort(c, session, view.Row, view.Column, level); !known {
				return false
			}
			continue
		}
		// a model picked applies what the page holds first, as closing does, and what that could
		// not do stops it, said; it flips the marks as drawn, and the orchestrator's own, above,
		// picks nothing
		mark := c.Mark(c.Names[view.Row], view.Column)
		if view.Note, known = applyConfigHeld(c, session, cardOn(session, &view, keyboard, painter)); !known {
			return false
		} else if view.Note != "" {
			continue
		}
		if view.Column == 0 && session != "" {
			if !moveConfigSeat(session, &view, keyboard, painter) {
				return false
			}
			continue
		}
		var changed *run.Object
		if session != "" {
			changed, err = seat.SaveMarks(session, mark)
		} else {
			var note string
			changed, note = mark(c.Selected)
			if note != "" {
				view.Note = note
				continue
			}
			err = config.RememberDefaults(changed.Str("orchestrator"), configNames(changed, "workers"), configNames(changed, "reviewers"), func() error { return nil })
		}
		if err != nil {
			view.Note = err.Error()
		} else {
			c.Selected = changed
		}
	}
}

func configNames(selected *run.Object, key string) []string {
	names := []string{}
	for _, value := range selected.List(key) {
		if name, ok := value.(string); ok {
			names = append(names, name)
		}
	}
	return names
}

// configPages are the pages Enter opens on the rows under Subscriptions, by the row's name, but
// `Machines`' (menuMachines).
var configPages = map[string]func(*terminal.Keyboard, *terminal.Painter) bool{
	"Discord": menuDiscord, "Weekly audit": menuAudit, "Done check": menuDoneCheck, "Limits": menuLimits,
}

// configOptions are the rows under the models, as menu.CONFIG_ROWS. Owner, 10 Nov 2026: "Remove
// the weekly audit feature for now. Dont delete it, but remove it." `Weekly audit`, its value
// menu.audit_value's, stood between Discord and Done check.  A value that cannot be read is
// shown as why, and a config.toml that will not load, checked after every read so one breaking
// between them is caught, as why on `Machines`, which reads it itself (menu.machines_value), the
// other rows keeping what `last` read, as Python's `c` goes on with the config it read last
// (menu.holding).
func configOptions(c *matrix.Configuration, last []menu.ConfigOption) []menu.ConfigOption {
	check, limits := "", ""
	if checker, on, err := config.DoneCheck(); err != nil {
		check = err.Error()
	} else {
		check = onOff(on) + " · " + checkerName(checker, c.Models)
	}
	if numbers, err := config.HostNumbers(); err != nil {
		limits = err.Error()
	} else {
		limits = limitsSaid(numbers)
	}
	known, noun := len(machines.Known()), "machines"
	if known == 1 {
		noun = "machine"
	}
	options := []menu.ConfigOption{{Name: "Models"}, {Name: "Subscriptions"}, {Name: "Discord", Value: menu.DiscordValue()},
		{Name: "Done check", Value: check},
		{Name: "Machines", Value: fmt.Sprintf("%d %s", known, noun)},
		{Name: "Limits", Value: limits}}
	if err := config.Check(); err != nil {
		if last != nil {
			options = slices.Clone(last)
		}
		options[4].Value = err.Error()
	}
	return options
}

// onOff is how a row says a setting's `on`, as `Weekly audit` and `Done check` do.
func onOff(on bool) string {
	if on {
		return "on"
	}
	return "off"
}
