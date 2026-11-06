package loop

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	neturl "net/url"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// A writable account's delivery of what its line checked, Python's deliver in merge: the branch
// pushed over a lease, its PR opened, the target's required checks waited for, and the PR merged
// at the very commit reviewed, with the tree the suite passed on named in the merge.

const (
	mergeBodyQuery = "query=query($owner:String!,$name:String!,$number:Int!,$method:PullRequestMergeMethod!){" +
		"repository(owner:$owner,name:$name){pullRequest(number:$number){" +
		"viewerMergeBodyText(mergeType:$method)}}}"
)

var (
	// GitHub refusing a push for a reason of its own, which the same push went through a minute
	// later; the lease's refusal is git's own `(stale info)` and ends the run at once
	remoteRejected = regexp.MustCompile(`(?m)^.*\[remote rejected\].*$`)
	staleInfo      = regexp.MustCompile(`(?i)stale info`)
	// a merge losing a race to another merge to the target, GitHub not yet having taken the head
	// just pushed, or GitHub's own server failing the call: each re-checked and tried again
	baseModified = regexp.MustCompile(`(?i)Base branch was modified`)
	headModified = regexp.MustCompile(`(?i)Head branch was modified`)
	github5xx    = regexp.MustCompile(`(?i)status code: 5\d\d|HTTP 5\d\d|Bad Gateway|Gateway Timeout|Service Unavailable|couldn't respond to your request in time`)
	notMergeable = regexp.MustCompile(`(?i)Pull Request is not mergeable`)
	pullPath     = regexp.MustCompile(`^/([^/\s]+)/([^/\s]+)/pull/(\d+)/?$`)
	trailerLine  = regexp.MustCompile(`(?m)^Suite-Passed-Tree:.*\n?`)
	methods      = map[string]string{"squash": "--squash", "merge": "--merge", "rebase": "--rebase"}
)

// deliverOwn pushes, opens the PR, waits for its checks and merges, Python's deliver closure.
func (r *repoPlace) deliverOwn(l *loop, target, upstream string) error {
	if err := r.requireReviewPass(l); err != nil {
		return err
	}
	if err := l.step("merge"); err != nil {
		return err
	}
	if ok, err := r.push(l); err != nil || !ok {
		return err
	}
	url, err := r.openPR(l, target)
	if err != nil || url == "" {
		return err
	}
	if ok, err := r.waitChecks(l, url, target); err != nil || !ok {
		return err
	}
	return r.doMerge(l, url, upstream)
}

// read is the record as it stands.
func read(l *loop) (*run.Object, error) {
	record, err := run.Read(l.dir)
	if record == nil {
		return nil, cmp.Or(err, errors.New("run.json cannot be read"))
	}
	return record, nil
}

// push puts the reviewed head on origin, Python's push: over a lease pinned to what the pruning
// fetch saw, so a name another run took is refused, never overwritten.
func (r *repoPlace) push(l *loop) (bool, error) {
	if err := r.requireReviewPass(l); err != nil {
		return false, err
	}
	g := r.git()
	head, err := g.Must("rev-parse", "HEAD")
	if err != nil {
		return false, err
	}
	record, err := read(l)
	if err != nil {
		return false, err
	}
	if record.Str("merge_method") == "rebase" {
		// a rebase merge keeps the branch's messages and ignores a merge body: the trailer goes on
		// the commit, its message alone changed
		if head, err = r.trailed(l, head); err != nil {
			return false, err
		}
	}
	seen, err := g.Try("rev-parse", "--verify", "--quiet", "refs/remotes/origin/"+r.branch)
	if err != nil {
		return false, err
	}
	ours := record.List("pushed")
	if seen != "" && seen != record.Str("delivery_sha") && !slices.ContainsFunc(ours, func(sha any) bool { return run.Text(sha) == seen }) {
		return false, r.note(l, fmt.Sprintf("origin already has %s at %s and this run did not push it; the branch was taken by another run", r.branch, seen[:12]), true)
	}
	// set out to push before it does: origin may take a push that stops before it is recorded
	if err := l.save(func(record *run.Object) { record.Set("pushed", append(append([]any{}, ours...), head)) }); err != nil {
		return false, err
	}
	code, out, err := r.gitPush(l, "--force-with-lease="+r.branch+":"+seen, "-u", "origin", r.branch)
	if err != nil {
		return false, err
	}
	if code != 0 {
		if staleInfo.MatchString(out) {
			return false, r.note(l, fmt.Sprintf("origin already has %s and this run did not push it; the branch was taken by another run: %s", r.branch, tail(out, 400)), true)
		}
		return false, r.note(l, fmt.Sprintf("pushing %s to origin failed: %s", r.branch, tail(out, 400)), true)
	}
	l.say("--- merge: pushed " + r.branch + " to origin")
	return true, l.save(func(record *run.Object) { record.Set("delivery_sha", head) })
}

// trailed is the head with the suite's trailer in its message where the suite passed on it,
// Python's push for a rebase merge.
func (r *repoPlace) trailed(l *loop, head string) (string, error) {
	g := r.git()
	old, err := g.Must("show", "-s", "--format=%B", head)
	if err != nil {
		return "", err
	}
	message := strings.TrimRightFunc(trailerLine.ReplaceAllString(old, ""), config.Space)
	body, err := r.mergeBody(l, head, "")
	if err != nil {
		return "", err
	}
	if len(body) > 0 {
		if message, err = r.addTrailer(l, message, body[len(body)-1]); err != nil {
			return "", err
		}
	}
	if message == strings.TrimRightFunc(old, config.Space) {
		return head, nil
	}
	if _, err := g.Must("-c", "core.hooksPath="+os.DevNull, "commit", "--amend", "--only", "-m", message); err != nil {
		return "", err
	}
	if head, err = g.Must("rev-parse", "HEAD"); err != nil {
		return "", err
	}
	return head, l.save(func(record *run.Object) {
		record.Dict("review").Set("head_sha", head)
		if checked := record.Dict("final_check"); len(body) > 0 && checked != nil {
			checked.Set("sha", head)
		}
	})
}

// gitPush is `git push` with args, GitHub refusing it for a reason of its own waited out and the
// same push tried again over the same lease, Python's git_push.
func (r *repoPlace) gitPush(l *loop, args ...string) (int, string, error) {
	args = append([]string{"push"}, args...)
	for tried := 1; tried <= githubRetries; tried++ {
		code, out, err := r.git().Out(args...)
		refused := ""
		if err == nil && code != 0 {
			refused = remoteRejected.FindString(out)
		}
		if refused == "" {
			return code, out, err
		}
		delay := transientDelay(tried)
		l.say(fmt.Sprintf("WARN GitHub refused the push: %s; pushing again over the same lease in %ds (%d/%d)", strings.TrimSpace(refused), int(delay.Seconds()), tried, githubRetries))
		if err := l.pause(delay); err != nil {
			return 0, "", err
		}
	}
	return r.git().Out(args...)
}

// pause waits, unless a signal ends the driver first.
func (l *loop) pause(delay time.Duration) error {
	select {
	case <-l.ctx.Done():
		return context.Cause(l.ctx)
	case <-time.After(delay):
		return nil
	}
}

// openPR opens the run's PR into the target, Python's open_pr: its URL, "" where it could not.
func (r *repoPlace) openPR(l *loop, target string) (string, error) {
	record, err := read(l)
	if err != nil {
		return "", err
	}
	if record.Truthy("pr") {
		// a run that rejoined its line after opening its PR delivers through that PR, while it is
		// still open on the head just pushed and aimed at the target the line checked
		current, err := prHead(l.dir, record.Str("pr"))
		if err != nil {
			if errors.As(err, new(*gitcall.Stopped)) {
				return "", err
			}
			return "", r.note(l, "could not re-check the PR: "+err.Error(), true)
		}
		if current.Str("state") != "open" || !isDelivery(record, current, target) {
			return "", r.note(l, "PR head or target changed since PASS; a new run is required", true)
		}
		if ok, err := r.refreshPR(l, record); err != nil || !ok {
			return "", err
		}
		return record.Str("pr"), nil
	}
	path := filepath.Join(l.dir, "pr-body.md")
	if err := os.WriteFile(path, []byte(prBody(record)), 0o666); err != nil {
		return "", err
	}
	code, said, err := gh.Call(r.wt, "pr", "create", "--base", target, "--head", r.branch, "--title", record.Str("title"), "--body-file", path)
	if err != nil {
		return "", err
	}
	// gh names the PR it refuses a duplicate of, so one pattern finds both
	url := prURL.FindString(said)
	if url == "" {
		// the create may still have happened on GitHub: the view says so, or stops too
		viewed, view, err := gh.Call(r.wt, "pr", "view", r.branch, "--json", "url", "-q", ".url")
		if err != nil {
			return "", err
		}
		if !gh.Halted(viewed, view) {
			url = prURL.FindString(view)
		}
		switch {
		case url != "":
		case gh.Halted(code, said):
			return "", &gitcall.Stopped{Why: said}
		case gh.Halted(viewed, view):
			return "", &gitcall.Stopped{Why: view}
		default:
			return "", r.note(l, "gh pr create failed: "+tail(said, 400), true)
		}
	}
	if err := l.save(func(record *run.Object) { record.Set("pr", url) }); err != nil {
		return "", err
	}
	open := ""
	if code != 0 {
		open = " (already open)"
	}
	l.say("--- merge: PR " + url + open)
	return url, nil
}

// refreshPR puts the run's description on its open PR, Python's refresh_pr_body: through the REST
// API, as `gh pr edit` asks GraphQL for Projects (classic), which some gh releases fail since
// GitHub retired them.  Only an update GitHub confirmed is skipped on a later delivery.
func (r *repoPlace) refreshPR(l *loop, record *run.Object) (bool, error) {
	path, body := filepath.Join(l.dir, "pr-body.md"), prBody(record)
	if held, err := os.ReadFile(path); err == nil && string(held) == body {
		return true, nil
	}
	api, owner, name, number, ok := prParts(record.Str("pr"))
	if !ok {
		return false, r.note(l, "cannot update the description of "+record.Str("pr")+": not a PR URL", true)
	}
	pending := filepath.Join(l.dir, "pr-body-update.md")
	if err := os.WriteFile(pending, []byte(body), 0o666); err != nil {
		return false, err
	}
	code, said, err := asked(r.wt, append(api, "-X", "PATCH", "repos/"+owner+"/"+name+"/pulls/"+number, "-F", "body=@"+pending)...)
	if err != nil {
		return false, err
	}
	if code != 0 {
		return false, r.note(l, "updating the PR description failed: "+tail(said, 400), true)
	}
	return true, os.Rename(pending, path)
}

// prParts are `gh api` with the host it needs, and the owner, repository and number of the PR at
// url, Python's pr_parts; ok false for a URL that is not one PR on an https host.
func prParts(url string) (api []string, owner, name, number string, ok bool) {
	parsed, err := neturl.Parse(url)
	if err != nil || parsed.Scheme != "https" || parsed.Hostname() == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, "", "", "", false
	}
	parts := pullPath.FindStringSubmatch(parsed.Path)
	if parts == nil {
		return nil, "", "", "", false
	}
	api = []string{"api"}
	if parsed.Host != "github.com" {
		api = append(api, "--hostname", parsed.Host)
	}
	return api, parts[1], parts[2], parts[3], true
}

// askJSON is gh's JSON, or why not, Python's gh_json: a gh that never answered, or wanted a
// prompt, is a Stopped, never an empty answer.
func askJSON(dir string, args ...string) (any, string, error) {
	value, why, err := gh.JSON(dir, args...)
	if err == nil && value == nil && (why == "gh timed out" || gitcall.Halted(1, why)) {
		return nil, "", &gitcall.Stopped{Why: why}
	}
	return value, why, err
}

// waitChecks sits on the PR's required checks until they are green, Python's wait_checks: red
// ones in the line owe a landing fixer, any other failure leaves the PR open and says why.
func (r *repoPlace) waitChecks(l *loop, url, target string) (bool, error) {
	_, owner, name, number, ok := prParts(url)
	if !ok {
		return false, r.note(l, "cannot read required checks for "+url+"; the PR is open at "+url, true)
	}
	record, err := read(l)
	if err != nil {
		return false, err
	}
	wait := record.Dict("waiting_on")
	inLine := wait != nil && wait.Truthy("line")
	head := cmp.Or(record.Str("delivery_sha"), record.Str("head_sha"))
	green, why, err := requiredChecks(l, &gh.Pull{Owner: owner, Name: name, Number: number}, target, head, inLine)
	if err != nil || green {
		return green, err
	}
	if inLine && strings.HasPrefix(why, "required checks failed:") {
		path := filepath.Join(l.dir, "pr-checks.log")
		if err := os.WriteFile(path, []byte(why+"\nPR: "+url+"\n"), 0o666); err != nil {
			return false, err
		}
		line, _, _ := strings.Cut(why, "\n")
		return false, l.save(func(record *run.Object) {
			record.Set("waiting_on", run.SetAll(record.Dict("waiting_on").Copy(), "fix", run.Fields("line", line, "log", path)))
		})
	}
	return false, r.note(l, why+"; the PR is open at "+url, true)
}

// doMerge merges the PR at the reviewed commit, Python's do_merge for a run in its line: a lost
// race or GitHub's own failure is re-checked and tried again, a target that moved under the
// checked tree sends the run back to its line, and work that passed is never thrown away over one
// bad answer.
func (r *repoPlace) doMerge(l *loop, url, upstream string) error {
	record, err := read(l)
	if err != nil {
		return err
	}
	method := cmp.Or(record.Str("merge_method"), "squash")
	why, raced, cause := "", 0, ""
	var code int
	var out string
	for attempt := 1; attempt <= 2; attempt++ {
		ready, lost := true, false
		for {
			if err := r.requireReviewPass(l); err != nil {
				return err
			}
			if record, err = read(l); err != nil {
				return err
			}
			delivered := record.Str("delivery_sha")
			if cmp.Or(record.Dict("review"), run.NewObject()).Str("head_sha") != delivered {
				return r.note(l, "the delivery SHA is not the tested and reviewed commit", true)
			}
			if ready {
				if moved, err := r.targetMoved(l, upstream, true); err != nil || moved {
					return err
				}
				var body []string
				if method != "rebase" {
					if body, err = r.mergeBody(l, delivered, url); err != nil {
						return err
					}
				}
				if code, out, err = gh.Call(l.dir, append([]string{"pr", "merge", url, methods[method], "--delete-branch", "--match-head-commit", delivered}, body...)...); err != nil {
					return err
				}
			}
			if code == 0 || gh.Halted(code, out) {
				break
			}
			switch {
			case baseModified.MatchString(out):
				cause = "the base branch was modified under the merge"
			case headModified.MatchString(out):
				cause = "GitHub had not yet taken the pushed head"
			case github5xx.MatchString(out):
				cause = "GitHub failed the merge call"
			default:
				cause = ""
			}
			if cause == "" {
				break
			}
			if raced >= githubRetries {
				lost = true
				break
			}
			raced++
			delay := transientDelay(raced)
			l.say(fmt.Sprintf("WARN %s; re-fetching, re-checking and retrying in %ds (%d/%d)", cause, int(delay.Seconds()), raced, githubRetries))
			if err := l.pause(delay); err != nil {
				return err
			}
			if fetched, said, err := r.git().Fetch("origin"); err != nil || fetched != 0 {
				return cmp.Or(err, r.note(l, "git fetch origin failed: "+tail(said, 400), true))
			}
			current, err := prHead(l.dir, url)
			if err != nil {
				if errors.As(err, new(*gitcall.Stopped)) {
					return err
				}
				return r.note(l, "could not re-check the PR: "+err.Error(), true)
			}
			switch {
			case !isDelivery(record, current, upstream):
				return r.note(l, "PR head or target changed since PASS; a new run is required", true)
			case current.Truthy("merged"):
				return r.merged(l, url, method)
			case current.Str("state") != "open":
				return r.note(l, "PR is closed without a merge", true)
			}
			if moved, err := r.targetMoved(l, upstream, false); err != nil || moved {
				return err
			}
			// GitHub may still be working out mergeability: an unconfirmed answer spends a retry
			ready = current.Get("mergeable") == true
		}
		if code == 0 {
			return r.merged(l, url, method)
		}
		if lost {
			// the last attempt's 5xx may have merged too, and no re-check followed it
			if merged, err := r.mergedAnyway(l, url, upstream, method); err != nil || merged {
				return err
			}
			tip, err := r.git().Try("rev-parse", upstream+"^{commit}")
			if err != nil {
				return err
			}
			return r.park(l, fmt.Sprintf("gh pr merge --%s failed after %d retries: %s; the PR is open at %s", method, githubRetries, cause, url), upstream, tip)
		}
		refused := notMergeable.MatchString(out)
		viewed := 0
		for polled := 0; polled <= githubRetries; polled++ {
			if polled > 0 {
				if err := l.pause(checksPoll); err != nil {
					return err
				}
			}
			if viewed, why, err = gh.Call(l.dir, "pr", "view", url, "--json", "mergeStateStatus", "-q", ".mergeStateStatus"); err != nil {
				return err
			}
			if !refused || viewed != 0 || why != "UNKNOWN" {
				break
			}
		}
		if gh.Halted(code, out) || gh.Halted(viewed, why) {
			// a merge that stopped may still have gone through on GitHub
			if merged, err := r.mergedAnyway(l, url, upstream, method); err != nil || merged {
				return err
			}
			if gh.Halted(code, out) {
				return &gitcall.Stopped{Why: out}
			}
			return &gitcall.Stopped{Why: why}
		}
		if attempt == 2 || !slices.Contains([]string{"BEHIND", "DIRTY", "CLEAN"}, why) {
			break
		}
		if why == "CLEAN" {
			if !refused {
				break
			}
			l.say("WARN GitHub called the PR not mergeable, then CLEAN: it had not yet worked out the head just pushed; retrying the merge")
			continue
		}
		l.say(fmt.Sprintf("WARN the PR is %s; taking %s in once more and retrying the merge", why, upstream))
		return r.rejoinLine(l, record.Dict("waiting_on"), "the PR is "+why)
	}
	if merged, err := r.mergedAnyway(l, url, upstream, method); err != nil || merged {
		return err
	}
	with := ""
	if why != "" {
		with = " with the PR " + why
	}
	return r.note(l, fmt.Sprintf("gh pr merge --%s failed%s; the PR is open at %s: %s", method, with, url, tail(out, 400)), true)
}

// targetMoved sends the run back to its line where the branch no longer holds the target's tip,
// Python's integrated: what the lander checked is no longer what would merge.  fetch fetches first.
func (r *repoPlace) targetMoved(l *loop, upstream string, fetch bool) (bool, error) {
	if fetch {
		if fetched, out, err := r.git().Fetch("origin", "--prune"); err != nil || fetched != 0 {
			return false, cmp.Or(err, fmt.Errorf("git fetch origin --prune failed in %s: %s", r.wt, out))
		}
	}
	code, _, err := r.git().Out("merge-base", "--is-ancestor", upstream, "HEAD")
	if err != nil || code == 0 {
		return false, err
	}
	record, err := read(l)
	if err != nil {
		return false, err
	}
	return true, r.rejoinLine(l, record.Dict("waiting_on"), "the PR's target moved")
}

// mergeBody is the merge's `--body`, Python's merge_body: GitHub's own body, with the tree the
// target's suite passed on as its trailer, where that suite passed on this very commit; none
// otherwise, and none where GitHub cannot say what its body would be.  With no url it is the
// trailer alone.
func (r *repoPlace) mergeBody(l *loop, head, url string) ([]string, error) {
	record, err := read(l)
	if err != nil {
		return nil, err
	}
	checked := cmp.Or(record.Dict("final_check"), run.NewObject())
	suite := gitcall.Suite(r.wt, cmp.Or(record.Str("target_sha"), r.upstream()))
	tree := checked.Str("tree_sha")
	if suite == "" || checked.Str("suite") != suite || checked.Str("outcome") != "passed" || checked.Str("sha") != head || tree == "" ||
		(checked.Has("tested") && checked.Str("tested") != tree) {
		return nil, nil
	}
	if headTree, err := r.git().Must("rev-parse", head+"^{tree}"); err != nil || headTree != tree {
		return nil, err
	}
	body := "Suite-Passed-Tree: " + tree
	if url == "" {
		return []string{"--body", body}, nil
	}
	api, owner, name, number, ok := prParts(url)
	if !ok {
		l.say("WARN cannot read the merge commit body for " + url + "; merging without suite trailer")
		return nil, nil
	}
	// an explicit body replaces GitHub's own, and the credit it carries with it
	value, why, err := askJSON(l.dir, append(api, "graphql", "-f", mergeBodyQuery, "-f", "owner="+owner, "-f", "name="+name,
		"-F", "number="+number, "-f", "method="+strings.ToUpper(cmp.Or(record.Str("merge_method"), "squash")),
		"-q", ".data.repository.pullRequest.viewerMergeBodyText | tojson")...)
	var stopped *gitcall.Stopped
	if errors.As(err, &stopped) {
		// only the CI shortcut needs this read; the reviewed head stays pinned
		value, why, err = nil, stopped.Why, nil
	}
	if err != nil {
		return nil, err
	}
	text, isText := value.(string)
	if !isText {
		l.say(fmt.Sprintf("WARN could not read the merge commit body for %s: %s; merging without suite trailer", url, cmp.Or(why, "GitHub returned no body text")))
		return nil, nil
	}
	if body, err = r.addTrailer(l, text, body); err != nil {
		return nil, err
	}
	return []string{"--body", body}, nil
}

// addTrailer is the message with the trailer in the block git and GitHub read as trailers,
// existing attribution kept, Python's add_suite_trailer.
func (r *repoPlace) addTrailer(l *loop, message, trailer string) (string, error) {
	path := filepath.Join(l.dir, "merge-body.txt")
	if err := os.WriteFile(path, []byte(message), 0o666); err != nil {
		return "", err
	}
	return r.git().Must("interpret-trailers", "--no-divider", "--where", "end", "--if-exists", "replace", "--trailer", trailer, path)
}

// merged records the PR merged, with what proving it live stands on, Python's merged.
func (r *repoPlace) merged(l *loop, url, method string) error {
	if err := l.save(func(record *run.Object) {
		record.Set("merged", true)
		// the `health:` the merged commit declares, the one record the tick reads after a merge
		if sha := record.Str("delivery_sha"); sha != "" {
			if code, _, err := r.git().Out("cat-file", "-e", sha+"^{commit}"); err == nil && code == 0 {
				health := run.NewObject()
				if command := gitcall.DeclaredAt(r.wt, sha, "health"); command != "" {
					health.Set("command", command)
				}
				record.Set("health", health)
			}
		}
	}); err != nil {
		return err
	}
	l.say("--- merge: merged " + url + " with --" + method + ", remote branch deleted")
	return nil
}

// mergedAnyway is whether GitHub merged this delivery whatever `gh pr merge` answered, recorded
// where it did, Python's merged_anyway: only a merge of the reviewed head into its target counts.
func (r *repoPlace) mergedAnyway(l *loop, url, upstream, method string) (bool, error) {
	current, err := prHead(l.dir, url)
	if err != nil {
		if errors.As(err, new(*gitcall.Stopped)) {
			return false, err
		}
		return false, nil
	}
	record, err := read(l)
	if err != nil || !current.Truthy("merged") || !isDelivery(record, current, upstream) {
		return false, err
	}
	return true, r.merged(l, url, method)
}

// isDelivery is whether the PR as GitHub has it is still this run's delivery: the reviewed head,
// aimed at the target.
func isDelivery(record, current *run.Object, upstream string) bool {
	head, base := cmp.Or(current.Dict("head"), run.NewObject()), cmp.Or(current.Dict("base"), run.NewObject())
	return head.Str("sha") == record.Str("delivery_sha") && base.Str("ref") == strings.TrimPrefix(upstream, "origin/")
}

// prHead is the PR as GitHub's REST API describes it now, Python's pr_head: an open one's head is
// its branch's tip as git has it, which moves the moment a push succeeds.
func prHead(dir, url string) (*run.Object, error) {
	api, owner, name, number, ok := prParts(url)
	if !ok {
		return nil, errors.New("cannot read the PR: " + url + " is not a PR URL")
	}
	value, why, err := askJSON(dir, append(api, "repos/"+owner+"/"+name+"/pulls/"+number)...)
	if err != nil {
		return nil, err
	}
	current, _ := value.(*run.Object)
	if current == nil || current.Dict("head") == nil || !current.Dict("head").Truthy("sha") {
		return nil, errors.New("cannot read the PR: " + why)
	}
	if current.Str("state") == "open" {
		sha, err := gh.BranchTip(current.Dict("head"))
		if err != nil {
			return nil, err
		}
		current.Dict("head").Set("sha", sha)
	}
	return current, nil
}
