package loop

import (
	"cmp"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// fixOnTip ends a fix run whose checks already pass on its target's fetched tip before any turn,
// Python's check_fix_on_tip: another merge may have fixed the command since the run was launched
// to.  A fresh run checks once, after a fetch that went through; a scratch run, a flaky repair and
// a suite split keep their first turn, as does one whose tip cannot be checked out or checked.
func (l *loop) fixOnTip() error {
	r, isRepo := l.place.(*repoPlace)
	if l.prior || !isRepo || !r.fetched || len(l.every) == 0 {
		return nil
	}
	record, err := run.Read(l.dir)
	if record == nil {
		return cmp.Or(err, errors.New("run.json cannot be read"))
	}
	if repair := record.Dict("repair"); !l.fixRun(record) || record.Truthy("split_suite") || repair != nil && repair.Truthy("flaky") {
		return nil
	}
	unavailable := func(err error) error {
		l.say(fmt.Sprintf("fix check unavailable: %v; continuing to the first executor turn", err))
		return nil
	}
	upstream := r.upstream()
	tip, err := r.git().Try("rev-parse", "--verify", "--quiet", "refs/remotes/"+upstream+"^{commit}")
	if err != nil {
		return unavailable(err)
	}
	if tip == "" {
		return nil
	}
	l.say(fmt.Sprintf("--- fix check on %s (%s) before the first turn", upstream, tip))
	if err := l.step("done-when"); err != nil {
		return err
	}
	tmp, err := os.MkdirTemp(l.dir, "")
	if err != nil {
		return unavailable(err)
	}
	defer os.RemoveAll(tmp)
	checkout := filepath.Join(tmp, "checkout")
	if err := tipCheckout(r.wt, checkout, tip); err != nil {
		return unavailable(err)
	}
	// before the first round: round 0, as Python's
	ok, _, _, err := l.checksIn(checkout, l.every, filepath.Join(l.dir, "tip.log"), l.rows("done-when", tip))
	switch {
	case err != nil && (l.ctx.Err() != nil || errors.Is(err, errStop)):
		return err // a stop or a signal ends the run here as anywhere
	case err != nil:
		return unavailable(err)
	case !ok:
		return nil
	}
	commands := make([]string, len(l.every))
	for i, cmd := range l.every {
		commands[i] = "`" + cmd + "`"
	}
	return &notNeeded{fmt.Sprintf("%s passed on %s at %s", strings.Join(commands, "; "), upstream, tip)}
}

// tipCheckout checks tip out at path in a clone of wt's own: it borrows wt's objects but none of
// its local replacement refs, and holds wt's fetched remote refs and origin, so only the target as
// fetched decides, never the run's branch or a stale local one.
func tipCheckout(wt, path, tip string) error {
	g := gitcall.Git{Repo: wt}
	origin, err := g.Must("remote", "get-url", "origin")
	if err != nil {
		return err
	}
	if err := g.CloneBorrowing(path, "--no-checkout"); err != nil {
		return err
	}
	clone := gitcall.Git{Repo: path}
	// the clone's origin is wt, whose local branches it took as origin's: they go with it
	for _, args := range [][]string{
		{"remote", "remove", "origin"},
		{"remote", "add", "origin", origin},
		{"fetch", "--quiet", "--no-tags", wt, "+refs/remotes/*:refs/remotes/*"},
		{"checkout", "--quiet", "--detach", tip},
	} {
		if _, err := clone.Must(args...); err != nil {
			return err
		}
	}
	return nil
}
