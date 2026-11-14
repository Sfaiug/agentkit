package worker

import (
	"cmp"
	"os"
	"path/filepath"

	"agentkit/internal/config"
)

// receipts are what history counts the turn in out by, as Python's worker.call writes them: the
// harness that reads its tokens, the login it ran on, and the model its entry launched it with,
// for a harness whose events name none.  The harness receipt's time is when the turn began.
func receipts(out string, model config.Model, env map[string]string) error {
	for name, text := range map[string]string{"harness": model.Harness, "account": cmp.Or(env["AGENTKIT_ACCOUNT"], config.DefaultAccount), "model": model.ID} {
		if err := os.WriteFile(filepath.Join(out, name), []byte(text), 0o666); err != nil {
			return err
		}
	}
	return nil
}
