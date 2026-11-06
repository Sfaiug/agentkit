package history

import (
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"agentkit/internal/run"
)

// record is a run's record as its JSON text has it.
func record(t *testing.T, text string) *run.Object {
	t.Helper()
	value, err := run.Decode([]byte(text))
	if err != nil {
		t.Fatal(err)
	}
	return value.(*run.Object)
}

// row is the run's row as SQLite holds each value, its type beside it.
func row(t *testing.T, id string, columns ...string) Row {
	t.Helper()
	db, err := Open()
	if err != nil || db == nil {
		t.Fatalf("got (%v, %v)", db, err)
	}
	defer db.Close()
	var selected []string
	for _, column := range columns {
		selected = append(selected, column, "typeof("+column+") AS "+column+"_type")
	}
	rows, err := db.rows("SELECT "+strings.Join(selected, ", ")+" FROM runs WHERE run_id=?", id)
	if err != nil || len(rows) != 1 {
		t.Fatalf("got (%v, %v)", rows, err)
	}
	return rows[0]
}

// said is a log, and the lines said on it.
func said() (func(string), *[]string) {
	lines := &[]string{}
	return func(line string) { *lines = append(*lines, line) }, lines
}

// A run's row lives as Python's does: the launch makes the database and its row running, the loop
// keeps its workers and rounds, the ending closes it with how long it took and who reviewed whom,
// and a resume makes it running again, the first start and orchestrator kept.
func TestARunsRowLivesAsPythonsDoes(t *testing.T) {
	home(t)
	config := "[models.opus]\nharness='claude'\nmodel='opus'\neffort='high'\nprovider='anthropic'\n" +
		"[models.astra]\nharness='codex'\nmodel='astra'\neffort='high'\nprovider='openai'\n" +
		"[providers.anthropic]\nmode='subscription'\n[providers.openai]\nmode='subscription'\n"
	if err := os.WriteFile(filepath.Join(filepath.Dir(Path()), "config.toml"), []byte(config), 0o600); err != nil {
		t.Fatal(err)
	}
	log, lines := said()
	launched := record(t, `{"run_id": "20261105-1200-fix-api", "state": "queued", "started_at": 1000.5,
		"launched_session": null, "review_pr": null, "notify_sink": "", "policy": {"review_rounds": 0}}`)
	Start(launched, log)
	got := row(t, "20261105-1200-fix-api", "final_state", "started_at", "repo", "rounds_used", "change", "kind",
		"no_review", "landing_breaks", "broke_after_merge", "executor_seconds")
	want := Row{"final_state": "running", "final_state_type": "text", "started_at": 1000.5, "started_at_type": "real",
		"repo": nil, "repo_type": "null", "rounds_used": int64(0), "rounds_used_type": "integer",
		"change": "20261105-1200-fix-api", "change_type": "text", "kind": "task", "kind_type": "text",
		"no_review": int64(1), "no_review_type": "integer", "landing_breaks": int64(0), "landing_breaks_type": "integer",
		"broke_after_merge": "", "broke_after_merge_type": "text", "executor_seconds": 0.0, "executor_seconds_type": "real"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("launched:\n got %v\nwant %v", got, want)
	}

	started := record(t, `{"run_id": "20261105-1200-fix-api", "state": "running", "started_at": 1010.0,
		"repo": "/home/someone/code/acme", "task_words": 40, "task_points": 2, "task_checks": 1}`)
	Start(started, log)
	picked := started.Copy()
	run.SetAll(picked, "executor", "opus", "reviewer", "astra", "executor_effort", "high")
	Keep(started, picked, log)
	got = row(t, "20261105-1200-fix-api", "repo", "started_at", "executor", "executor_effort", "task_words")
	if got["repo"] != "acme" || got["started_at"] != 1000.5 || got["executor"] != "opus" ||
		got["executor_effort"] != "high" || got["task_words_type"] != "integer" {
		t.Fatalf("started: %v", got)
	}

	ended := picked.Copy()
	run.SetAll(ended, "state", "pass", "verdict", "PASS", "finished_at", 1100.25, "started_at", 1010.0,
		"round_summaries", []any{run.NewObject()}, "review", run.Fields("reviewer", "astra"))
	Finish(ended, log)
	got = row(t, "20261105-1200-fix-api", "final_state", "verdict", "rounds_used", "total_seconds", "review_pair", "started_at")
	if got["final_state"] != "pass" || got["verdict"] != "PASS" || got["rounds_used"] != int64(1) ||
		got["total_seconds"] != 99.75 || got["review_pair"] != "other provider" || got["started_at"] != 1000.5 {
		t.Fatalf("ended: %v", got)
	}

	Start(ended, log)
	got = row(t, "20261105-1200-fix-api", "final_state", "verdict", "finished_at", "total_seconds", "started_at")
	if got["final_state"] != "running" || got["verdict"] != nil || got["finished_at"] != nil ||
		got["total_seconds"] != nil || got["started_at"] != 1000.5 {
		t.Fatalf("resumed: %v", got)
	}
	if len(*lines) > 0 {
		t.Fatalf("said %q", *lines)
	}
}

// A suite's run, under its notify sink, has no row and makes no database; a save that moves
// nothing the row keeps writes nothing.
func TestWhatWritesNoRowMakesNoDatabase(t *testing.T) {
	home(t)
	log, _ := said()
	suite := record(t, `{"run_id": "20261105-1200-fix-api", "state": "error", "notify_sink": "dry-run"}`)
	Start(suite, log)
	Finish(suite, log)
	owner := record(t, `{"run_id": "20261105-1200-fix-api", "state": "running", "executor": "opus"}`)
	moved := owner.Copy()
	moved.Set("step", "executor")
	Keep(owner, moved, log)
	if _, err := os.Lstat(Path()); err == nil {
		t.Fatal("history.db was made")
	}
}

// A run in a suite's repository has no row: the one its launch wrote before the repository was
// known goes.
func TestASuitesRepositoryForgetsItsRow(t *testing.T) {
	home(t)
	log, _ := said()
	Start(record(t, `{"run_id": "20261105-1200-fix-api", "state": "queued"}`), log)
	Start(record(t, `{"run_id": "20261105-1200-fix-api", "state": "running", "repo": "/tmp/agentkit-smoke"}`), log)
	db, err := Open()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if rows := query(t, db, "SELECT run_id FROM runs"); len(rows) > 0 {
		t.Fatalf("kept %v", rows)
	}
}

// A write that fails is said where the run's log says it, and the run goes on.
func TestAFailedWriteIsSaid(t *testing.T) {
	home(t)
	if err := os.Mkdir(Path(), 0o700); err != nil {
		t.Fatal(err)
	}
	log, lines := said()
	Start(record(t, `{"run_id": "20261105-1200-fix-api", "state": "queued"}`), log)
	if len(*lines) != 1 || !strings.HasPrefix((*lines)[0], "WARN history: ") {
		t.Fatalf("said %q", *lines)
	}
}

// A run goes on in Go unless history.db holds a step of it, which only Python records: one Python
// carried, tokens that wait for Python's repair, or a database SQLite cannot read; and a history
// holds Python's runs where it holds a step of any.  One that is no file holds none.
func TestARunWithStepsIsPythons(t *testing.T) {
	home(t)
	if Carried("20261105-1200-fix-api") || Carried("") {
		t.Fatal("no database, yet carried")
	}
	log, _ := said()
	Start(record(t, `{"run_id": "20261105-1200-fix-api", "state": "queued"}`), log)
	if Carried("20261105-1200-fix-api") || Carried("") {
		t.Fatal("Go's row alone, yet carried")
	}
	write(t, "INSERT INTO phases VALUES ('20261105-1200-fix-api', 'executor', 1.0, 2.0, NULL)")
	if !Carried("20261105-1200-fix-api") || Carried("20261105-1300-fix-ui") || !Carried("") {
		t.Fatal("a step not read as Python's")
	}
	write(t, "PRAGMA user_version=1")
	put(t, filepath.Join(run.Runs(), "20261105-1200-fix-api", "round-1", "executor-opus", "events.jsonl"), "")
	if !Carried("20261105-1300-fix-ui") {
		t.Fatal("tokens owed Python's repair left to Go")
	}
	os.WriteFile(Path(), []byte("not a database"), 0o600)
	if !Carried("20261105-1300-fix-ui") {
		t.Fatal("an unreadable database left to Go")
	}
	os.Remove(Path())
	os.Mkdir(Path(), 0o700)
	if Carried("") {
		t.Fatal("a directory read as Python's history")
	}
}

// A review's row is a pull request's from its receipt, and a seat's own once the launch knows
// whose it reads, as Python's preflight says it before anything refuses the launch.
func TestAReviewKnownAsTheSeatsOwnReadsAsOne(t *testing.T) {
	home(t)
	log, lines := said()
	launched := record(t, `{"run_id": "20261105-1200-review-pr-acme-7", "state": "queued", "review_pr": "https://github.com/acme/widgets/pull/7"}`)
	Start(launched, log)
	if kind := row(t, "20261105-1200-review-pr-acme-7", "kind")["kind"]; kind != "PR" {
		t.Fatalf("at its receipt: %v", kind)
	}
	launched.Set("own_pr", true)
	Classified(launched, log)
	if kind := row(t, "20261105-1200-review-pr-acme-7", "kind")["kind"]; kind != "seat PR" || len(*lines) > 0 {
		t.Fatalf("once known: %v, said %q", kind, *lines)
	}
}

// The ending keeps what git measures of the run, as Python's history_finish reads it: the files
// it changed, the lines a merged change landed, generated ones aside, and the AGENTS.md handed
// to its workers; in its repository at the tip it recorded once its checkout is gone.
func TestTheEndingKeepsWhatGitMeasures(t *testing.T) {
	home(t)
	repo := t.TempDir()
	git := func(args ...string) string {
		out, err := exec.Command("git", append([]string{"-C", repo, "-c", "user.name=acme", "-c", "user.email=acme@example.com"}, args...)...).Output()
		if err != nil {
			t.Fatal(args, err)
		}
		return strings.TrimSpace(string(out))
	}
	commit := func(files map[string]string) string {
		for name, text := range files {
			if err := os.WriteFile(filepath.Join(repo, name), []byte(text), 0o600); err != nil {
				t.Fatal(err)
			}
		}
		git("add", "-A")
		git("commit", "-qm", "change")
		return git("rev-parse", "HEAD")
	}
	git("init", "-q")
	base := commit(map[string]string{"AGENTS.md": "# acme\n", ".gitattributes": "gen.txt linguist-generated\n"})
	tip := commit(map[string]string{"retry.txt": "one\ntwo\n", "gen.txt": "a\nb\nc\n"})
	log, lines := said()
	ended := record(t, `{"run_id": "20261105-1200-fix-api", "state": "pass", "merged": true}`)
	run.SetAll(ended, "repo", repo, "worktree", repo, "base_sha", base, "target_sha", base)
	Start(ended, log)
	Finish(ended, log)
	got := row(t, "20261105-1200-fix-api", "task_files", "changed_lines", "rules_bytes")
	if got["task_files"] != `["gen.txt", "retry.txt"]` || got["changed_lines"] != int64(2) || got["rules_bytes"] != int64(7) {
		t.Fatalf("in its checkout: %v", got)
	}
	gone := ended.Copy()
	run.SetAll(gone, "worktree", filepath.Join(repo, "gone"), "delivery_sha", tip, "finished_at", 2000.0)
	git("checkout", "-q", base)
	Finish(gone, log)
	if again := row(t, "20261105-1200-fix-api", "task_files", "changed_lines", "rules_bytes"); !reflect.DeepEqual(again, got) {
		t.Fatalf("from its repository: %v", again)
	}
	if len(*lines) > 0 {
		t.Fatalf("said %q", *lines)
	}
}
