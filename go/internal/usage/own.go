package usage

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/host"
)

// shipped is the words a refresh asks a harness's verbs with where no $AGENTKIT_ADAPTER_DIR is
// named: for a harness with a `usage` verb of its own, this program's `ak adapter`, as
// listing.Lister asks a harness's own `models`, so no script runs, nor need be there; else the
// checkout's script, or why it cannot be run.
func shipped(name string) ([]string, error) {
	if harness.Usage(name) != nil {
		program, _, err := config.Running()
		return []string{program, "adapter", filepath.Dir(filepath.Dir(program)), name}, err
	}
	script, err := config.ShippedAdapter(name)
	return []string{script}, err
}

// ask is the source's adapter asked that verb for its login.
func (src source) ask(ctx context.Context, verb string) *exec.Cmd {
	cmd := exec.CommandContext(ctx, src.adapter[0], append(slices.Clone(src.adapter[1:]), verb)...)
	cmd.Env = append(os.Environ(), config.AccountEnv(src.account), "AGENTKIT_PROVIDER="+src.Name)
	cmd.WaitDelay = time.Second
	host.AdapterCall(cmd)
	return cmd
}
