package listing

import (
	"context"
	"io"
	"os/exec"
	"slices"
	"strings"
	"sync"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
)

// listingCap is how long one login's listing may take, after which that login lists nothing.
const listingCap = 15 * time.Second

// ChoicesContext lets a screen stop its listing and reap its adapter calls before leaving.
func ChoicesContext(ctx context.Context, harness string) ([]Choice, error) {
	rows := askContext(ctx, harness)
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return choices(harness, rows)
}

func askContext(ctx context.Context, harness string) [][]string {
	if ctx.Err() != nil {
		return nil
	}
	script, _ := config.Lister(harness)
	logins, err := config.ListingLogins(harness)
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
	cmd.Env, cmd.WaitDelay = env, time.Second
	stop := host.AdapterCall(cmd)
	var said strings.Builder
	cmd.Stdout, cmd.Stderr = &said, io.Discard
	if cmd.Start() != nil {
		return nil
	}
	// The cap holds to the end of the output, which a helper the adapter leaves can hold open past
	// its exit, when the Context no longer reaches anything.
	ended := make(chan error, 1)
	go func() { ended <- cmd.Wait() }()
	select {
	case err := <-ended:
		if err != nil {
			return nil
		}
	case <-ctx.Done():
		stop()
		<-ended
		return nil
	}
	for _, line := range config.SplitLines(strings.ToValidUTF8(said.String(), "�")) {
		if fields := strings.Split(line, "\t"); len(fields) == 3 && fields[0] != "" {
			rows = append(rows, []string{fields[0], fields[2], fields[1]})
		}
	}
	return rows
}
