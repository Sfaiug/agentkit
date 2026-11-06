package cli

import (
	"slices"

	"agentkit/internal/config"
	modelListing "agentkit/internal/listing"
	"agentkit/internal/matrix"
	"agentkit/internal/seat"
)

// A visit reads each harness once, before any key can step its models' efforts, and again only for
// a model new since that its choices lack, which a login made in between brought.
type configCatalog struct {
	choices map[string][]modelListing.Choice
	served  map[[2]string]bool // each harness and model id the choices were read for
	ask     func(string) ([]modelListing.Choice, error)
}

func (catalogs *configCatalog) read(c *matrix.Configuration) error {
	if catalogs.choices == nil {
		catalogs.choices, catalogs.served = map[string][]modelListing.Choice{}, map[[2]string]bool{}
	}
	ask := catalogs.ask
	if ask == nil {
		ask = modelListing.Choices
	}
	asked := map[string]bool{}
	for _, name := range c.Names {
		entry := c.Models[name]
		choices, read := catalogs.choices[entry.Harness]
		model := [2]string{entry.Harness, entry.ID}
		lacked := !catalogs.served[model] && !slices.ContainsFunc(choices, func(choice modelListing.Choice) bool { return choice.ID == entry.ID })
		if !read || lacked && !asked[entry.Harness] {
			var err error
			if choices, err = ask(entry.Harness); err != nil {
				return err
			}
			catalogs.choices[entry.Harness], asked[entry.Harness] = choices, true
		}
		catalogs.served[model] = true
		for _, choice := range choices {
			if choice.ID == entry.ID {
				c.Levels[name] = choice.Efforts
			}
		}
	}
	return nil
}

// stepConfigEffort steps the effort in column one level on, from the highest round to the lowest,
// or, `to` 0 or more, takes its to-th level, a level past its last changing nothing.
func stepConfigEffort(c *matrix.Configuration, session string, row, column, to int) (string, bool) {
	if session == "" || column == 3 {
		return "", false
	}
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
	saved, err := seat.SaveEffort(session, name, config.RoleEfforts[role], word)
	if err != nil {
		return err.Error(), true
	}
	c.Selected.Set("efforts", saved.Get("efforts"))
	return "", true
}
