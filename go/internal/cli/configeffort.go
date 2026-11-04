package cli

import (
	"slices"

	"agentkit/internal/config"
	modelListing "agentkit/internal/listing"
	"agentkit/internal/matrix"
	"agentkit/internal/seat"
)

// A visit reads each harness once, before any key can step its models' efforts.
type configCatalog struct {
	choices map[string][]modelListing.Choice
	ask     func(string) ([]modelListing.Choice, error)
}

func (catalogs *configCatalog) read(c *matrix.Configuration) error {
	if catalogs.choices == nil {
		catalogs.choices = map[string][]modelListing.Choice{}
	}
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

func stepConfigEffort(c *matrix.Configuration, session string, row, column int) (string, bool) {
	if session == "" || column == 3 {
		return "", false
	}
	name, role := c.Names[row], column-3
	levels, current := c.Levels[name], c.Effort(name, role)
	if len(levels) == 0 {
		return "", true
	}
	word := levels[(slices.Index(levels, current)+1)%len(levels)]
	if word == current {
		return "", true
	}
	saved, err := seat.SaveEffort(session, name, config.RoleEfforts[role], word)
	if err != nil {
		return err.Error(), true
	}
	c.Selected.Set("efforts", saved.Get("efforts"))
	return "", true
}
