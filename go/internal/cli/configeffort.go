package cli

import (
	"cmp"
	"fmt"
	"maps"
	"slices"
	"strings"

	"agentkit/internal/config"
	modelListing "agentkit/internal/listing"
	"agentkit/internal/matrix"
	"agentkit/internal/seat"
)

// A visit reads each harness once, before any key can step its models' efforts, and again after a
// sign-in on it finishes, since a login changes what each of its models offers.
type configCatalog struct {
	choices map[string][]modelListing.Choice
	ask     func(string) ([]modelListing.Choice, error)
}

// signedIn is each harness a sign-in has finished on since c last read its models (ranVerb).
var signedIn = map[string]bool{}

func (catalogs *configCatalog) read(c *matrix.Configuration) error {
	if catalogs.choices == nil {
		catalogs.choices = map[string][]modelListing.Choice{}
	}
	for harness := range signedIn {
		delete(catalogs.choices, harness)
	}
	clear(signedIn)
	ask := catalogs.ask
	if ask == nil {
		ask = modelListing.Choices
	}
	for _, name := range c.Names {
		entry := c.Models[name]
		choices, read := catalogs.choices[entry.Harness]
		if !read {
			var err error
			if choices, err = ask(entry.Harness); err != nil {
				return err
			}
			catalogs.choices[entry.Harness] = choices
		}
		for _, choice := range choices {
			if choice.ID == entry.ID {
				c.Levels[name] = choice.Efforts
			}
		}
	}
	return nil
}

// stepConfigEffort steps the effort in column one level on, from the highest round to the lowest,
// or, `to` 0 or more, takes its to-th level, a level past its last changing nothing.  A seat's page
// holds it till it closes (applyConfigHeld), with the record's effort when that cell was first
// stepped: a step back to that one lets it go, the record's own drawn again (menu.config_effort).
func stepConfigEffort(c *matrix.Configuration, session string, row, column, to int) (string, bool) {
	name, role := c.Names[row], column-3
	levels, current := c.Levels[name], c.Effort(name, role)
	if len(levels) == 0 {
		return "", true
	}
	if to < 0 {
		to = (slices.Index(levels, current) + 1) % len(levels)
	}
	if to >= len(levels) || levels[to] == current {
		return "", true
	}
	word := levels[to]
	if session == "" {
		return stepNewSeatsEffort(c, name, column, word)
	}
	cell := [2]string{name, config.RoleEfforts[role]}
	pair, held := c.Held[cell]
	if !held {
		pair[0] = current
	}
	delete(c.Held, cell)
	if word != pair[0] {
		c.Held[cell] = [2]string{pair[0], word}
	}
	return "", true
}

// applyConfigHeld applies what a seat's page holds, once, then holds nothing (menu.apply_held):
// as it closes, and before a model is picked on it.  The effort of the orchestrator its record
// names now goes into the seat as one move (seat.Move), asking on `card` where that restarts it,
// and every other is written to its record at once (seat.SaveEfforts).  What to say under the
// rows, or ""; false leaves the move to Python.
func applyConfigHeld(c *matrix.Configuration, session string, card seatCard) (string, bool) {
	defer clear(c.Held) // after the card, which draws the page as it holds them
	if len(c.Held) == 0 {
		return "", true
	}
	if selected, unread := seat.ConfigSelection(session); unread == nil && selected != nil {
		c.Selected = selected // a model another window picked since keeps its pick: no effort moves it
	}
	orchestrator, lead, led := c.Selected.Str("orchestrator"), "", false
	var steps []seat.Step
	for _, cell := range slices.SortedFunc(maps.Keys(c.Held), func(a, b [2]string) int {
		return cmp.Or(strings.Compare(a[0], b[0]), strings.Compare(a[1], b[1]))
	}) {
		switch _, runs := c.Models[cell[0]]; {
		case !runs: // a model the config no longer runs holds nothing
		case cell == [2]string{orchestrator, "effort"}:
			lead, led = c.Held[cell][1], true
		default:
			steps = append(steps, seat.Step{Model: cell[0], Key: cell[1], Effort: c.Held[cell][1]})
		}
	}
	var said []string
	if len(steps) > 0 {
		if saved, err := seat.SaveEfforts(session, steps...); err != nil {
			said = append(said, err.Error())
		} else {
			c.Selected.Set("efforts", saved.Get("efforts"))
		}
	}
	if led {
		known, err := seat.Move(session, orchestrator, lead, func(kept bool) (bool, bool) {
			return card(fmt.Sprintf("Restart %s on %s at %s?", session, config.ModelName(orchestrator, c.Models), lead), "Restart", kept)
		})
		if !known {
			return "", false
		}
		if selected, unread := seat.ConfigSelection(session); unread == nil && selected != nil {
			c.Selected = selected
		}
		if err != nil {
			said = append(said, config.Fold(err.Error()))
		}
	}
	return strings.Join(said, "\n"), true
}
