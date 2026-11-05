package listing

import (
	"context"
	"io"
	"os/exec"

	"agentkit/internal/host"
)

// Read through EOF before reaping the adapter: its helpers may still be writing. Cancellation
// stops the call and closes the reader, so an inherited pipe cannot keep a screen waiting.
func catalogOutput(ctx context.Context, cmd *exec.Cmd) ([]byte, error) {
	stop := host.AdapterCall(cmd)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	defer stdout.Close()
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	type output struct {
		data []byte
		err  error
	}
	ended := make(chan output, 1)
	go func() {
		data, err := io.ReadAll(stdout)
		if waited := cmd.Wait(); err == nil {
			err = waited
		}
		ended <- output{data, err}
	}()
	select {
	case got := <-ended:
		return got.data, got.err
	case <-ctx.Done():
		stop()
		stdout.Close()
		<-ended
		return nil, ctx.Err()
	}
}
