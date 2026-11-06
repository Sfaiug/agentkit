package worker

import (
	"cmp"
	"os"
	"path/filepath"

	"agentkit/internal/config"
)

// receipts are what history counts the turn in out by, as Python's worker.call writes them: the
// harness that reads its tokens, and the login it ran on.  The receipt's time is when the turn
// began.
func receipts(out, harness string, env map[string]string) error {
	for name, text := range map[string]string{"harness": harness, "account": cmp.Or(env["AGENTKIT_ACCOUNT"], config.DefaultAccount)} {
		if err := os.WriteFile(filepath.Join(out, name), []byte(text), 0o666); err != nil {
			return err
		}
	}
	return nil
}
