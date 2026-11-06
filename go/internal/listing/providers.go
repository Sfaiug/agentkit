package listing

import (
	"bytes"
	"context"
	"errors"
	"os/exec"
	"strings"
	"time"

	"agentkit/internal/config"
)

// providersCap is how long a host harness may take to list its providers.
const providersCap = 75 * time.Second

// A Provider is one a host harness can log in to (config.Listed).
type Provider = config.Listed

// Providers is every provider that harness can log in to, as its adapter's `providers` verb lists
// them, the logged-in ones first (config.listed_providers).  The one with the harness's own id is the
// harness's own, named by its label (config.ProviderHosts).  An error in the adapter's own last words
// where it lists none.
func Providers(ctx context.Context, harness string) ([]Provider, error) {
	ctx, cancel := context.WithTimeout(ctx, providersCap)
	defer cancel()
	adapter, err := config.LoginAdapter(harness)
	if err != nil {
		return nil, err
	}
	env, err := config.ChildEnv()
	if err != nil {
		return nil, err
	}
	cmd := exec.CommandContext(ctx, adapter, "providers")
	var said bytes.Buffer
	cmd.Env, cmd.Stderr = env, &said
	out, err := catalogOutput(ctx, cmd)
	if err != nil && !errors.As(err, new(*exec.ExitError)) {
		return nil, errors.New(harness + " providers: " + err.Error())
	}
	_, labels := config.ProviderHosts()
	var rows []Provider
	for _, line := range config.SplitLines(string(out)) {
		if fields := strings.Split(line, "\t"); len(fields) == 3 && fields[0] != "" {
			if fields[0] == harness && labels[harness] != "" {
				fields[1] = labels[harness]
			}
			rows = append(rows, Provider{ID: fields[0], Name: fields[1], Mode: fields[2]})
		}
	}
	if err != nil || len(rows) == 0 {
		last := harness + " lists no provider"
		if lines := config.SplitLines(strings.TrimSpace(said.String())); len(lines) > 0 {
			last = lines[len(lines)-1]
		}
		return nil, errors.New(last)
	}
	return rows, nil
}
