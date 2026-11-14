package tick

import (
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// Whether each seat's product is up, told from the machine ak runs on (Python's alive.py): a
// project's `alive:` exits 0 while its product is up and prints why when it is not.

const (
	aliveCeiling = 60 * time.Second // a check still running then fails
	aliveDown    = 5 * 60           // seconds every read fails, from the first, before the owner is paged
	aliveCut     = 200              // the most of the check's last line a card carries
)

// alive is the alive checks row (alive.tick): each seat's project the project rules row fetched
// read with the `alive:` its default branch declares, in its checkout; while it is down its down
// card asked for until it is out, and once that is out, from the pass that ends the outage on,
// its back card until that is.  Down is every read failing since one at least aliveDown ago.  A
// pass ends an outage whose down card is not out with no back card, and a failing read before
// the back card is out begins a new one.  A project not fetched counts no read, so ak's own
// connection going down never pages; one with no seat, or declaring no `alive:`, forgets its
// outage.  Each is kept in state/alive.json from tick to tick, as its first failing read, and
// once over, with its first pass.
func (t *ticking) alive() error {
	repos, err := seatProjects()
	if err != nil {
		return err
	}
	last, err := outages()
	if err != nil {
		return err
	}
	slices.Sort(repos)
	kept := run.NewObject()
	for _, repo := range repos {
		if !slices.Contains(t.fetched, filepath.Clean(repo)) {
			if last.Has(repo) {
				kept.Set(repo, last.Get(repo))
			}
			continue
		}
		env := gitcall.ProjectEnv(repo)
		commit, err := gitcall.Git{Repo: repo, Env: env}.Try("rev-parse", "--verify", "--quiet", rulesRef)
		if err != nil {
			return err
		}
		command := ""
		if commit != "" {
			command = gitcall.DeclaredAt(repo, commit, "alive", env...)
		}
		if command == "" {
			continue
		}
		since, back, ok := outage(last.Get(repo))
		if !ok {
			return errLeft
		}
		now := epoch(t.clock()) // when this read starts: earlier checks may have taken minutes
		up, said, _ := healthCommand(repo, commit, command, aliveCeiling)
		name := filepath.Base(repo)
		if !up {
			if since == nil || at(back) != 0 {
				since = run.Float(now) // none open: this read begins one
			}
			kept.Set(repo, since)
			if now-at(since) >= aliveDown {
				line := fmt.Sprintf("\U0001f534 %s is down since <t:%d:t> · %s", name, int64(at(since)), lastSaid(said)) // 🔴
				if _, err := notify.Page("down:"+repo+":"+run.Text(since), line, true, t.log.errOut); err != nil {
					return err
				}
			}
			continue
		}
		if since == nil {
			continue
		}
		paged, err := notify.Paged("down:" + repo + ":" + run.Text(since))
		if err != nil {
			return err
		}
		if !paged {
			continue
		}
		if at(back) == 0 {
			back = run.Float(now)
		}
		line := fmt.Sprintf("%s is back since <t:%d:t>, after %s", name, int64(at(back)), lasted(at(back)-at(since)))
		waiting, err := notify.Page("back:"+repo+":"+run.Text(since), line, false, t.log.errOut)
		if err != nil {
			return err
		}
		if waiting {
			kept.Set(repo, []any{since, back})
		}
	}
	if run.Equal(kept, last) {
		return nil
	}
	return replaceFile(statePath("alive.json"), run.Line(kept))
}

// outages is alive.json as Python reads it, none where it cannot be read or parsed.
func outages() (*run.Object, error) {
	data, err := os.ReadFile(statePath("alive.json"))
	if err != nil {
		return run.NewObject(), nil
	}
	value, err := run.DecodeLimited(data)
	if errors.Is(err, run.ErrLoneSurrogate) || errors.Is(err, run.ErrLimit) {
		return nil, errLeft
	}
	if err != nil {
		return run.NewObject(), nil
	}
	if last, ok := value.(*run.Object); ok {
		return last, nil
	}
	return nil, errLeft
}

// outage is a project's kept outage: when its first failing read began, and once over, when its
// first pass did, each nil for none; false for what Go does not read.
func outage(kept any) (since, back any, ok bool) {
	pair, listed := kept.([]any)
	if !listed {
		pair = []any{kept, nil}
	}
	if len(pair) != 2 {
		return nil, nil, false
	}
	for _, stamp := range pair {
		if value, number := run.Num(stamp); stamp != nil && (!number || math.IsInf(value, 0) || math.IsNaN(value)) {
			return nil, nil, false
		}
	}
	return pair[0], pair[1], true
}

// at is a kept stamp's seconds, 0 for none.
func at(stamp any) float64 {
	value, _ := run.Num(stamp)
	return value
}

// lastSaid is the check's last line, from its start, as a card carries it.
func lastSaid(said string) string {
	lines := append([]string{"no output"}, config.SplitLines(said)...)
	last := []rune(lines[len(lines)-1])
	return string(last[:min(len(last), aliveCut)])
}

// lasted is how long an outage lasted: to the minute under a day, `45 min` or `2 h 5 min`, and
// in whole days after, `3 days`.
func lasted(seconds float64) string {
	minutes := math.Floor(math.Trunc(seconds) / 60)
	hours, days := math.Floor(minutes/60), math.Floor(minutes/(24*60))
	switch rest := int(minutes) % 60; {
	case days > 1:
		return fmt.Sprintf("%d days", int(days))
	case days != 0:
		return fmt.Sprintf("%d day", int(days))
	case hours != 0 && rest != 0:
		return fmt.Sprintf("%d h %d min", int(hours), rest)
	case hours != 0:
		return fmt.Sprintf("%d h", int(hours))
	}
	return fmt.Sprintf("%d min", int(minutes))
}
