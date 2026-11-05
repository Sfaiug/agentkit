package tick

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/run"
)

// What Python's watch.incoming does with an open head of another person's PR on an owned
// checkout: it is reviewed once, by `ak run --review-pr`, whose ending posts the verdict and
// offers a pass to the inbox seat. watch.json's `reviewed` notes each PR's head in Python's form.

// marker opens every review ak posts: a head whose note was lost is found reviewed by it.
const marker = "agentkit review of"

// backoff is how long a head waits after the tick saw its first, second and third try fail, and
// hourly from then on: a head is never abandoned.
var backoff = []float64{600, 1800, 3600}

func wait(tries int) float64 { return backoff[max(0, min(tries, len(backoff)-1))] }

// review is the pass for one open head; false, with nothing launched for it, where gh cannot
// be run as Python runs it.
func (t *ticking) review(pr *run.Object, me string) bool {
	url, sha := pr.Str("html_url"), pr.Dict("head").Str("sha")
	author := "?"
	if user := pr.Dict("user"); user != nil && user.Truthy("login") {
		author = run.Text(user.Get("login"))
	}
	what := fmt.Sprintf("%s (#%s by %s: %s) at %s", url, run.Text(pr.Get("number")), author,
		run.Text(pr.Get("title")), sha[:min(len(sha), 12)])
	reviewed, now := t.state.Dict("reviewed"), epoch(t.clock())
	seen, attempts := reviewed.Dict(url), 0
	again := seen != nil && seen.Get("sha") == sha
	if again {
		if settled(seen) != "failed" {
			return true
		}
		attempts = 1
		if tries, ok := seen.Int("attempts"); ok && tries != 0 {
			attempts = tries
		}
	}
	found, ok := onGitHub(url, sha, me)
	if !ok {
		return false
	}
	if found {
		reviewed.Set(url, run.Fields("sha", sha, "run", nil, "at", now))
		return true
	}
	if again {
		if !seen.Has("retry_at") {
			seen.Set("retry_at", now+wait(attempts-1))
		}
		seen.Delete("gave_up") // older installs gave a head up
		if at, _ := seen.Num("retry_at"); now < at {
			t.log.line("retry " + what + " after " + time.Unix(0, int64(at*1e9)).Format("15:04"))
			return true
		}
		t.log.line(fmt.Sprintf("WARN the review run %s for %s did not finish; launching again", run.Text(seen.Get("run")), what))
	}
	if t.dry {
		t.log.line("would review " + what)
		return true
	}
	id, err := reviewRun(url)
	if err != nil {
		t.log.line("WARN " + err.Error())
		reviewed.Set(url, run.Fields("sha", sha, "run", nil, "at", now, "attempts", attempts+1,
			"error", err.Error(), "retry_at", now+wait(attempts)))
		return true
	}
	reviewed.Set(url, run.Fields("sha", sha, "run", id, "at", now, "attempts", attempts+1))
	t.log.line(fmt.Sprintf("review %s -> %s", what, id))
	return true
}

// settled is what became of the review run an entry names, Python's watch.settled: only a run
// that ended with its review on GitHub at that head settles it, and a stop ends it on purpose. An
// entry naming no run came from a review found on GitHub. The rows before this one leave the tick
// to Python wherever a reap would act, so the record is read as it stands.
func settled(entry *run.Object) string {
	if !entry.Truthy("run") {
		if entry.Truthy("error") {
			return "failed"
		}
		return "done"
	}
	record, _ := run.Read(filepath.Join(run.Runs(), entry.Str("run")))
	if record == nil {
		return "failed"
	}
	state := record.Str("state")
	switch {
	case run.Active(record) || run.NeedsRecovery(record):
		return "pending"
	case state == "stopped":
		return "done"
	case (state == "pass" || state == "fail") && record.Truthy("review_posted") && !record.Truthy("review_stale") &&
		(!entry.Truthy("sha") || record.Get("head_sha") == entry.Get("sha")):
		return "done"
	}
	return "failed"
}

// onGitHub is whether this account already posted ak's review of that head, Python's
// reviewed_on_github; false in the second place where gh cannot be run as Python runs it.
func onGitHub(url, sha, me string) (bool, bool) {
	value, _, err := gh.JSON(run.Runs(), "pr", "view", url, "--json", "reviews")
	if err != nil {
		return false, false
	}
	view, _ := value.(*run.Object)
	if view == nil {
		return false, true
	}
	for _, item := range view.List("reviews") {
		review, _ := item.(*run.Object)
		if review == nil || review.Dict("author") == nil || review.Dict("commit") == nil {
			continue
		}
		if review.Dict("author").Str("login") == me && strings.Contains(review.Str("body"), marker) &&
			review.Dict("commit").Str("oid") == sha {
			return true, true
		}
	}
	return false, true
}

// reviewRun is Python's watch.launch of a review: `ak run --review-pr <url> --bg`, this program's
// own, nobody's seat's, and the id of the run it printed.
func reviewRun(url string) (string, error) {
	asked := "ak run --review-pr " + url + " --bg"
	self, err := os.Executable()
	env, unread := config.ChildEnv()
	if err := errors.Join(err, unread); err != nil {
		return "", err
	}
	call := exec.Command(self, "run", "--review-pr", url, "--bg")
	call.Env = slices.DeleteFunc(env, func(pair string) bool { return strings.HasPrefix(pair, "AGENTKIT_SESSION=") })
	var out, said bytes.Buffer
	call.Stdout, call.Stderr = &out, &said
	if err := call.Run(); err != nil {
		var exit *exec.ExitError
		if !errors.As(err, &exit) {
			return "", err
		}
		both := []rune(strings.TrimFunc(strings.ToValidUTF8(out.String()+said.String(), "�"), config.Space))
		return "", fmt.Errorf("%s exited %d: %s", asked, exit.ExitCode(), string(both[max(0, len(both)-300):]))
	}
	lines := config.SplitLines(out.String())
	for i := len(lines) - 1; i >= 0; i-- {
		if strings.HasSuffix(lines[i], "/result.md") {
			return path.Base(path.Dir(lines[i])), nil
		}
	}
	return "", errors.New(asked + " printed no result path")
}
