package listing

import (
	"context"
	"os/exec"
	"slices"
	"strings"
	"sync"
	"time"

	"agentkit/internal/config"
)

// listingCap is how long one login's listing may take, after which that login lists nothing.
const listingCap = 15 * time.Second

// ChoicesContext lets a screen stop its listing and reap its adapter calls before leaving.
func ChoicesContext(ctx context.Context, harness string) ([]Choice, error) {
	return ChoicesAdding(ctx, harness, "", "")
}

// ChoicesAdding is ChoicesContext as the harness will answer once provider, where named, lists
// account alone (config.ListingLoginsAdding).
func ChoicesAdding(ctx context.Context, harness, provider, account string) ([]Choice, error) {
	rows := askContext(ctx, harness, provider, account)
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return choices(harness, rows)
}

func askContext(ctx context.Context, harness, provider, account string) [][]string {
	if ctx.Err() != nil {
		return nil
	}
	script, _ := config.Lister(harness)
	logins, err := config.ListingLoginsAdding(harness, provider, account)
	if err != nil || script == "" {
		return nil
	}
	env, err := config.ChildEnv()
	if err != nil {
		return nil
	}
	answers := make([][][]string, len(logins))
	var asking sync.WaitGroup
	for i, told := range logins {
		asking.Add(1)
		go func() {
			defer asking.Done()
			answers[i] = listed(ctx, script, slices.Concat(env, told))
		}()
	}
	asking.Wait()
	var rows [][]string
	for _, answer := range answers {
		rows = append(rows, answer...)
	}
	return rows
}

// listed is one login's answer, as Python's config._listed reads it: nothing for a call that
// fails or outlasts its cap, and an `id<TAB>label<TAB>efforts` line for each model.
func listed(parent context.Context, script string, env []string) (rows [][]string) {
	ctx, cancel := context.WithTimeout(parent, listingCap)
	defer cancel()
	cmd := exec.CommandContext(ctx, script, "models")
	cmd.Env = env
	said, err := catalogOutput(ctx, cmd)
	if err != nil {
		return nil
	}
	for _, line := range config.SplitLines(strings.ToValidUTF8(string(said), "�")) {
		if fields := strings.Split(line, "\t"); len(fields) == 3 && fields[0] != "" {
			rows = append(rows, []string{fields[0], fields[2], fields[1]})
		}
	}
	return rows
}
