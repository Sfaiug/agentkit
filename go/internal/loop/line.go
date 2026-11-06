package loop

// The landing line, Python's land.py with deliver.join_line, release_line, rejoin_line and
// land_from_line: a passed run on a writable repository waits in its line, processless, the lander
// checks its tree on the target's tip once, and the run, woken on that verdict, delivers the very
// tree checked.  It hides the line's files, each Python's, beside the delivery lock every landing
// on that repository and target takes (`.merge-<key>.lock`, which names the line): the lander's
// lock (`.lander.lock`), the verdicts it keeps (`.green`, under `.green.lock`), its passes
// (`.passes`) and its log (`.log`).  Its interface is join (joinLine, then releaseLine as the run
// leaves), check (CheckLine, `ak run --lander`) and land (landFromLine, in the woken run).
//
// Stacks share the single member's checks and delivery; narrow.go searches a red by what failed.
// Target repairs, reds with suite helpers and PR reviews remain Python's once this releases its
// lock.

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

const (
	keepEvidence = 24 * time.Hour // a tree checked longer ago lands through its own suite again
	checkedPass  = time.Minute    // a pass shorter than this checked nothing: it says nothing of the pace
)

// beside is the line's file of that suffix, Python's turn.with_suffix.
func beside(turn, suffix string) string { return strings.TrimSuffix(turn, ".lock") + suffix }

// landingLine is the line a record waits on or was woken from, "" for none.
func landingLine(record *run.Object) string {
	if wait := record.Dict("waiting_on"); wait != nil {
		return wait.Str("line")
	}
	return ""
}

// parkedInLine is whether the run waits in its line with no process of its own, Python's
// landing_line: the lander's to wake.
func parkedInLine(record *run.Object) bool {
	return record != nil && record.Str("state") == "waiting" && landingLine(record) != ""
}

// green is a verdict to deliver: the tree checked, and no fixer owed.
func green(wait *run.Object) bool { return wait != nil && wait.Has("land") && !wait.Has("fix") }

// joinLine takes a passed run into its line, rebased onto the target and unchecked, Python's
// join_line: the line's check is the one check of its tree before it merges.  A run woken from
// the line lands instead.
func (r *repoPlace) joinLine(l *loop, upstream string, deliver func() error) error {
	record, err := run.Read(l.dir)
	if record == nil {
		return cmp.Or(err, errors.New("run.json cannot be read"))
	}
	if landingLine(record) != "" {
		return r.landFromLine(l, upstream, record, deliver)
	}
	if err := r.requireReviewPass(l); err != nil {
		return err
	}
	integrated := false
	if err := r.landingMark(l, func() (err error) {
		integrated, err = r.integrate(l, upstream)
		return err
	}); err != nil || !integrated {
		return err
	}
	if err := r.requireReviewPass(l); err != nil {
		return err
	}
	turn, err := r.turn(upstream)
	if err != nil {
		return err
	}
	return l.save(func(record *run.Object) {
		run.SetAll(record, "state", "waiting", "waiting_on", run.Fields("line", filepath.Base(turn), "joined", clock()),
			"error", "waiting for the lander", "finished_at", nil)
		record.Delete("recovery_pending")
	})
}

// releaseLine leaves the run's place to its lander as its process ends, Python's release_line:
// what it started ends first, so the lander never wakes a run something of its last attempt holds.
func releaseLine(dir string, said io.Writer) {
	line := ""
	run.Change(dir, func(record *run.Object) error {
		if pid, _ := record.Int("pid"); !parkedInLine(record) || pid != os.Getpid() {
			return nil
		}
		host.EndMarked(dir, said)
		run.SetAll(record, "pid", nil, "process_identity", nil)
		line = landingLine(record)
		return nil
	})
	if line != "" {
		startLine(filepath.Join(run.Runs(), line), said)
	}
}

// rejoinLine puts a woken run back in its place, Python's rejoin_line: checked again soon, it
// meets the target it was checked against, not one moved by every landing behind it.
func (r *repoPlace) rejoinLine(l *loop, wait *run.Object, reason string) error {
	l.say("rejoins the line: " + reason)
	return l.save(func(record *run.Object) {
		run.SetAll(record, "state", "waiting", "error", reason, "merge_failed", false, "merge_note", reason,
			"waiting_on", run.Fields("line", wait.Get("line"), "joined", wait.Get("joined")))
		record.Delete("recovery_pending")
	})
}

// landFromLine is a woken run taking its lander's verdict, Python's land_from_line: on green it
// takes the target's tip in under the delivery lock and delivers, if that makes the tree the
// lander checked; a red is its landing fixer's (landfix.go).
func (r *repoPlace) landFromLine(l *loop, upstream string, record *run.Object, deliver func() error) error {
	wait := record.Dict("waiting_on")
	if !green(wait) {
		if wait.Has("fix") {
			return r.fixLanding(l, upstream, record, wait)
		}
		return r.rejoinLine(l, wait, "waiting for the lander")
	}
	turn, err := r.turn(upstream)
	if err != nil {
		return err
	}
	// what left the line, or rejoined it, did so under the lock: the next pass checks what is left
	defer startLine(turn, stampedLog{l.dir})
	held, err := r.mergeLock(l, upstream)
	if err != nil {
		return err
	}
	defer held.Close()
	g := r.git()
	code, out, err := g.Fetch("origin", "--prune")
	if err != nil {
		return err
	}
	if code != 0 {
		return r.note(l, "git fetch origin --prune failed: "+tail(out, 400), true)
	}
	tip, err := g.Must("rev-parse", upstream+"^{commit}")
	if err != nil {
		return err
	}
	how, err := r.how(record)
	if err != nil {
		return err
	}
	if code, _, err := g.Out(integration(how, tip)...); err != nil || code != 0 {
		r.abort(l, how, err != nil)
		if err != nil {
			return err
		}
		return r.rejoinLine(l, wait, fmt.Sprintf("its %s onto %s at %s stopped on a conflict; the lander checks it again", how, upstream, tip[:12]))
	}
	r.baseSHA = tip
	head, tree, err := r.identity()
	if err != nil {
		return err
	}
	saved := cmp.Or(record.Dict("review"), run.NewObject())
	if err := l.save(func(record *run.Object) {
		review := run.SetAll(saved.Copy(), "head_sha", head, "tree_sha", tree, "passed_head_sha", passedReviewHead(record),
			"rebased_from", saved.Get("head_sha"))
		run.SetAll(record, "base_sha", tip, "target_sha", tip, "review", review)
	}); err != nil {
		return err
	}
	if land := wait.Str("land"); tree != land {
		return r.rejoinLine(l, wait, fmt.Sprintf("on %s at %s its tree is %s, not the %s the lander checked: a change stacked ahead of it has not landed yet, or %s moved",
			upstream, tip[:12], tree[:12], land[:min(12, len(land))], upstream))
	}
	if code, _, err := g.Out("diff", "--quiet", tip, "HEAD"); err != nil || code == 0 {
		if err != nil {
			return err
		}
		if err := l.save(func(record *run.Object) { record.Set("on_target", true); leaveLine(record) }); err != nil {
			return err
		}
		return r.note(l, "its work is already on "+strings.TrimPrefix(upstream, "origin/"), false)
	}
	tested := wait.Str("tested")
	if tested == "" {
		tested = cmp.Or(evidence(turn, "trees").Dict(wait.Str("land")), run.NewObject()).Str("tested")
	}
	var suite any
	if declared := gitcall.Suite(r.wt, tip); declared != "" {
		suite = declared
	}
	if err := l.save(func(record *run.Object) {
		record.Set("final_check", run.Fields("outcome", "passed", "where", "landing", "sha", head, "tree_sha", tree,
			"tested", cmp.Or(tested, tree), "suite", suite))
	}); err != nil {
		return err
	}
	if err := deliver(); err != nil {
		return err
	}
	return l.save(func(record *run.Object) {
		switch {
		case record.Dict("waiting_on") != nil && record.Dict("waiting_on").Has("fix"):
			// red required checks owe a fixer: the run parks on that verdict for the lander's wake
			record.Set("state", "waiting")
		case record.Truthy("merged"):
			leaveLine(record)
		}
	})
}

// leaveLine takes the record out of its line, the counts of its landing with it.
func leaveLine(record *run.Object) {
	for _, key := range []string{"waiting_on", "landing_reds", "landing_conflicts"} {
		record.Delete(key)
	}
}

// startLine starts a lander on the line where none runs and a member waits with no process of its
// own, Python's start_line: `ak run --lander`, apart from whatever started it, into the line's log.
func startLine(turn string, said io.Writer) {
	if filepath.Dir(turn) != run.Runs() || !strings.HasPrefix(filepath.Base(turn), ".merge-") {
		return
	}
	held, err := lock.Try(beside(turn, ".lander.lock"))
	if err != nil {
		if !errors.Is(err, lock.ErrHeld) {
			fmt.Fprintf(said, "WARN could not start lander for %s: %v\n", filepath.Base(turn), err)
		}
		return
	}
	ready := slices.ContainsFunc(lineMembers(filepath.Base(turn)), func(m member) bool {
		return m.record.Str("state") == "waiting" && !run.ProcessActive(m.record)
	})
	held.Close()
	if !ready {
		return // the joining attempt finishes its cleanup before a wake
	}
	env, err := config.ChildEnv()
	if err == nil {
		// this work outlives its caller and must not belong to the caller's stop sweep
		env = slices.DeleteFunc(env, func(pair string) bool {
			key, _, _ := strings.Cut(pair, "=")
			return slices.Contains([]string{host.Marker, "AK_PARENT_RUN", "AK_RUN_LOG", "AK_RUN_ROLE", "AK_RUN_DEPTH",
				"AGENTKIT_JOB_DIR", "AGENTKIT_SESSION", "AGENTKIT_UNATTENDED"}, key)
		})
		err = detach(beside(turn, ".log"), append(env, "AK_RUN_DEPTH=0"), "run", "--lander", filepath.Base(turn))
	}
	if err != nil {
		fmt.Fprintf(said, "WARN could not start lander for %s: %v\n", filepath.Base(turn), err)
	}
}

// detach starts this program with args in a session of its own, appending to log.
func detach(log string, env []string, args ...string) error {
	self, err := os.Executable()
	if err != nil {
		return err
	}
	out, err := os.OpenFile(log, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666)
	if err != nil {
		return err
	}
	defer out.Close()
	cmd := exec.Command(self, args...)
	cmd.Env, cmd.Stdout, cmd.Stderr, cmd.SysProcAttr = env, out, out, host.Detached()
	if err := cmd.Start(); err != nil {
		return err
	}
	go cmd.Wait() // a zombie still answers as alive
	return nil
}

// Logging is whether this process writes into the run's log, as a lander's wake does, Python's
// log_is_stdout.
func Logging(dir string) bool {
	log, err := os.Stat(filepath.Join(dir, "log.txt"))
	if err != nil {
		return false
	}
	out, err := os.Stdout.Stat()
	return err == nil && os.SameFile(log, out)
}

// A member is a run in a line, as read.
type member struct {
	dir    string
	record *run.Object
}

// lineMembers is Python's land.line: the runs holding a place in the line (run.Member), in its order.
func lineMembers(name string) (found []member) {
	for _, dir := range run.Dirs() {
		if record, _ := run.Read(dir); record != nil && run.Member(record) && landingLine(record) == name {
			found = append(found, member{dir, record})
		}
	}
	return orderMembers(found)
}

// wake starts the member's own `ak run resume` on the verdict written to it, under its lock.
func wake(dir string, said io.Writer) {
	err := run.Change(dir, func(record *run.Object) error {
		if record.Str("state") == "stopped" {
			return nil
		}
		return resume(dir, record)
	})
	if err != nil {
		fmt.Fprintf(said, "WARN could not resume %s: %v\n", filepath.Base(dir), err)
	}
}

// resume starts the run's own `ak run resume`, Python's launch_resume: into its log, at the depth
// its record holds.
func resume(dir string, record *run.Object) error {
	env, err := config.ChildEnv()
	if err != nil {
		return err
	}
	depth, _ := record.Int("run_depth")
	return detach(filepath.Join(dir, "log.txt"), append(env, fmt.Sprintf("AK_RUN_DEPTH=%d", depth)), "run", "resume", filepath.Base(dir))
}

// CheckLine is `ak run --lander LINE`, Python's check_line: under the line's own lock, which a
// lander already holding it keeps, members are checked on the stack ahead and woken on their
// verdict, a verdict saved for it is published again, and anything else waits for Python's.
func CheckLine(name string, out io.Writer) int {
	host.Lower()
	turn := filepath.Join(run.Runs(), name)
	code := ourCode() // read as the pass starts: an update installed during a check is not this pass's
	held, err := lock.Try(beside(turn, ".lander.lock"))
	if errors.Is(err, lock.ErrHeld) {
		return 0
	}
	if err != nil {
		fmt.Fprintf(out, "ak run: %v\n", err)
		return 2
	}
	defer held.Close()
	took := passes(turn)
	started := time.Now()
	keepPasses(turn, run.Fields("took", took, "started", clock(), "pid", os.Getpid(), "process_identity", identity(os.Getpid())))
	err = checkTurn(turn, code, stampedOut{out})
	if spent := time.Since(started); spent >= checkedPass {
		took = append(took, spent.Seconds())[max(0, len(took)+1-20):]
	}
	keepPasses(turn, run.Fields("took", took))
	if err != nil {
		fmt.Fprintf(out, "ak run: %v\n", err)
		return 2
	}
	return 0
}

// A stampedOut writes each line given it with its time, as Python's say does.
type stampedOut struct{ out io.Writer }

func (w stampedOut) Write(data []byte) (int, error) {
	for _, line := range config.SplitLines(string(data)) {
		io.WriteString(w.out, stamped(line))
	}
	return len(data), nil
}

// passes is the seconds the line's last passes took that checked something.
func passes(turn string) []any {
	kept, _ := run.ReadJSON(beside(turn, ".passes"))
	if kept == nil {
		return []any{}
	}
	return append([]any{}, kept.List("took")...)
}

func keepPasses(turn string, data *run.Object) {
	path := beside(turn, ".passes")
	if os.WriteFile(path+".new", []byte(run.Encode(data)), 0o666) == nil {
		os.Rename(path+".new", path)
	}
}

// unchanged is whether the member's record is still the one read, with no process of its own.
func unchanged(dir string, saved *run.Object) bool {
	same := false
	run.Change(dir, func(current *run.Object) error {
		same = run.Equal(current, saved) && !run.ProcessActive(current)
		return nil
	})
	return same
}

// publish writes the verdict onto the member, Python's publish: only a record still the one this
// pass read, with no process of its own, takes it.  A green wakes at once; a red is the pass's
// wake's (wakes.go), told of it.
func publish(dir string, saved, verdict *run.Object, said io.Writer) bool {
	err := run.Change(dir, func(current *run.Object) error {
		if !run.Equal(current, saved) || run.ProcessActive(current) {
			return errStale
		}
		wait := current.Dict("waiting_on").Copy()
		for _, key := range verdict.Keys() {
			wait.Set(key, verdict.Get(key))
		}
		current.Set("waiting_on", wait)
		return nil
	})
	if err != nil {
		return false
	}
	if verdict.Has("fix") {
		redGiven()
	} else {
		wake(dir, said)
	}
	return true
}

var errStale = errors.New("the line changed during this pass")

func minutes(record *run.Object, key string, fallback float64) time.Duration {
	return time.Duration(number(record, key, fallback) * float64(time.Minute))
}

func number(record *run.Object, key string, fallback float64) float64 {
	if value, ok := record.Num(key); ok {
		return value
	}
	return fallback
}

// addScratch checks the commit out at path, detached, Python's add_worktree with the scratch mark:
// locked while git makes it, so gc takes one a killed lander left, and no other checkout for it.
func addScratch(repo, path, commit string) (int, string, error) {
	g := gitcall.Git{Repo: repo, Env: gitcall.ProjectEnv(repo)}
	held, err := gitcall.PrepareCheckout(repo)
	if err != nil {
		return 0, "", err
	}
	defer held.Close()
	code, out, err := g.Out("worktree", "add", "--lock", "--reason", gitcall.Making, path, "--detach", commit)
	if err != nil || code != 0 {
		return code, out, err
	}
	own, err := gitcall.Git{Repo: path}.Must("rev-parse", "--absolute-git-dir")
	if err == nil {
		err = os.WriteFile(filepath.Join(own, gitcall.ScratchMark), nil, 0o666)
	}
	if err != nil {
		return 0, "", err
	}
	return g.Out("worktree", "unlock", path)
}

// fixed is the red a step before the checks leaves: its text in the member's log of that name.
func (l *loop) fixed(name, text string, conflict bool) *run.Object {
	path := filepath.Join(l.dir, name)
	os.WriteFile(path, []byte(text), 0o666)
	fix := run.Fields("line", firstFailure(text), "log", path)
	if conflict {
		fix.Set("conflict", true)
	}
	return run.Fields("fix", fix, "after", run.NewObject())
}

// checkTree runs the checks on the scratch checkout, pinned to its commit, Python's _check: whether
// they passed, the line that says what failed, and the first command that failed, the suite where
// none did yet they did not pass.
func (l *loop) checkTree(scratch string, checks []string, name, suite string, selections ...*checkSelection) (bool, string, string, error) {
	in := gitcall.Git{Repo: scratch}
	place := &repoPlace{wt: scratch}
	head, tree, err := place.identity()
	if err != nil {
		return false, "", "", err
	}
	dirty, _, err := in.Out("diff", "--quiet", "HEAD")
	if err != nil {
		return false, "", "", err
	}
	path := filepath.Join(l.dir, name)
	ok, text, marks, err := l.checksIn(scratch, checks, path, selections...)
	if err != nil {
		return false, "", "", err
	}
	if moved, err := place.changedSince(head, tree); err != nil || moved || dirty != 0 {
		if err != nil {
			return false, "", "", err
		}
		ok = false
		if selection := selectedCheck(selections); selection != nil {
			selection.handoff = true
		}
		text += "\n\nCheckout changed during the final check; these commands do not verify the pinned commit."
	}
	text = fmt.Sprintf("Commit: %s\nTree: %s\n\n%s", head, tree, text)
	if err := os.WriteFile(path, []byte(text), 0o666); err != nil || ok {
		return ok, "", "", err
	}
	failing := suite
	for i, mark := range marks {
		if mark == nil || *mark != 0 {
			failing = checks[i]
			break
		}
	}
	if len(marks) == 0 {
		failing = ""
	}
	return false, firstFailure(text), failing, nil
}

// landingChecks are the member's own landing checks on the scratch checkout, Python's
// _landing_checks: its `# once` commands and the target's suite, and a `tests:` line the change
// rewrites, which every later change would land through.
func landingChecks(dir, scratch, tip string) ([]string, error) {
	_, cmds, err := task.Read(filepath.Join(dir, "task.md"))
	if err != nil {
		return nil, err
	}
	suite := gitcall.Suite(scratch, tip)
	_, once := task.Group(task.RoundCommands(cmds, suite, true))
	if own := gitcall.Declared(scratch, "tests"); own != "" && own != suite && !slices.Contains(once, own) {
		once = append(once, own)
	}
	return once, nil
}

// covers is whether evidence that ran those checks answers for these, in their order.
func covers(ran []any, checks []string) bool {
	at := 0
	for _, check := range checks {
		for at < len(ran) && run.Text(ran[at]) != check {
			at++
		}
		if at == len(ran) {
			return false
		}
		at++
	}
	return true
}

func toList(items []string) []any {
	list := []any{}
	for _, item := range items {
		list = append(list, item)
	}
	return list
}

func pairs(object *run.Object) []any {
	var found []any
	for _, key := range object.Keys() {
		found = append(found, key, object.Get(key))
	}
	return found
}

// ourCode is the ak commit this lander checks under, Python's _code: what another commit's lander
// saw holds only once both commits passed a check of the line.
func ourCode() string {
	repo := config.Repo()
	if repo == "" {
		return ""
	}
	code, _ := gitcall.Git{Repo: repo}.Try("rev-parse", "HEAD")
	return code
}

func codeValue(code string) any {
	if code == "" {
		return nil
	}
	return code
}

// evidence is the line's verdicts of that kind by tree, Python's _trees: a pass older than a day is
// forgotten, a red the target was found never.
func evidence(turn, kind string) *run.Object {
	kept, _ := run.ReadJSON(beside(turn, ".green"))
	found := run.NewObject()
	entries := cmp.Or(kept, run.NewObject()).Dict(kind)
	if entries == nil {
		return found
	}
	for _, tree := range entries.Keys() {
		entry := entries.Dict(tree)
		if entry == nil {
			continue
		}
		if at, _ := entry.Num("at"); kind == "red" || time.Since(time.Unix(0, int64(at*1e9))) < keepEvidence {
			found.Set(tree, entry)
		}
	}
	return found
}

// answering is the evidence of that kind this lander trusts, Python's _answering: its own commit's,
// and another's once that commit and this one each passed a check of the line.
func answering(turn, code, kind string) *run.Object {
	passing := map[string]bool{}
	trees := evidence(turn, "trees")
	for _, tree := range trees.Keys() {
		passing[trees.Dict(tree).Str("code")] = true
	}
	for _, key := range evidence(turn, "passed").Keys() {
		passing[key] = true
	}
	delete(passing, "")
	found := run.NewObject()
	entries := evidence(turn, kind)
	for _, tree := range entries.Keys() {
		theirs := entries.Dict(tree).Str("code")
		if theirs == code || passing[theirs] && passing[code] && theirs != "" && code != "" {
			found.Set(tree, entries.Dict(tree))
		}
	}
	return found
}

// note changes the line's evidence under its lock, Python's note: a pass a later one of the same
// tree replaces stays on record as its commit's (`passed`), as it still proves that commit passed
// the line.
func note(turn string, change func(trees, red, redStacks *run.Object)) {
	held, err := lock.Wait(context.Background(), beside(turn, ".green.lock"))
	if err != nil {
		return
	}
	defer held.Close()
	trees, red, redStacks, passed := evidence(turn, "trees"), evidence(turn, "red"), evidence(turn, "red_stacks"), evidence(turn, "passed")
	before := map[string]*run.Object{}
	for _, tree := range trees.Keys() {
		before[tree] = trees.Dict(tree)
	}
	change(trees, red, redStacks)
	for tree, old := range before {
		if replaced := trees.Dict(tree); replaced != old && old.Str("code") != "" {
			at, _ := old.Num("at")
			if kept := passed.Dict(old.Str("code")); kept != nil {
				earlier, _ := kept.Num("at")
				at = max(at, earlier)
			}
			passed.Set(old.Str("code"), run.Fields("at", at))
		}
	}
	for _, tree := range trees.Keys() {
		if trees.Dict(tree) != before[tree] {
			redStacks.Delete(tree) // a tree that passed holds no earlier red
		}
	}
	path := beside(turn, ".green")
	data := run.Encode(run.Fields("trees", trees, "red", red, "red_stacks", redStacks, "passed", passed))
	if os.WriteFile(path+".new", []byte(data), 0o666) == nil {
		os.Rename(path+".new", path)
	}
}
