package cli

import (
	"agentkit/internal/handback"
	"agentkit/internal/hooks"
	"agentkit/internal/seat"
)

var rulebooks = hooks.Rulebooks{Current: seat.Rulebook, Update: seat.Update, Riding: handback.Riding}
