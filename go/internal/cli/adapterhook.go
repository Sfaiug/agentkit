package cli

import (
	"io"
	"os"

	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// hooked is each hook an adapter's command may name, as the stubs under go/hooks are named.
var hooked = map[string]func(payload []byte, out io.Writer) int{"seat-state": seatState, "orchestrator-stop": orchestratorStop}

// Adapter hooks use the same fact writer, rename following and locks as installed hooks: the event
// as its harness reads it goes to each hook the command names in turn, the seat's state where it
// names none, once the seat has gone on in, or kept, the conversation it names where its harness
// follows one there (`harness.HookFollows`); the hook exits 3 where one of them leaves its decision
// to Python.
func adapterHook(name string, stems []string, out io.Writer) (code int) {
	defer func() { recover() }()
	payload, _ := io.ReadAll(os.Stdin)
	read, _ := run.Decode(payload)
	event, _ := read.(*run.Object)
	if event, code = harness.HookEvent(name, event, out, seat.QuestionRefused, seat.Reconciled); event == nil {
		return code
	}
	if to := harness.HookFollows(name, event); to != nil && !seat.Claim(os.Getenv("AGENTKIT_SESSION"), *to, os.Getppid()) {
		return leftToPython()
	}
	if len(stems) == 0 {
		stems = []string{"seat-state"}
	}
	for _, stem := range stems {
		if hook := hooked[stem]; hook != nil {
			code = max(code, hook([]byte(run.Line(event)), out))
		}
	}
	return code
}
