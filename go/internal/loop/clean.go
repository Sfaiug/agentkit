package loop

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/run"
	"agentkit/internal/uncommitted"
)

// cleanupLimit is how long a repository's `cleanup:` line may take.
const cleanupLimit = 10 * time.Minute

// Clean is `ak run clean <id>`, Python's cmd_clean: a run's checkout goes and its branch stays,
// with what was left uncommitted on it.  A refusal is an error, in Python's words.
func Clean(id string, out io.Writer) error {
	dir := filepath.Join(run.Runs(), id)
	record, _ := run.Read(dir)
	if record == nil {
		return fmt.Errorf("%s: cannot read %s", id, filepath.Join(dir, "run.json"))
	}
	if record.Truthy("scratch") {
		workspace := record.Str("worktree")
		if info, err := os.Stat(workspace); workspace == "" || err != nil || !info.IsDir() {
			fmt.Fprintf(out, "%s: its workspace is gone; result.md lists what was there\n", id)
			return nil
		}
		fmt.Fprintf(out, "%s: ran in the scratch workspace %s; its files are the deliverable, so nothing is removed\n", id, workspace)
		return nil
	}
	repo, worktree := record.Str("repo"), record.Str("worktree")
	if repo == "" || worktree == "" {
		return fmt.Errorf("%s: run.json records no worktree; nothing to remove", id)
	}
	if filepath.Clean(worktree) == filepath.Clean(repo) {
		fmt.Fprintf(out, "%s: ran with --no-worktree; nothing to remove\n", id)
		return nil
	}
	var told []string
	if !stopCheckout(dir, record, func(line string) { told = append(told, strings.TrimPrefix(line, "WARN ")) }, true) {
		return fmt.Errorf("%s: %s", id, strings.Join(told, "; "))
	}
	fmt.Fprintf(out, "%s: removed worktree %s; branch %s kept\n", id, worktree, run.Field(record, "branch", "?"))
	return nil
}

// safe is no link among a path's ancestors, and it a folder of this account's, Python's
// retention.safe where a checkout goes by hand.
func safe(path string) bool {
	if !filepath.IsAbs(path) {
		return false
	}
	for at := path; ; at = filepath.Dir(at) {
		info, err := os.Lstat(at)
		if err != nil || info.Mode()&os.ModeSymlink != 0 {
			return false
		}
		if filepath.Dir(at) == at {
			break
		}
	}
	info, err := os.Lstat(path)
	return err == nil && info.IsDir() && owned(info)
}

// stopCheckout takes a run's worktree, and its local branch unless kept, Python's stop_checkout:
// true when nothing asked to go is left.  A kept branch takes the checkout's committable work
// first, the repository's `cleanup:` line runs while the checkout is there, and git only runs in
// the repository, never itself what goes.  A live loop, and anything under ~/code, is not this
// run's to delete.
func stopCheckout(dir string, record *run.Object, log func(string), keepBranch bool) bool {
	repo, worktree, branch := record.Str("repo"), record.Str("worktree"), record.Str("branch")
	if record.Truthy("scratch") || repo == "" || worktree == "" || filepath.Clean(worktree) == filepath.Clean(repo) {
		return true
	}
	if config.UnderCode(worktree) {
		home, _ := os.UserHomeDir()
		log(fmt.Sprintf("WARN left worktree %s: it is under %s", worktree, filepath.Join(home, "code")))
		return false
	}
	if pid, _ := record.Int("pid"); pid != os.Getpid() && run.ProcessActive(record) {
		log(fmt.Sprintf("WARN left worktree %s: the run is still going", worktree))
		return false
	}
	_, statErr := os.Lstat(worktree)
	if keepBranch && statErr == nil && !preserveCheckout(dir, record, log) {
		return false
	}
	if record.Truthy("run_id") {
		runCleanup(worktree, dir)
	}
	g := gitcall.Git{Repo: repo}
	code, out, err := g.Out("worktree", "remove", "--force", worktree)
	if err != nil {
		log(fmt.Sprintf("WARN could not remove worktree %s: %v", worktree, err))
		return false
	}
	if code != 0 && filepath.Dir(worktree) == filepath.Join(config.Home(), "wt") && safe(worktree) {
		os.RemoveAll(worktree)
	}
	if _, err := g.Try("worktree", "prune"); err != nil {
		log(fmt.Sprintf("WARN could not prune worktrees in %s: %v", repo, err))
	}
	if _, gone := os.Lstat(worktree); code != 0 && gone == nil {
		log(fmt.Sprintf("WARN could not remove worktree %s: %s", worktree, out))
		return false
	}
	return keepBranch || dropBranch(g, branch, log)
}

// dropBranch deletes the run's local `ak/` branch once nothing has it checked out: the prefix is
// the guard, as the repository is the owner's.
func dropBranch(g gitcall.Git, branch string, log func(string)) bool {
	if !strings.HasPrefix(branch, "ak/") {
		return true
	}
	held, err := gitcall.HoldRepository(g)
	if err != nil {
		log(fmt.Sprintf("WARN could not delete branch %s: %v", branch, err))
		return false
	}
	defer held.Close()
	found, err := g.Try("rev-parse", "--verify", "--quiet", "refs/heads/"+branch)
	if err == nil && found == "" {
		return true
	}
	code, out := 0, ""
	if err == nil {
		code, out, err = g.Out("branch", "-D", branch)
	}
	if err != nil {
		log(fmt.Sprintf("WARN could not delete branch %s: %v", branch, err))
		return false
	}
	if code != 0 {
		log(fmt.Sprintf("WARN could not delete branch %s: %s", branch, out))
		return false
	}
	return true
}

// preserveCheckout puts the checkout's work on its branch, or holds it for the seven-day clock,
// Python's preserve_checkout.  Hooks may rewrite or refuse work; saving it must do neither.
func preserveCheckout(dir string, record *run.Object, log func(string)) bool {
	worktree, branch := record.Str("worktree"), record.Str("branch")
	err := saveWork(record)
	if err == nil {
		return true
	}
	record.Set("checkout_kept", true)
	if record.Truthy("run_id") {
		run.Change(dir, func(current *run.Object) error {
			current.Set("checkout_kept", true)
			return nil
		})
	}
	log(fmt.Sprintf("WARN left worktree %s: could not save its work on %s: %v", worktree, branch, err))
	return false
}

func saveWork(record *run.Object) error {
	worktree, branch := record.Str("worktree"), record.Str("branch")
	g := gitcall.Git{Repo: worktree}
	artifacts := map[string]bool{}
	for _, name := range names(record.List("artifacts")) {
		artifacts[name] = true
	}
	on, err := g.Must("symbolic-ref", "--quiet", "HEAD")
	if err != nil {
		return err
	}
	stopped, err := inProgress(g)
	if err != nil {
		return err
	}
	if on != "refs/heads/"+branch || stopped {
		return fmt.Errorf("the checkout is off %s or a rebase or merge is unfinished", branch)
	}
	real, _, err := uncommitted.Committable(g, artifacts)
	if err != nil {
		return err
	}
	if len(real) > 0 {
		if err := uncommitted.Add(g, real); err != nil {
			return err
		}
		title := record.Str("title")
		if title == "" {
			title = "Save run work"
		}
		// --only takes these paths, leaving staged junk and done-when artifacts out
		args := []string{"-c", "core.hooksPath=" + os.DevNull, "commit", "--only", "-m", title, "--"}
		for _, path := range real {
			args = append(args, ":(literal)"+path)
		}
		if _, err := g.Must(args...); err != nil {
			return err
		}
	}
	remaining, left, err := uncommitted.Committable(g, artifacts)
	if err != nil {
		return err
	}
	// work staged differently from the working file may be invisible to diff HEAD
	staged, err := g.Must("diff", "--cached", "--no-renames", "--name-only", "-z", "HEAD")
	if err != nil {
		return err
	}
	unsaved := len(remaining) > 0
	for _, path := range paths(staged) {
		known := artifacts[path]
		for _, each := range left {
			known = known || each == path
		}
		unsaved = unsaved || !known
	}
	if unsaved {
		return errors.New("uncommitted work remains")
	}
	held, err := gitcall.Git{Repo: record.Str("repo")}.Must("rev-parse", "--verify", "refs/heads/"+branch)
	if err != nil {
		return err
	}
	head, err := g.Must("rev-parse", "HEAD")
	if err != nil {
		return err
	}
	if held != head {
		return fmt.Errorf("the branch in %s does not hold the checkout's commit", record.Str("repo"))
	}
	return nil
}

// inProgress is whether a rebase or a merge is still sitting in the checkout, its own git
// directory's name kept byte for byte.
func inProgress(g gitcall.Git) (bool, error) {
	code, out, said, err := g.Bytes("rev-parse", "--absolute-git-dir")
	if err != nil {
		return false, err
	}
	if code != 0 {
		return false, fmt.Errorf("git rev-parse --absolute-git-dir failed in %s: %s", g.Repo, gitcall.Strip(string(said)))
	}
	own := strings.TrimSuffix(string(out), "\n")
	for _, name := range []string{"rebase-merge", "rebase-apply", "MERGE_HEAD"} {
		if _, err := os.Stat(filepath.Join(own, name)); err == nil {
			return true, nil
		}
	}
	return false, nil
}

// runCleanup is the repository's `cleanup:` line, once, in the checkout before it goes, Python's
// run_repo_cleanup: it undoes what no removal of the checkout can reach.  `cleanup.log` going up
// is the mark, claimed atomically, so a retried removal never re-runs it.  It gets the repository's
// secrets in its own environment only: whatever calls this may clean several repositories.
// Whatever it does the removal goes ahead and the record is untouched.
func runCleanup(worktree, dir string) {
	line := gitcall.Declared(worktree, "cleanup")
	if info, err := os.Stat(worktree); line == "" || err != nil || !info.IsDir() {
		return
	}
	file, err := os.OpenFile(filepath.Join(dir, "cleanup.log"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o666)
	if err != nil {
		return
	}
	defer file.Close()
	fmt.Fprintf(file, "$ %s\n", line)
	outcome := cleanupOutcome(line, worktree, dir, file)
	appendLog(dir, stamped(fmt.Sprintf("repo cleanup: %s %s (see cleanup.log)", line, outcome)))
}

func cleanupOutcome(line, worktree, dir string, file *os.File) string {
	env := os.Environ()
	record, _ := run.Read(dir)
	if record != nil && record.Truthy("repo") {
		secrets, err := config.RepoEnv(record.Str("repo"))
		if err != nil {
			outcome := "could not run: " + err.Error()
			fmt.Fprintf(file, "[%s]\n", outcome)
			return outcome
		}
		for key, value := range secrets {
			env = append(env, key+"="+value)
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), cleanupLimit)
	defer cancel()
	command := exec.CommandContext(ctx, "bash", "-c", line)
	command.Dir, command.Env, command.Stdout, command.Stderr = worktree, env, file, file
	err := command.Run()
	var exit *exec.ExitError
	switch {
	case ctx.Err() != nil:
		outcome := fmt.Sprintf("timed out after %d minutes", int(cleanupLimit.Minutes()))
		fmt.Fprintf(file, "[%s]\n", outcome)
		return outcome
	case errors.As(err, &exit):
		return fmt.Sprintf("exited %d", exit.ExitCode())
	case err != nil:
		outcome := "could not run: " + err.Error()
		fmt.Fprintf(file, "[%s]\n", outcome)
		return outcome
	}
	return "exited 0"
}
