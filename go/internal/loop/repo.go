package loop

import (
	"cmp"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/handback"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

var refName = regexp.MustCompile(`^refs/(heads|remotes/origin)/`)

// repoPlace is a repository's run: a checkout of its own on a branch of its own, or the
// repository's own checkout with --no-worktree.
type repoPlace struct {
	repo, wt, branch, from string
	base, target, baseSHA  string
	noWorktree, noMerge    bool
	followup               bool
	fetched                bool // origin's base came in as the run opened: its tip is known
	artifacts              map[string]bool
	checked, viewed        [2]string // the commit and tree the round's checks ran on, and its review read
	title                  string
	files                  []string
}

// repoFrom is the place a record describes.
func repoFrom(record *run.Object) *repoPlace {
	opts := record.Dict("launch_opts")
	artifacts := map[string]bool{}
	for _, name := range names(record.List("artifacts")) {
		artifacts[name] = true
	}
	return &repoPlace{repo: record.Str("repo"), wt: record.Str("worktree"), branch: record.Str("branch"), base: record.Str("base"),
		target: record.Str("target"), baseSHA: record.Str("base_sha"), title: record.Str("title"),
		noWorktree: opts != nil && opts.Truthy("--no-worktree"), noMerge: record.Truthy("no_merge") || opts != nil && opts.Truthy("--no-merge"),
		followup: record.Truthy("followup"), artifacts: artifacts}
}

func (r *repoPlace) git(env ...string) gitcall.Git { return gitcall.Git{Repo: r.wt, Env: env} }

// upstream is `origin/<target>`, the branch the work lands on.
func (r *repoPlace) upstream() string {
	if r.target == "" {
		return ""
	}
	if strings.HasPrefix(r.target, "origin/") {
		return r.target
	}
	return "origin/" + r.target
}

// fromRefusal is why no run can start `from:` that branch, "" where one can.
func (r *repoPlace) fromRefusal(path, from string) (string, error) {
	if from == "" {
		return "", nil
	}
	if r.noWorktree {
		return path + ": from: needs a worktree; drop --no-worktree so the run gets its own checkout", nil
	}
	found, err := gitcall.Git{Repo: r.repo}.Try("rev-parse", "--verify", "--quiet", "refs/heads/"+from)
	if err != nil {
		return "", err
	}
	if found == "" {
		return fmt.Sprintf("%s: from: %s is not a local branch", path, commandhelp.Quote(from)), nil
	}
	return "", nil
}

// open is Python's loop from its refusals to the worktree's environment: the base as origin has
// it now, the checkout, the record naming it before anything else can fail, and the settling.
func (r *repoPlace) open(l *loop, meta map[string]string, path string, common []any) error {
	from := gitcall.Strip(meta["from"])
	why, err := r.fromRefusal(path, from)
	if err != nil {
		return err
	}
	if why != "" {
		return errors.New(why)
	}
	r.from = from
	if err := gitcall.NoAutoGC(r.repo); err != nil {
		return err
	}
	g := gitcall.Git{Repo: r.repo}
	code, out, err := g.Fetch("origin", "--prune", "+refs/heads/*:refs/remotes/origin/*")
	var stopped *gitcall.Stopped
	if errors.As(err, &stopped) {
		code, out = -1, stopped.Why
	} else if err != nil {
		return err
	}
	spelled := meta["base"]
	if spelled == "" {
		head, warning, err := gitcall.DefaultBase(r.repo)
		if err != nil {
			return err
		}
		spelled = head
		if warning != "" {
			l.say(warning)
		}
	}
	r.base = refName.ReplaceAllString(spelled, "origin/")
	r.target = r.base
	if meta["target"] != "" {
		r.target = refName.ReplaceAllString(meta["target"], "origin/")
	}
	name := strings.TrimPrefix(r.base, "origin/")
	// the tracking ref named in full, as `origin/main` could be a tag
	ref := "refs/remotes/origin/" + name
	if code == 0 {
		found, _, err := g.Out("show-ref", "--verify", "--quiet", ref)
		if err != nil {
			return err
		}
		if found != 0 {
			code, out = 1, "origin has no branch "+name
		}
	}
	r.fetched = code == 0
	if code != 0 {
		// git's reason is its first line; the rest is advice
		why, _, _ := strings.Cut(out, "\n")
		if r.followup {
			return &gitcall.Stopped{Why: fmt.Sprintf("could not fetch %s from origin, and a fix run starts only on origin's tip: %s", name, why)}
		}
		l.say(fmt.Sprintf("WARN could not fetch %s from origin; basing this run on the local %s: %s", name, spelled, why))
		ref = spelled
	}
	// a branch name moves with the executor's commits, so pin the diff to the commit it names
	if r.baseSHA, err = g.Must("rev-parse", "--verify", ref+"^{commit}"); err != nil {
		return err
	}
	change, err := r.onChange(l, path)
	if err != nil {
		return err
	}
	if r.noWorktree {
		r.wt = r.repo
		if r.branch, err = g.Must("rev-parse", "--abbrev-ref", "HEAD"); err != nil {
			return err
		}
		l.say(fmt.Sprintf("no worktree: working directly in %s on %s", r.wt, r.branch))
	} else if err := r.makeWorktree(l, task.Slug(l.title), cmp.Or(r.from, r.baseSHA)); err != nil {
		return err
	}
	l.workspace, l.usersAt = r.wt, r.upstream()
	err = l.save(func(record *run.Object) {
		run.SetAll(record, "repo", r.repo, "scratch", false, "base", r.base, "target", r.target, "base_sha", r.baseSHA,
			"branch", r.branch, "worktree", r.wt, "no_merge", r.noMerge)
		run.SetAll(record, common...)
		record.Set("rounds", l.budget)
		if from != "" {
			record.Set("from", from)
		}
		if change != nil {
			record.Set("change", change)
		}
	})
	if err != nil {
		// a stop that landed after the checkout was cut removed nothing for lack of paths
		if !r.noWorktree {
			stopCheckout(l.dir, run.Fields("repo", r.repo, "worktree", r.wt, "branch", r.branch), func(string) {}, false)
		}
		return err
	}
	if !r.noWorktree {
		merging := ""
		if r.target != r.base {
			merging = ", merging into " + r.target
		}
		if from != "" {
			l.say(fmt.Sprintf("worktree %s on %s from %s, base %s (%s)%s", r.wt, r.branch, from, r.base, r.baseSHA[:12], merging))
			if err := r.takeInTarget(l); err != nil {
				return err
			}
		} else {
			l.say(fmt.Sprintf("worktree %s on %s from %s (%s)%s", r.wt, r.branch, r.base, r.baseSHA[:12], merging))
		}
	}
	return r.settle(l)
}

// settle readies a checkout for its turns: the exclude, and the repository's secrets, which from
// here every worker and check has.
func (r *repoPlace) settle(l *loop) error {
	if err := r.excludeJunk(l); err != nil {
		return err
	}
	env, err := config.RepoEnv(r.repo)
	if err != nil {
		return err
	}
	if len(env) > 0 {
		var names []string
		for key, value := range env {
			os.Setenv(key, value)
			names = append(names, key)
		}
		sort.Strings(names)
		l.say(fmt.Sprintf("env: %s -> %s", filepath.Join(config.Home(), "env", filepath.Base(r.repo)+".env"), strings.Join(names, ", ")))
	}
	return nil
}

// makeWorktree cuts the run's checkout from that commit, on a branch whose name is free on
// the remote too: two runs that picked one locally would both push it, and the second is rejected
// after its work has passed.  An origin that cannot say is the empty set: naming is not worth
// failing a run over.
func (r *repoPlace) makeWorktree(l *loop, slug, start string) error {
	g := gitcall.Git{Repo: r.repo}
	taken := map[string]bool{}
	asked := g
	asked.Cap = time.Minute
	if code, out, _, err := asked.Run("ls-remote", "--heads", "origin", "refs/heads/ak/"+slug+"*"); err == nil && code == 0 {
		for _, line := range config.SplitLines(out) {
			if _, ref, found := strings.Cut(line, "\t"); found {
				taken[strings.TrimPrefix(ref, "refs/heads/")] = true
			}
		}
	}
	r.branch = "ak/" + slug
	for suffix := 2; ; suffix++ {
		found, err := g.Try("rev-parse", "--verify", "--quiet", "refs/heads/"+r.branch)
		if err != nil {
			return err
		}
		if !taken[r.branch] && found == "" {
			break
		}
		r.branch = fmt.Sprintf("ak/%s-%d", slug, suffix)
	}
	r.wt = filepath.Join(config.Home(), "wt", l.id)
	held, err := gitcall.PrepareCheckout(r.repo)
	if err != nil {
		return err
	}
	defer held.Close()
	code, out, err := g.Out("worktree", "add", "--lock", "--reason", gitcall.Making, r.wt, "-b", r.branch, start)
	if err == nil && code == 0 {
		code, out, err = g.Out("worktree", "unlock", r.wt)
	}
	if err != nil {
		return err
	}
	if code != 0 {
		return fmt.Errorf("git worktree add %s failed in %s: %s", r.wt, r.repo, out)
	}
	return nil
}

func (r *repoPlace) where(l *loop) string {
	merging := ""
	if r.target != r.base {
		merging = ", to be merged into " + r.target
	}
	return fmt.Sprintf("Repo checkout: %s\nBranch: %s (based on %s%s)", r.wt, r.branch, r.base, merging)
}

// rules is the body of the repository's AGENTS.md at the base commit, for every worker prompt: the
// work under review cannot rewrite the rules it is judged by.
func (r *repoPlace) rules() string {
	text := gitcall.AgentsBody(r.wt, r.baseSHA)
	if text == "" {
		return ""
	}
	return "\n\n## Repository AGENTS.md\nThe repository's own instructions, as on the base commit. Where they differ from the rest of this prompt, the rest of this prompt wins.\n\n" + text + "\n"
}

func (r *repoPlace) landing() (bool, string) {
	if r.noMerge {
		return false, ""
	}
	return true, run.DeclaredSuite(r.wt, r.target)
}

func (r *repoPlace) role(word string) string { return word }

func (r *repoPlace) beforeTurn(l *loop) { r.sweepSandboxes(l) }

// finished delivers the passed work, unless the run opted out of landing it.
func (r *repoPlace) finished(l *loop) error {
	if r.noMerge {
		return nil
	}
	return r.merge(l)
}

// head is a repository's opening of result.md: the diff stat never depends on git working.
func (r *repoPlace) head(_ string, record *run.Object) []string {
	stat := "(no changes)"
	said, err := r.git().Try("diff", "--stat", record.Str("base_sha")+"...HEAD")
	if err != nil {
		stat = "(cannot read the diff: " + err.Error() + ")"
	} else if said != "" {
		stat = said
	}
	pr, merged := "(none)", "no"
	if record.Truthy("pr") {
		pr = run.Text(record.Get("pr"))
	}
	if record.Truthy("merged") {
		merged = "yes"
	}
	parts := []string{"branch: " + run.Field(record, "branch", "None"), "pr: " + pr, "merged: " + merged}
	if record.Truthy("merge_note") {
		parts = append(parts, "merge: "+record.Str("merge_note"))
	}
	if retry := handback.RetryCommand(record); retry != "" {
		parts = append(parts, "retry delivery: "+retry)
	}
	executor := "-"
	if record.Truthy("executor") {
		executor = record.Str("executor")
	}
	return append(parts, "worktree: "+record.Str("worktree"),
		"executor: "+executor+"   reviewer: "+run.Field(record, "reviewer", "None"),
		"", "## Diff stat", "```", stat, "```")
}
