// Package doctor is `ak doctor`, as Python's watch.doctor: where the agents run, whether the tick
// is alive, what each machine ak may use is, any model set to an effort it does not take, and
// what ak rents. It changes nothing.
package doctor

import (
	"context"
	"fmt"
	"io"
	"os/exec"
	"slices"
	"strings"
	"sync"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/machines"
	"agentkit/internal/tick"
)

// listingCap is how long one login's listing may take, after which that login lists nothing.
const listingCap = 15 * time.Second

// Report says all of it and is the exit: 2 for a config Python's config.load refuses, after what
// it reads without one, 1 where the tick reads as hung. False, with nothing said, where a read is
// one Go cannot make. The first lines come out before the efforts, which ask each harness.
func Report(out, errOut io.Writer) (int, bool) {
	health, stuck, read := tick.Health()
	if !read {
		return 0, false
	}
	harnesses, refused := config.OfferedHarnesses()
	rented, read := config.NotRenting()
	if refused == nil && !(read && askable(harnesses)) {
		return 0, false
	}
	fmt.Fprintln(out, host.SliceLine())
	fmt.Fprintln(out, "tick  "+health)
	var wrong []string
	if refused == nil {
		for _, line := range machines.Lines() {
			fmt.Fprintln(out, "machine  "+line)
		}
		wrong, refused = config.WrongEfforts(listings{}.efforts)
	}
	if refused != nil {
		fmt.Fprintf(errOut, "ak doctor: %s\n", refused)
		return 2, true
	}
	if len(wrong) == 0 {
		wrong = []string{"effort  every model takes the effort it is set to"}
	}
	fmt.Fprintln(out, strings.Join(wrong, "\n"))
	fmt.Fprintln(out, "rented machines: "+rented)
	if stuck {
		return 1, true
	}
	return 0, true
}

// askable is whether each harness has an adapter to ask for its models.
func askable(harnesses []string) bool {
	return !slices.ContainsFunc(harnesses, func(harness string) bool {
		_, can := config.Lister(harness)
		return !can
	})
}

// listings keeps what each harness's logins listed, asked once a run.
type listings map[string][][]string

// efforts is what the harness's listing says that model takes, as config.catalog_held merges it:
// the first login to list the model says it, none where it leaves them unsaid.
func (l listings) efforts(harness, model string) []string {
	rows, asked := l[harness]
	if !asked {
		rows = ask(harness)
		l[harness] = rows
	}
	for _, row := range rows {
		if row[0] == model {
			return strings.FieldsFunc(row[1], config.Space)
		}
	}
	return nil
}

// ask is each model's [id, efforts] the harness's logins list, asked at once, the first login's
// first, as Python's config.catalog.
func ask(harness string) [][]string {
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
	cmd.Env, cmd.WaitDelay = env, time.Second
	host.Group(cmd)
	said, err := cmd.Output()
	if err != nil {
		return nil
	}
	for _, line := range config.SplitLines(strings.ToValidUTF8(string(said), "�")) {
		if fields := strings.Split(line, "\t"); len(fields) == 3 && fields[0] != "" {
			rows = append(rows, []string{fields[0], fields[2]})
		}
	}
	return rows
}
