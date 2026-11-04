package loop

import (
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// A deliberate stop owes no hand-back; its launching seat's bar follows the recorded stop.
func redressStopped(record *run.Object) { seat.Redress(run.Seat(record)) }
