package cli

import (
	"fmt"
	"slices"

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
// or, `to` 0 or more, takes its to-th level, a level past its last changing nothing.  A seat's
// orchestrator effort is the one its harness runs, so its step moves the seat (seat.Move), asking
// on `card` where that restarts it (menu.seat_effort).
func stepConfigEffort(c *matrix.Configuration, session string, row, column, to int, card seatCard) (string, bool) {
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
	if role == 0 {
		known, err := seat.Move(session, name, word, func(kept bool) (bool, bool) {
			return card(fmt.Sprintf("Restart %s on %s at %s?", session, config.ModelName(name, c.Models), word), "Restart", kept)
		})
		if !known {
			return "", false
		}
		if selected, unread := seat.ConfigSelection(session); unread == nil && selected != nil {
			c.Selected = selected
		}
		if err != nil {
			return config.Fold(err.Error()), true
		}
		return "", true
	}
	saved, err := seat.SaveEffort(session, name, config.RoleEfforts[role], word)
	if err != nil {
		return err.Error(), true
	}
	c.Selected.Set("efforts", saved.Get("efforts"))
	return "", true
}
