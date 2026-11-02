package loop

import (
	"context"
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
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// making is the reason ak locks a checkout it makes while git makes it, so a maker killed before
// it unlocks leaves one gc knows holds nothing yet.
const making = "ak is making this checkout"

var refName = regexp.MustCompile(`^refs/(heads|remotes/origin)/`)

// repoPlace is a repository's run: a checkout of its own on a branch of its own, or the
// repository's own checkout with --no-worktree.
type repoPlace struct {
	repo, wt, branch      string
	base, target, baseSHA string
	noWorktree, noMerge   bool
	followup              bool
	artifacts             map[string]bool
	checked, viewed       [2]string // the commit and tree the round's checks ran on, and its review read
	title                 string
	files                 []string
}

// repoFrom is the place a record describes.
func repoFrom(record *run.Object) *repoPlace {
	opts := record.Dict("launch_opts")
	return &repoPlace{repo: record.Str("repo"), wt: record.Str("worktree"), branch: record.Str("branch"), base: record.Str("base"),
		target: record.Str("target"), baseSHA: record.Str("base_sha"), title: record.Str("title"),
		noWorktree: opts != nil && opts.Truthy("--no-worktree"), noMerge: record.Truthy("no_merge") || opts != nil && opts.Truthy("--no-merge"),
		followup: record.Truthy("followup"), artifacts: map[string]bool{}}
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

// noAutoGC turns git's own gc off in the checkout: linked worktrees share this config, and a
// turn's detached gc can lock all their HEADs, then leave those locks behind when the worker
// stops its leftover processes.  It holds the lock gc takes on the shared git directory.
func noAutoGC(repo string) error {
	g := gitcall.Git{Repo: repo, Env: gitcall.ProjectEnv(repo)}
	held, err := holdRepository(g)
	if err != nil {
		return err
	}
	defer held.Close()
	return gcOff(g)
}

func gcOff(g gitcall.Git) error {
	for _, setting := range [][2]string{{"gc.auto", "0"}, {"maintenance.auto", "false"}} {
		said, err := g.Try("config", "--local", "--get", setting[0])
		if err != nil {
			return err
		}
		if said != setting[1] {
			if _, err := g.Must("config", "--local", "--replace-all", setting[0], setting[1]); err != nil {
				return err
			}
		}
		if said, err = g.Try("config", "--get", setting[0]); err != nil {
			return err
		}
		if said != setting[1] {
			if _, err := g.Must("config", "--worktree", "--replace-all", setting[0], setting[1]); err != nil {
				return err
			}
		}
	}
	return nil
}

// holdRepository takes the lock on the shared git directory itself: preparation waits for gc, and
// gc skips a preparation in progress.
func holdRepository(g gitcall.Git) (*os.File, error) {
	common, err := g.Must("rev-parse", "--path-format=absolute", "--git-common-dir")
	if err != nil {
		return nil, err
	}
	return lock.Wait(context.Background(), common)
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
// it now, the checkout, the record naming it before anything else can fail, the exclude, and the
// repository's secrets, which from here every worker and check has.
func (r *repoPlace) open(l *loop, meta map[string]string, path string, common []any) error {
	from := gitcall.Strip(meta["from"])
	why, err := r.fromRefusal(path, from)
	if err != nil {
		return err
	}
	if why != "" {
		return errors.New(why)
	}
	if from != "" {
		return notYet(fmt.Sprintf("%s: from: %s", path, from), "a run from a branch")
	}
	if err := noAutoGC(r.repo); err != nil {
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
	if r.noWorktree {
		r.wt = r.repo
		if r.branch, err = g.Must("rev-parse", "--abbrev-ref", "HEAD"); err != nil {
			return err
		}
		l.say(fmt.Sprintf("no worktree: working directly in %s on %s", r.wt, r.branch))
	} else if err := r.makeWorktree(l); err != nil {
		return err
	}
	l.workspace, l.usersAt = r.wt, r.upstream()
	err = l.save(func(record *run.Object) {
		run.SetAll(record, "repo", r.repo, "scratch", false, "base", r.base, "target", r.target, "base_sha", r.baseSHA,
			"branch", r.branch, "worktree", r.wt, "no_merge", r.noMerge)
		run.SetAll(record, common...)
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
		l.say(fmt.Sprintf("worktree %s on %s from %s (%s)%s", r.wt, r.branch, r.base, r.baseSHA[:12], merging))
	}
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

// makeWorktree cuts the run's checkout from the pinned base, on a branch whose name is free on
// the remote too: two runs that picked one locally would both push it, and the second is rejected
// after its work has passed.  An origin that cannot say is the empty set: naming is not worth
// failing a run over.
func (r *repoPlace) makeWorktree(l *loop) error {
	g := gitcall.Git{Repo: r.repo}
	slug := task.Slug(l.title)
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
	held, err := holdRepository(gitcall.Git{Repo: r.repo, Env: gitcall.ProjectEnv(r.repo)})
	if err != nil {
		return err
	}
	defer held.Close()
	if err := gcOff(gitcall.Git{Repo: r.repo, Env: gitcall.ProjectEnv(r.repo)}); err != nil {
		return err
	}
	code, out, err := g.Out("worktree", "add", "--lock", "--reason", making, r.wt, "-b", r.branch, r.baseSHA)
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

// finished ends a run that lands where its landing starts: the review it earned stays on the
// record, for Python's `ak run resume` to carry on from.
func (r *repoPlace) finished(*loop) error {
	if r.noMerge {
		return nil
	}
	return notYet("the review passed", "landing it")
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
	executor := "-"
	if record.Truthy("executor") {
		executor = record.Str("executor")
	}
	return append(parts, "worktree: "+record.Str("worktree"),
		"executor: "+executor+"   reviewer: "+run.Field(record, "reviewer", "None"),
		"", "## Diff stat", "```", stat, "```")
}
