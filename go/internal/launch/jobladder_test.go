//go:build linux

package launch

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"agentkit/internal/job"
	"agentkit/internal/run"
)

// A job's task that does not deliver settles with its own line.  A run stopped is stopped, one
// blocked BLOCKED with its error; a FAIL its reviews failed, one short of its round budget and one
// at it with no other worker to rerun it on fail with their findings or error, as an exhausted run
// no budget fixes fails with its error; a task its file now refuses at its start is BLOCKED, the
// refusal its findings, and one that cannot start fails, one preflight refuses with its run ended
// in error, one whose run cannot be made and one executors are off for.  A step Python's ladder
// takes first, a wait, a PASS still to deliver or the rerun, leaves the task as it was.  Once
// every task settled the job logs each one's findings and that it needs you, and exits 1; a job
// whose only undelivered task was stopped needs nobody and is done, and exits 1 too.
func TestAJobsUndeliveredTasksEndItNeedingYou(t *testing.T) {
	home, worktree := jobHome(t), t.TempDir()
	one, both := []string{"opus"}, []string{"opus", "astra"}
	atBudget := `"state": "fail", "rounds": 3, "round_summaries": [{}, {}, {}], "worktree": "` + worktree + `", "executor": "opus"`
	j := createdJob(t, "stopped.md", "blocked.md", "reviewed.md", "early.md", "alone.md", "tool.md", "refused.md", "from.md", "unmade.md", "off.md")
	tasks := j.receipt.List("tasks")
	for _, each := range []struct {
		task    int
		record  string
		workers []string
		settles bool
	}{
		{0, `{"state": "stopped"}`, one, true},
		{1, `{"state": "blocked", "error": "the task asks for\n  a secret"}`, one, true},
		{2, `{` + atBudget + `, "findings": "api.go:12 - the handler drops the error", "review_records": [{"kind": "finding"}, {"kind": "done"}]}`, both, true},
		{3, `{"state": "fail", "rounds": 3, "round_summaries": [{}], "worktree": "` + worktree + `", "error": "the check failed"}`, both, true},
		{4, `{"state": "waiting", "error": "the target moved"}`, one, false},
		{4, `{"state": "waiting_login", "error": "a harness login expired"}`, one, false},
		{4, `{"state": "interrupted"}`, one, false},
		{4, `{"state": "exhausted", "error": "every worker has a gate meter at 100% used"}`, one, false},
		{4, `{"state": "exhausted", "error": "the review was invalidated", "review_pending": {"round": 3}}`, both, false},
		{4, `{"state": "pass", "verdict": "PASS", "merge_failed": true}`, one, false},
		{4, `{` + atBudget + `}`, both, false},
		{4, `{` + atBudget + `}`, one, true},
		{5, `{"state": "exhausted", "error": "git did not answer"}`, one, true},
	} {
		task := tasks[each.task].(*run.Object)
		run.SetAll(task, "state", "running", "run_id", "run-"+task.Str("name"))
		record, err := run.Decode([]byte(each.record))
		if err != nil {
			t.Fatal(err)
		}
		settled, err := j.settle(ending{task, filepath.Join(run.Runs(), "run-"+task.Str("name")), record.(*run.Object), each.workers})
		if err != nil || settled != each.settles || !settled && (task.Str("state") != "running" || task.Has("verdict_line")) {
			t.Fatalf("%s settled %v (%v) on %s: %v", task.Str("name"), settled, err, each.record, task)
		}
	}
	ended := make(chan ending)
	refused := tasks[6].(*run.Object)
	write(t, refused.Str("task_file"), "---\nrepo: none\nafter: fix-api.md\n---\n# Refused\n\n## Done when\n```bash\ntrue\n```\n")
	if begun, err := j.begin(refused, ended); begun || err != nil {
		t.Fatalf("began %v: %v", begun, err)
	}
	write(t, tasks[7].(*run.Object).Str("task_file"), "---\nrepo: none\nfrom: previous\n---\n# from\n\n## Done when\n```bash\ntrue\n```\n")
	work := filepath.Join(home, ".agentkit", "work")
	for i, broken := range []func(){func() {}, func() { os.RemoveAll(work); write(t, work, "") },
		func() { write(t, filepath.Join(home, ".agentkit", "config.toml"), "executor_lines = 0\n"+jobConfig) }} {
		broken()
		if begun, err := j.begin(tasks[7+i].(*run.Object), ended); begun || err != nil {
			t.Fatalf("began %v: %v", begun, err)
		}
	}
	made, _ := filepath.Glob(filepath.Join(run.Runs(), "*-from"))
	if len(made) != 1 {
		t.Fatalf("from.md made the runs %v", made)
	}
	preflight := filepath.Join(made[0], "task.md") + ": from: needs a repository; a scratch run has no branch to start from"
	if record, _ := run.Read(made[0]); record == nil || record.Str("state") != "error" || record.Str("error") != preflight {
		t.Fatalf("the refused run ended %v", record)
	}
	if code, err := j.carry(); code != 1 || err != nil {
		t.Fatalf("the job ended %d: %v", code, err)
	}

	after := "`after:` is gone: tasks launched together are independent pieces; build work that waits on another piece in your session, in order"
	receipt, _ := job.Read(j.dir)
	for i, want := range [][]any{
		{"stopped", "stopped.md: stopped"},
		{"blocked", "blocked.md: BLOCKED: the task asks for a secret", "the task asks for\n  a secret"},
		{"failed", "reviewed.md: FAIL after 3 rounds: needs you", "api.go:12 - the handler drops the error"},
		{"failed", "early.md: FAIL after 1 rounds: needs you", "the check failed"},
		{"failed", "alone.md: FAIL after 3 rounds: needs you", ""},
		{"failed", "tool.md: FAIL: needs you (git did not answer)", "git did not answer"},
		{"blocked", "refused.md: BLOCKED: " + after, after},
		{"failed", "from.md: FAIL: needs you (" + preflight + ")"},
		{"failed", "unmade.md: FAIL: needs you (mkdir " + work + ": file exists)"},
		{"failed", "off.md: FAIL: needs you (executor_lines = 0: Executors are off; the orchestrator builds every change itself.)"},
	} {
		task := receipt.List("tasks")[i].(*run.Object)
		got := []any{task.Get("state"), task.Get("verdict_line")}
		if task.Has("findings") {
			got = append(got, task.Get("findings"))
		}
		if !run.Equal(got, want) || !task.Truthy("finished_at") || !strings.Contains(logged(t, j), "\n"+want[1].(string)+"\n") {
			t.Fatalf("task %d settled %v, not %v", i, got, want)
		}
	}
	if said := logged(t, j); !receipt.Truthy("finished_at") || !strings.HasSuffix(said, "\n"+strings.Join([]string{
		"blocked.md findings:", "the task asks for", "  a secret",
		"reviewed.md findings:", "api.go:12 - the handler drops the error",
		"early.md findings:", "the check failed",
		"tool.md findings:", "git did not answer",
		"refused.md findings:", after,
		"job " + j.id() + ": Needs you",
		"no seat launched this job, so nothing is sent; the result is here and in `ak run status`", ""}, "\n")) {
		t.Fatalf("the job logged %s", said)
	}

	done := createdJob(t, "fix-api.md", "fix-db.md")
	for i, record := range []string{`{"state": "pass", "merged": true, "round_summaries": [{}]}`, `{"state": "stopped"}`} {
		task := done.receipt.List("tasks")[i].(*run.Object)
		value, _ := run.Decode([]byte(record))
		if settled, err := done.settle(ending{task, filepath.Join(run.Runs(), "run-"+task.Str("name")), value.(*run.Object), one}); !settled || err != nil {
			t.Fatalf("%s settled %v: %v", task.Str("name"), settled, err)
		}
	}
	if code, err := done.carry(); code != 1 || err != nil || !strings.HasSuffix(logged(t, done), "\nfix-api.md: PASS, merged after 1 rounds\n"+
		"fix-db.md exit 1: run-fix-db.md stopped None not merged\nfix-db.md: stopped\njob "+done.id()+": Done\n"+
		"no seat launched this job, so nothing is sent; the result is here and in `ak run status`\n") {
		t.Fatalf("the job ended %d (%v), logging %s", code, err, logged(t, done))
	}
}

// A stop that lands as preflight's refusal ends a task's run keeps the run's word, which refuse
// leaves standing: the task is stopped, not failed.
func TestAStopAsPreflightRefusesKeepsItsWord(t *testing.T) {
	jobHome(t)
	j := createdJob(t, "fix-api.md")
	path := j.receipt.List("tasks")[0].(*run.Object).Str("task_file")
	write(t, path, "---\nrepo: none\nfrom: previous\n---\n# Fix api\n\n## Done when\n```bash\ntrue\n```\n")
	l, _, _, err := j.task(path)
	if l == nil || l.reason == "" {
		t.Fatalf("preflight did not refuse it: %v", err)
	}
	// the stop lands as the refusal's warning is said, past every look make took
	l.warning = "the base moved"
	j.out = stopAt{l.dir, l.warning}
	if err := j.ready(l); !errors.Is(err, ErrStopped) {
		t.Fatalf("ready said %v", err)
	}
	if record, _ := run.Read(l.dir); record == nil || record.Str("state") != "stopped" {
		t.Fatalf("the run ended %v", record)
	}
}

// stopAt stops the run at dir once a line it is told says that.
type stopAt struct{ dir, that string }

func (s stopAt) Write(p []byte) (int, error) {
	if strings.Contains(string(p), s.that) {
		run.Change(s.dir, func(record *run.Object) error { record.Set("state", "stopped"); return nil })
	}
	return len(p), nil
}

const jobConfig = "[defaults]\nworkers = ['opus']\n[models.opus]\nharness = 'claude'\nmodel = 'opus'\neffort = 'high'\nprovider = 'anthropic'\n" +
	"[providers.anthropic]\nmode = 'subscription'\n"

// jobHome is a home a job launched from no seat starts its tasks in, its one worker's harness
// installed and its login ready, whatever the host has installed.
func jobHome(t *testing.T) string {
	home, adapters := t.TempDir(), t.TempDir()
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "XDG_CACHE_HOME": "", "XDG_RUNTIME_DIR": t.TempDir(),
		"AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_DEPTH": "", "AK_PARENT_RUN": "", "AK_MAX_RUNS": "0",
		"AGENTKIT_ADAPTER_DIR": adapters, "AGENTKIT_JOB_DIR": "", "PATH": adapters + string(os.PathListSeparator) + os.Getenv("PATH")} {
		t.Setenv(key, value)
	}
	write(t, filepath.Join(home, ".agentkit", "config.toml"), jobConfig)
	write(t, filepath.Join(adapters, "claude.sh"), "#!/bin/sh\nprintf 'ready\\n'\n")
	write(t, filepath.Join(adapters, "claude"), "#!/bin/sh\n")
	return home
}

// createdJob is a job's receipt of scratch tasks by those names, each queued, as Job creates it.
func createdJob(t *testing.T, names ...string) *jobRun {
	folder := t.TempDir()
	var tasks []*launching
	for _, name := range names {
		path := filepath.Join(folder, name)
		write(t, path, "---\nrepo: none\n---\n# "+strings.TrimSuffix(name, ".md")+"\n\n## Done when\n```bash\ntrue\n```\n")
		tasks = append(tasks, &launching{path: path, named: strings.TrimSuffix(name, ".md")})
	}
	j := &jobRun{values: map[string]string{}, flags: map[string]bool{}, out: &bytes.Buffer{}}
	if err := j.create(tasks, nil); err != nil {
		t.Fatal(err)
	}
	return j
}

// logged is the job's log, each line's time aside.
func logged(t *testing.T, j *jobRun) string {
	data, err := os.ReadFile(filepath.Join(j.dir, "log.txt"))
	if err != nil {
		t.Fatal(err)
	}
	return regexp.MustCompile(`(?m)^\d\d:\d\d:\d\d `).ReplaceAllString(string(data), "")
}
