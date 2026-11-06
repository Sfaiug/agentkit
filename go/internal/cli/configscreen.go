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
// window edits what new seats take. False leaves a key beyond this milestone to the shadow build.
func menuConfig(session string, cells []menu.Cell, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	c, err := matrix.Configured()
	if err != nil || len(c.Names) == 0 {
		return false
	}
	view := menu.ConfigView{Matrix: c, Scope: "new seats", Fresh: session == "", Cells: cells, Version: update.Build()}
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
	defer painter.Forget()
	nextKey := followSeat(session, keyboard)
	for {
		var known bool
		if view.Options, known = configOptions(c); !known {
			return false
		}
		if view.Row < len(c.Names) {
			columns := c.Columns(c.Names[view.Row])
			if !slices.Contains(columns, view.Column) {
				view.Column = max(0, view.Column-3)
			}
		}
		view.Clock = time.Now().Format("15:04")
		screen := keyboard.Screen()
		frame := menu.ConfigFrame(screen, view)
		view.Top = frame.Top
		painter.Write(frame.Lines, screen)
		key := nextKey(c)
		switch {
		case key.Name == "again": // a resize: drawn whole again, what was said and the pointer's place kept
			painter.Forget()
			continue
		case key.Name == "wake": // the seat's record changed: drawn again, what was said kept
			continue
		case view.Away && (key.Name == "space" || key.Name == "enter"):
			view.Away = false // pressed with no highlight drawn: it only comes back where the keys left it
			continue
		}
		view.Note, view.Away = "", false
		level := -1
		switch {
		case key.Name == "esc" || key.Name == "eof":
			return true
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			view.Row = max(0, view.Row-1)
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			view.Row = min(len(c.Names)+len(view.Options)-1, view.Row+1)
		case key.Name == "left" || key.Name == "right":
			if view.Row < len(c.Names) {
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
				view.Row = max(0, min(len(c.Names)+len(view.Options)-1, view.Row+mouse.Notches))
			} else if row, column, hit := frame.Hit(mouse); hit {
				view.Row, view.Column = row, max(0, column)
				if mouse.Released && mouse.Button&3 == 0 {
					if row >= len(c.Names) {
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
			if !menuModels(session, "config · recommended · "+view.Scope, c, keyboard, painter) {
				return false
			}
		case key.Name == "char" && key.Char == "a" && view.Fresh:
			return false
		}
		if key.Name == "enter" && view.Row == len(c.Names)+3 {
			if !menuAudit(keyboard, painter) {
				return false
			}
			continue
		}
		if key.Name == "enter" && view.Row == len(c.Names)+5 {
			if !menuMachines(keyboard, painter) {
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
		if key.Name != "space" || view.Row >= len(c.Names) {
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
		if view.Column == 0 && session != "" {
			if !moveConfigSeat(session, &view, keyboard, painter) {
				return false
			}
			continue
		}
		mark := c.Mark(c.Names[view.Row], view.Column)
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

func configOptions(c *matrix.Configuration) ([]menu.ConfigOption, bool) {
	discord, cloud := menu.ConfigServices(time.Now())
	setting, on, err := config.Audit()
	audit := ""
	if err != nil {
		audit = err.Error()
	} else {
		audit = onOff(on) + " · " + menu.RoleHead(0) + " " + config.ModelName(setting.Orchestrator, c.Models) + " · " + menu.RoleHead(1) + " " + auditNames(setting.Workers, c.Models) + " · " + menu.RoleHead(2) + " " + auditNames(setting.Reviewers, c.Models)
	}
	checker, on, err := config.DoneCheck()
	check := ""
	if err != nil {
		check = err.Error()
	} else if checker == "" {
		check = onOff(on) + " · the seat's reviewer"
	} else {
		check = onOff(on) + " · " + config.ModelName(checker, c.Models)
	}
	numbers, err := config.HostNumbers()
	if err != nil {
		return nil, false
	}
	limits := limitsSaid(numbers)
	return []menu.ConfigOption{{Name: "Models"}, {Name: "Subscriptions"}, {Name: "Discord", Value: discord},
		{Name: "Weekly audit", Value: audit}, {Name: "Done check", Value: check},
		{Name: "Machines", Value: fmt.Sprintf("%d machines · Google Cloud %s", len(machines.Known()), cloud)},
		{Name: "Limits", Value: limits}}, true
}

// onOff is how a row says a setting's `on`, as `Weekly audit` and `Done check` do.
func onOff(on bool) string {
	if on {
		return "on"
	}
	return "off"
}
