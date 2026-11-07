package worker

import (
	"context"
	"errors"
	"time"

	"agentkit/internal/run"
)

// ErrSilent is a turn stopped for streaming nothing for its Given's Silence.
var ErrSilent = errors.New("silent")

// A LoginExpired is a harness that cannot authenticate: no turn of it reaches the model.
type LoginExpired struct{ Harness, Why string }

func (e *LoginExpired) Error() string {
	return e.Harness + " login expired: " + e.Why
}

// Given is what a run binds a turn to, beyond its model's own config: its context, which ends the
// turn as ^C does; the efforts the run launched with, and each variable of Env, over the model's
// and the environment's; and the silence its event stream is stopped after, none for zero.
type Given struct {
	Context context.Context
	// Account is the login of its provider the turn runs on, usage.TurnAccount's: "" for a provider's one.
	Account string
	Efforts map[string]string
	Env     []string
	Silence time.Duration
	// UsersAt is the ref a review's `users:` is read at.
	UsersAt string
	// Checks is what a builder's `ak hand-in done` is held to, nil for nothing.
	Checks *run.Object
	// Findings is the file of blocking findings handed to the turn, "" for none.
	Findings string
	// Previous is the record file of the turn this one resumes, "" for none.
	Previous string
}
