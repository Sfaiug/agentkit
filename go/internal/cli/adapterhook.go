package cli

import (
	"io"
	"os"

	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// Adapter hooks use the same fact writer, rename following and locks as installed hooks.
func adapterHook(name string, out io.Writer) (code int) {
	defer func() { recover() }()
	payload, _ := io.ReadAll(os.Stdin)
	read, _ := run.Decode(payload)
	event, _ := read.(*run.Object)
	if event = harness.HookEvent(name, event); event != nil {
		return seatState([]byte(run.Line(event)), out)
	}
	return 0
}
