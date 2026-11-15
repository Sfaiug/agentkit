package tick

import (
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

const (
	revertFailures = 3      // watch.REVERT_FAILURES: failed health probes in a row, deployed, that make a release broken
	revertGrace    = 5 * 60 // watch.REVERT_GRACE: a release coming up gets five minutes after its deployment
)

// probeOnce is the merge's `kind:` declaration, health or deployed, probed as Python's
// health_command runs it, once a round for each repository and commit, and stamped as it ends: a
// slow probe must not spend the release's startup grace.  With it, the row history.db keeps of it,
// for its caller to write once it carries the merge: none for a probe this round ran before.
func probeOnce(probes map[[3]string]probe, key, kind string, each *merge, command string, rows *history.Checked) (probe, func()) {
	at := [3]string{key, each.sha, kind}
	if said, ran := probes[at]; ran {
		return said, func() {}
	}
	asked := epoch(time.Now())
	var said probe
	var exit *int
	said.passed, said.output, exit = healthCommand(each.record.Str("repo"), each.sha, command, healthTimeout)
	said.at = epoch(time.Now())
	probes[at] = said
	return said, func() {
		if rows != nil {
			history.Ran(&history.Checked{Run: rows.Run, Kind: kind, Tree: rows.Tree}, command, asked, exit, nil)
		}
	}
}

// deploying is the merge's deployment probed beside its health, once a round, with its row; none
// where it declares none, nor in a dry tick, which runs no probe.
func deploying(probes map[[3]string]probe, key string, each *merge, command string, rows *history.Checked, dry bool) (*probe, func()) {
	if command == "" || dry {
		return nil, func() {}
	}
	said, row := probeOnce(probes, key, "deployed", each, command, rows)
	return &said, row
}

// deployedOn is what a deployment probe leaves on the merge's run, after_merge_deployed: whether
// the live product runs it now, and when it first did, kept as the start of its own window.
func deployedOn(current *run.Object, said probe) {
	current.Set("deployed_passed", said.passed)
	if said.passed && !current.Has("deployed_at") {
		current.Set("deployed_at", run.Float(said.at))
	}
}

// failuresOn is the broken release's count after a health probe of a deployed merge, its deployment
// written first: one more failure while the live product runs it, up to revertFailures, else none.
func failuresOn(current *run.Object, passed bool) {
	failures := 0
	if !passed && current.Truthy("deployed_passed") {
		count, _ := current.Num("health_failures")
		failures = min(revertFailures, int(count)+1)
	}
	current.Set("health_failures", failures)
}

// deployment is which way a deployed merge's health fails, for its NOT LIVE line.
func deployment(passed bool) string {
	if passed {
		return "this merge is live and its health fails"
	}
	return "the live product does not run this merge yet"
}

// reverting is after_merge_revert up to where a revert starts: only the newest merge whose
// deployment passes now, probed once a round, may undo a broken live release, once its health has
// failed revertFailures times in a row and revertGrace has passed since its deployment.  That
// revert, or the schema change named instead, is the next milestones': errLeft there, its
// deployment written first, as Python's is.  A project's own rollback leaves none deployed, and a
// dry tick reverts nothing.
func reverting(key string, merges []*merge, probes map[[3]string]probe, dry bool) error {
	if dry {
		return nil
	}
	for _, each := range slices.Backward(merges) {
		command := each.record.Str("deployed")
		if each.sha == "" || command == "" {
			continue
		}
		rows, err := mergeRows(each, false)
		if err != nil {
			return err
		}
		said, row := probeOnce(probes, key, "deployed", each, command, rows)
		row()
		err = run.Change(filepath.Join(run.Runs(), each.name), func(current *run.Object) error {
			deployedOn(current, said)
			each.record = current
			return nil
		})
		if err != nil {
			return err
		}
		if !said.passed {
			continue // not served: an older release may be the one live
		}
		failures, _ := each.record.Num("health_failures")
		deployed, _ := dated(each.record, "deployed_at")
		if failures >= revertFailures && epoch(time.Now())-deployed >= revertGrace {
			return errLeft
		}
		return nil
	}
	return nil
}
