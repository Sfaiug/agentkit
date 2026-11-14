package matrix

import (
	"agentkit/internal/boards"
	"agentkit/internal/run"
)

// ConfigRoles is the config's word for each role ak answers, the one ak's runs measure it under.
var ConfigRoles = map[string]string{"orchestrate": "orchestrator", "execute": "executor", "review": "reviewer"}

// Measures are what ak's own runs measured, Python's spend.roles (measures).
type Measures struct {
	// Shares is {model: {effort: {role: share}}}: of each offered model at each effort it did a
	// worker role at, the mean points of a week its runs took there
	Shares *run.Object
	listed map[[3]string]float64 // the mean dollars at listed prices those are, by model, effort and role
	plans  []plan                // of each login a subscription still lists whose week holds some, in the usage cache's order
}

// A plan is a login's: what it costs a month, nil where nothing says, and the listed dollars its
// week holds.
type plan struct {
	provider string
	price    *float64
	week     float64
}

// Measured is the Measures of history.db at the listed prices of the boards as cached.
func Measured() (*Measures, error) { return measures(boards.Cached()) }
