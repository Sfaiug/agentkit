package tick

import (
	"cmp"
	"encoding/base64"
	"fmt"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/gitcall"
	"agentkit/internal/handback"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// healthTimeout bounds a live probe, and the read of what a merge declares on GitHub
// (watch.HEALTH_TIMEOUT): it must leave time for the rest of the tick.
const healthTimeout = 30 * time.Second

// A probe is what one live probe said, run once a tick for each repository and commit.
type probe struct {
	passed bool
	output string
}

// mergeHealth is Python's after_merge_health, the one place a merge's health is decided: what its
// commit declares kept on its run where the run holds none, and the commit; inside its window its
// `health:` probed, a pass making it live and a failure kept with its output for the next tick,
// each told nobody; past it, the failure kept is its break; and history.db keeps its commit, its
// probes and when it went live (mergeRows).  Go follows no deployment, and a pass its seat may be
// owed is Python's to tell but where the run's ending, still to be said, says it
// (handback.LiveLeft).  Each is decided before this merge's first write, and left there: the one
// write, or where the probe keeps a row, written as it starts, the probe.  A seat that comes to owe
// a pass after that has it recorded, as Python records it, and the next tick, reading it owed
// first, hands its telling over.  A dry tick decides the same, runs no probe and makes no write: it
// says what it would check and record.
func mergeHealth(each *merge, key string, now float64, probes map[[2]string]probe, say func(string), dry bool) error {
	rows, err := mergeRows(each)
	if err != nil {
		return err
	}
	record, dir := each.record, filepath.Join(run.Runs(), each.name)
	inside, found := inWindow(record, now), run.NewObject()
	if !record.Truthy("live_at") && (!record.Has("health") || !record.Has("deployed")) && inside && record.Truthy("repo") {
		// a merge that could not read its commit, or one recorded before merges did: the commit
		// it delivered decides, as it would have there, recorded once
		if found, err = declared(record.Str("repo"), cmp.Or(record.Str("delivery_sha"), each.sha), each.pr, dry); err != nil {
			return err
		}
		for _, name := range found.Keys() {
			if record.Has(name) {
				found.Delete(name)
			}
		}
		if found.Truthy("deployed") {
			return errLeft
		}
	}
	health := healthOf(record)
	if found.Has("health") {
		health = healthOf(found)
	}
	owed := handback.LiveLeft(record)
	verdict, probed := "", (*probe)(nil)
	switch command := run.Text(health.Get("command")); {
	case record.Truthy("live_at"):
		verdict = "passed"
	case !health.Truthy("command"):
	case !inside:
		// One typed line: a line break would reach the seat as Enter and send half of it.
		output := cmp.Or(health.Str("output"), "command exited nonzero without output")
		parts := []string{each.pr}
		for _, line := range config.SplitLines(output) {
			if strings.TrimFunc(line, config.Space) != "" {
				parts = append(parts, line)
			}
		}
		verdict, each.check, each.at = "failed", "health: "+command, strings.Join(parts, "; ")
	default:
		said, ran := probes[[2]string{key, each.sha}]
		if !ran {
			if owed && rows != nil {
				return errLeft
			}
			if dry {
				// the probe is the project's own command, which may act
				say(fmt.Sprintf("would check run %s's live product: %s", each.name, command))
				verdict = "pending"
				break
			}
			said.passed, said.output = healthCommand(record.Str("repo"), each.sha, command, healthTimeout, rows)
			probes[[2]string{key, each.sha}] = said
		}
		verdict, probed = "pending", &said
		if said.passed {
			verdict = "passed"
		}
	}
	if verdict == "passed" && owed {
		return errLeft
	}
	if !dry && (len(found.Keys()) > 0 || record.Str("merge_sha") != each.sha || probed != nil) {
		err := run.Change(dir, func(current *run.Object) error {
			for _, name := range found.Keys() {
				current.Set(name, found.Get(name))
			}
			if current.Truthy("merged") && run.Equal(current.Get("finished_at"), record.Get("finished_at")) {
				current.Set("merge_sha", each.sha)
			}
			if probed != nil && (probed.passed || current.Truthy("live_at")) {
				if !current.Has("live_at") {
					current.Set("live_at", run.Float(now))
				}
				current.Delete("health")
				verdict = "passed"
			} else if probed != nil {
				current.Set("health", run.Fields("command", health.Get("command"), "output", probed.output))
			}
			record = current
			return nil
		})
		if err != nil {
			return err
		}
		each.record = record
	}
	if !dry {
		keepMerge(rows, record, verdict == "passed", say)
	}
	if verdict == "passed" {
		if err := handback.Live(dir, record, now, say, dry); err != nil {
			return err
		}
	}
	each.verdict = verdict
	return nil
}

// declared is what the commit sha declares, Python's merge_record: its `health:`, {} where it
// declares none, and its `deployed:`, null for none; read in repo, else from the repository of
// the pull request pr on GitHub; nothing where neither holds the commit, and the next tick asks
// again.  A read in a partial clone fetches what the clone lacks, which a dry tick does not: it
// reads in repo only an AGENTS.md held there whole, and any other on GitHub.
func declared(repo, sha, pr string, dry bool) (*run.Object, error) {
	held, env := sha+"^{commit}", []string(nil)
	if dry {
		held, env = sha+":AGENTS.md", []string{"GIT_NO_LAZY_FETCH=1"}
	}
	code, _, err := gitcall.Git{Repo: repo, Env: env}.Out("cat-file", "-e", held)
	if err != nil {
		return nil, err
	}
	var health, deployed string
	if code == 0 {
		health, deployed = gitcall.DeclaredAt(repo, sha, "health", env...), gitcall.DeclaredAt(repo, sha, "deployed", env...)
	} else {
		text, found, err := agentsOnGitHub(sha, pr)
		if !found || err != nil {
			return run.NewObject(), err
		}
		health, deployed = task.FrontValue(text, "health"), task.FrontValue(text, "deployed")
	}
	found := run.Fields("health", run.NewObject(), "deployed", nil)
	if health != "" {
		found.Set("health", run.Fields("command", health))
	}
	if deployed != "" {
		found.Set("deployed", deployed)
	}
	return found, nil
}

// agentsOnGitHub is AGENTS.md at sha in the repository of the pull request pr, as GitHub holds it:
// the merge may be only there, and finding its health waits on no fetch.  Not found where GitHub
// does not answer with it.
func agentsOnGitHub(sha, pr string) (string, bool, error) {
	host, owner, name := pullRepo(pr)
	if host == "" {
		return "", false, nil
	}
	api := []string{"api"}
	if host != "github.com" {
		api = append(api, "--hostname", host)
	}
	value, _, err := gh.JSONWithin(healthTimeout, run.Runs(), append(api, "repos/"+owner+"/"+name+"/contents/AGENTS.md?ref="+sha)...)
	if err != nil {
		return "", false, errLeft
	}
	answer, _ := value.(*run.Object)
	if answer == nil || answer.Str("encoding") != "base64" {
		return "", false, nil
	}
	data, err := base64.StdEncoding.DecodeString(answer.Str("content"))
	return gitcall.Decoded(string(data)), err == nil, err
}
