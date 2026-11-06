package cli

import (
	"context"
	"strings"
	"time"

	"agentkit/internal/config"
	modelListing "agentkit/internal/listing"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// A throughChoice is one row of a host's list: a model it runs now, or with no model a provider it
// lists with no login, to log in to; or, once a model is picked, one of its efforts.
type throughChoice struct {
	provider modelListing.Provider
	model    *modelListing.Choice
	effort   string
	texts    []string
}

// menuAddThrough is `config · add a subscription · <label>`, the list a host opens under `+ add a
// subscription` (menu.config_add): every model it runs now beside its provider's name, then every
// provider it lists with no login.  One of those picked is logged in on the terminal and the host
// asked again, its first model highlighted once it has a mode.  A model picked opens its efforts, and
// one of those adds it (config.TakeIn); a model the config runs is marked, and is added at another
// effort, never at one it runs it at.  Enter or a click picks the choice lit, the key line naming
// what that does; `/` finds in the list and Esc lets the whole list back.  Esc steps back one list,
// true out of the first; a model added or Ctrl-D ends on Subscriptions.  Nothing is typed, so no
// model or effort the catalog does not offer is ever written.
func menuAddThrough(host, label string, cells []menu.Cell, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	view := menu.AddList{Title: addTitle + " · " + label}
	var picked []throughChoice // the model chosen, once one is
	ats := []int{0}            // each list's highlight
	var listed []modelListing.Provider
	var models []modelListing.Choice
	asked := false                     // listed and models are the host's answers
	var pending *modelListing.Provider // one just logged in to
	defer painter.Forget()
	for {
		if !asked {
			var err error
			listed, err = waitAdapter(view.Title, cells, keyboard, painter, func(ctx context.Context) ([]modelListing.Provider, error) {
				return modelListing.Providers(ctx, host)
			})
			if err == nil {
				models, err = waitAdapter(view.Title, cells, keyboard, painter, func(ctx context.Context) ([]modelListing.Choice, error) {
					return modelListing.ChoicesContext(ctx, host)
				})
			}
			if err == context.Canceled {
				return true // Esc while the list was asked: back one list
			}
			asked = true
			if err != nil {
				view.Note = "config: " + err.Error()
			}
		}
		choices, err := throughChoices(keyboard.Screen(), host, listed, models, picked)
		if err != nil {
			view.Note = "config: " + err.Error()
		}
		if pending != nil && len(picked) == 0 { // just logged in to: its first model, once it has a mode
			found := -1
			for i, choice := range choices {
				if choice.provider.ID == pending.ID && choice.model != nil {
					found = i
					break
				}
			}
			if found >= 0 {
				ats[0], view.Finding = found, nil
			} else {
				said := "is not logged in"
				for _, row := range listed {
					if row.ID == pending.ID && row.Mode != "" {
						said = "lists no model"
					}
				}
				view.Note = pending.Name + " " + said + "; nothing added"
			}
			pending = nil
		}
		if view.Finding != nil && *view.Finding != "" {
			var holding []throughChoice
			for _, choice := range choices {
				if strings.Contains(strings.ToLower(strings.Join(choice.texts, " ")), strings.ToLower(*view.Finding)) {
					holding = append(holding, choice)
				}
			}
			choices = holding
		}
		if len(choices) == 0 && view.Note == "" {
			switch {
			case view.Finding != nil && *view.Finding != "":
				view.Note = "nothing here holds " + *view.Finding
			case len(picked) > 0:
				view.Note = "the " + host + " catalog names no model"
			default:
				view.Note = host + " lists no model or provider"
			}
		}
		adding := len(picked) == len(menu.AddSteps)-1
		at := min(ats[len(ats)-1], max(0, len(choices)-1))
		switch {
		case len(choices) == 0:
			view.Enter = ""
		case adding:
			view.Enter = "add"
		case choices[at].model == nil:
			view.Enter = "log in"
		default:
			view.Enter = "open"
		}
		view.Picked, view.Choices, view.At = nil, nil, at
		for _, choice := range picked {
			view.Picked = append(view.Picked, choice.texts)
		}
		for _, choice := range choices {
			view.Choices = append(view.Choices, choice.texts)
		}
		view.Clock = time.Now().Format("15:04")
		screen := keyboard.Screen()
		frame := menu.AddPage(screen, view)
		view.Top = frame.Top
		painter.Write(frame.Lines, screen)
		key := keyboard.ReadKey()
		if key.Name == "wake" {
			continue
		}
		if key.Name != "pointer" {
			view.Away = false
		}
		view.Note = ""
		step := 0
		switch {
		case key.Name == "again":
			painter.Forget()
		case key.Name == "eof":
			return false
		case view.Finding != nil && (key.Name == "esc" || key.Name == "backspace" || key.Name == "char" || key.Name == "space"):
			// what is typed after `/` finds; Esc lets the whole list back
			switch found := *view.Finding; key.Name {
			case "esc":
				view.Finding = nil
			case "backspace":
				found = string([]rune(found)[:max(0, len([]rune(found))-1)])
				view.Finding = &found
			case "char":
				found += key.Char
				view.Finding = &found
			default:
				found += " "
				view.Finding = &found
			}
			ats[len(ats)-1] = 0
		case key.Name == "char" && key.Char == "/":
			view.Finding, ats[len(ats)-1] = new(string), 0
		case key.Name == "esc":
			if len(picked) == 0 {
				return true
			}
			picked, ats, view.Finding = picked[:len(picked)-1], ats[:len(ats)-1], nil
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			step = -1
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			step = 1
		case key.Name == "pointer":
			mouse := key.Mouse
			if mouse.Button&64 != 0 {
				step = -1
				if mouse.Button&1 != 0 {
					step = 1
				}
			} else if choice, hit := frame.Hit(mouse); hit {
				at, ats[len(ats)-1], view.Away = choice, choice, false
				if mouse.Released && mouse.Button&3 == 0 {
					key.Name = "enter"
				}
			} else {
				view.Away = true
			}
		}
		if step != 0 {
			ats[len(ats)-1], view.Away = max(0, min(len(choices)-1, at+step)), false
		}
		if key.Name != "enter" || len(choices) == 0 {
			continue
		}
		ats[len(ats)-1] = at
		chosen := choices[at]
		switch {
		case len(picked) == 0 && chosen.model == nil: // a provider to log in to
			if verb := adapterVerbs(keyboard, painter, host, []string{"login"}, "", chosen.provider.ID, false); verb != "" {
				view.Note = notAdded(host, verb, chosen.provider.Name)
			} else {
				asked, pending = false, &chosen.provider // asked again, for its mode and its models
			}
			painter.Forget()
		case !adding:
			picked, ats, view.Finding = append(picked, chosen), append(ats, 0), nil
		default:
			model := picked[0].model
			if taken, err := config.Runs(host, model.ID, chosen.effort); err != nil || len(taken) > 0 {
				view.Note = saved(err)
				if err == nil {
					view.Note = strings.Join(taken, ", ") + " runs " + model.ID + " at " + chosen.effort + " already"
				}
				continue
			}
			provider := picked[0].provider
			if view.Note = saved(config.TakeIn(model.Label, host, model.ID, chosen.effort, provider.ID, provider.Name, provider.Mode, seat.KeepConfigEfforts)); view.Note == "" {
				return false
			}
		}
	}
}

// throughChoices is the list the host's answers make with picked chosen (menu._through_choices):
// every model it lists of a provider it lists with a mode, which it runs now, beside that provider's
// name, then each provider it lists with none, to log in to; with a model picked, its efforts.  Each
// marked with the names the config runs it under.
func throughChoices(s terminal.Screen, host string, listed []modelListing.Provider, models []modelListing.Choice, picked []throughChoice) ([]throughChoice, error) {
	var choices []throughChoice
	if len(picked) > 0 {
		model := picked[0].model
		for _, effort := range model.Efforts {
			names, err := config.Runs(host, model.ID, effort)
			if err != nil {
				return nil, err
			}
			choices = append(choices, throughChoice{provider: picked[0].provider, model: model, effort: effort, texts: []string{effort, marked(s, names)}})
		}
		return choices, nil
	}
	for i, model := range models {
		owner, _, _ := strings.Cut(model.ID, "/")
		for _, row := range listed {
			if row.ID == owner && row.Mode != "" {
				names, err := config.Runs(host, model.ID, "")
				if err != nil {
					return nil, err
				}
				choices = append(choices, throughChoice{provider: row, model: &models[i], texts: []string{model.Label, row.Name, marked(s, names)}})
				break
			}
		}
	}
	for _, row := range listed {
		if row.Mode == "" {
			id := row.ID
			if id == row.Name {
				id = ""
			}
			choices = append(choices, throughChoice{provider: row, texts: []string{row.Name, id, "log in"}})
		}
	}
	return choices, nil
}

// marked is the names a model or effort runs under already, after a tick (menu._marked).
func marked(s terminal.Screen, names []string) string {
	tick := "✓"
	if s.ASCII() {
		tick = "v"
	}
	if len(names) == 0 {
		return ""
	}
	return tick + " " + strings.Join(names, ", ")
}
