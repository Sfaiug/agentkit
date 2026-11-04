// Package listing asks a harness's logins which models they run, as Python's config.catalog: an
// adapter's `models` verb answers, one `id<TAB>label<TAB>efforts` line per model, told the login.
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

// A Model is one model a harness can run, and the efforts it takes, strongest last.
type Model struct {
	ID      string
	Efforts []string
}

// Catalog is the models that harness can run, each once, as the first login to list it says it:
// what its logins list, else its manifest's `[catalog]` table.
func Catalog(harness string) ([]Model, error) {
	rows := Ask(harness)
	if len(rows) == 0 {
		var err error
		if rows, err = config.CatalogTable(harness); err != nil {
			return nil, err
		}
	}
	var models []Model
	for _, row := range rows {
		if !slices.ContainsFunc(models, func(each Model) bool { return each.ID == row[0] }) {
			models = append(models, Model{row[0], strings.FieldsFunc(row[1], config.Space)})
		}
	}
	return models, nil
}

// Ask is each model's [id, efforts, label] the harness's logins list, asked at once, the first login's
// first.
func Ask(harness string) [][]string {
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
			answers[i] = listed(script, slices.Concat(env, told))
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
func listed(script string, env []string) (rows [][]string) {
	ctx, cancel := context.WithTimeout(context.Background(), listingCap)
	defer cancel()
	cmd := exec.CommandContext(ctx, script, "models")
	cmd.Env = env
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
		return nil
	}
	for _, line := range config.SplitLines(strings.ToValidUTF8(said.String(), "�")) {
		if fields := strings.Split(line, "\t"); len(fields) == 3 && fields[0] != "" {
			rows = append(rows, []string{fields[0], fields[2], fields[1]})
		}
	}
	return rows
}
