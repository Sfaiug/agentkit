//go:build unix

package tick

import (
	"bytes"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// checking is a tick at its merge checks, on watch.json as it stands, saying what it says into said.
func checking(t *testing.T, said io.Writer) *ticking {
	t.Helper()
	state, ok := loadState()
	if !ok {
		t.Fatal("watch.json unread")
	}
	return &ticking{state: state, log: newLog(said, io.Discard), clock: time.Now}
}

// A merge's commit is kept on its run once, the record otherwise as it stood.
func TestMergeChecksKeepTheCommitOnce(t *testing.T) {
	ak, _ := idleHome(t, `case "$*" in *mergeCommit*) echo '{"mergeCommit":{"oid":"abc"}}';; esac`)
	path := filepath.Join(ak, "runs", "fix-api", "run.json")
	put(t, path, fmt.Sprintf(`{"merged":true,"finished_at":%d,"pr":"https://github.com/acme/api/pull/1","health":{},"deployed":null,"unknown": 12345678901234567890}`, time.Now().Unix()))
	if err := checking(t, io.Discard).mergeChecks(); err != nil {
		t.Fatal(err)
	}
	kept, _ := run.ReadJSON(path)
	if kept.Str("merge_sha") != "abc" || kept.Get("unknown") != run.Number("12345678901234567890") {
		t.Fatalf("kept %s", run.Line(kept))
	}
	first := read(t, path)
	if checking(t, io.Discard).mergeChecks() != nil || read(t, path) != first {
		t.Fatal("a kept commit was written again")
	}
}

// A dry tick's merge checks decide each merge as the real ones do, its commit read off GitHub, and
// say what they would probe, record and hand back: they save no commit, run no probe and write
// nothing, not even the objects a partial clone would fetch, reading on GitHub what that lacks.  A
// merge Go does not follow, or a home keeping history, which the dry tick cannot open without
// writing beside it, hands the whole dry tick over, nothing printed.
func TestDryMergeChecksNeverSaveTheMergeCommit(t *testing.T) {
	const pr = "https://github.com/acme/api/pull/1"
	declares := base64.StdEncoding.EncodeToString([]byte("---\nhealth: true\n---\n"))
	for name, each := range map[string]struct {
		fields, watch, said, lacks string
		ago                        int64
		left, history              bool
	}{
		"undeclared": {fields: `"health": {}, "deployed": null`},
		"probe": {fields: `"health": {"command": "touch \"$HOME/probed\""}, "deployed": null, "repo": "/"`,
			said: `would check run fix-api's live product: touch "$HOME/probed"` + "\n"},
		"live": {fields: `"live_at": 1, "health": {}, "deployed": null`, said: "would record, not type: run fix-api is live: " + pr + ".\n"},
		"break": {fields: `"health": {"command": "false", "output": "down\n\nstill down"}`, ago: 4 * 3600,
			said: "would hand run fix-api back for health: false on main: health: false failed on main after this merge. " + pr + "; down; still down. Fix the target.\n"},
		// told already: the real tick lets its run's failure go
		"told break": {fields: `"health": {"command": "false", "output": "down"}`, ago: 4 * 3600,
			watch: `{"after_merge": {"github.com/acme/api": {"notified": "abc", "at": 1, "run": "fix-api"}}}`},
		"deployment":    {fields: `"health": {}, "deployed": "true"`, left: true},
		"blob lacked":   {lacks: "blob", said: "would check run fix-api's live product: true\n"},
		"commit lacked": {lacks: "commit", said: "would check run fix-api's live product: true\n"},
		"kept probe":    {fields: `"health": {"command": "touch \"$HOME/probed\""}, "deployed": null, "repo": "/"`, history: true, left: true},
		// a break waiting in watch.json alone, its run's merge no longer followed
		"kept break": {history: true, left: true, watch: `{"after_merge": {"github.com/acme/api": {"pending": {"source": "health", "sha": "abc", ` +
			`"line": "health: true failed on main", "run": "fix-api", "finished": 1, "check": "health: true", "target": "main"}}}}`},
	} {
		t.Run(name, func(t *testing.T) {
			ak, _ := idleHome(t, `case "$*" in *mergeCommit*) echo '{"mergeCommit": {"oid": "abc"}}';;
				*contents/AGENTS.md*) echo '{"encoding": "base64", "content": "`+declares+`"}';; *) `+loggedOut+`;; esac`)
			fields := each.fields
			if each.lacks != "" {
				sha, checkout := partialClone(t, filepath.Dir(ak), each.lacks == "commit")
				fields = fmt.Sprintf(`"merge_sha": %q, "repo": %q`, sha, checkout)
			}
			if fields != "" {
				put(t, filepath.Join(ak, "runs", "fix-api", "run.json"), fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": %q, %s}`,
					time.Now().Unix()-each.ago, pr, fields))
			}
			if each.watch != "" {
				put(t, filepath.Join(ak, "state", "watch.json"), each.watch)
			}
			if each.history {
				older(t, "PRAGMA user_version")
			}
			before := files(t, filepath.Dir(ak))
			want := "lock free · no tick has ended yet · watch.log 0.0 MB of 5 MB\n" + each.said +
				"gh is not logged in; PR checks skipped (To get started, please run: gh auth login)\n"
			if each.left {
				want = ""
			}
			var out bytes.Buffer
			if left := Dry(&out); (left != "") != each.left || out.String() != want {
				t.Fatalf("left %q, printing %q", left, &out)
			}
			if !reflect.DeepEqual(files(t, filepath.Dir(ak)), before) {
				t.Fatal("the dry tick changed HOME")
			}
		})
	}
}

// A history.db appearing right after a dry tick's merge checks found none, as another tick's or a
// seat's first write makes it, is never opened: nothing but it is written under HOME.
func TestDryHistoryAppearingOpensNothing(t *testing.T) {
	ak, _ := idleHome(t, `case "$*" in *mergeCommit*) echo '{"mergeCommit": {"oid": "abc"}}';; *) `+loggedOut+`;; esac`)
	put(t, filepath.Join(ak, "runs", "fix-api", "run.json"), fmt.Sprintf(
		`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/1", "health": {}, "deployed": null}`, time.Now().Unix()))
	older(t, "PRAGMA user_version")
	staged := filepath.Join(t.TempDir(), "history.db")
	if err := os.Rename(history.Path(), staged); err != nil || !run.Historyless() {
		t.Fatalf("history.db not set aside whole: %v", err)
	}
	before := files(t, filepath.Dir(ak))
	before[history.Path()] = read(t, staged)
	still := historyless
	t.Cleanup(func() { historyless = still })
	historyless = func() bool {
		historyless = still
		none := still()
		if err := os.Rename(staged, history.Path()); err != nil {
			t.Error(err)
		}
		return none
	}
	Dry(io.Discard)
	if !reflect.DeepEqual(files(t, filepath.Dir(ak)), before) {
		t.Fatal("the dry tick wrote under HOME")
	}
}

// partialClone is a clone under dir filtered of every blob, and the commit declaring `health: true`
// whose AGENTS.md it lacks, or, where whole, one it lacks altogether.
func partialClone(t *testing.T, dir string, whole bool) (sha, checkout string) {
	t.Helper()
	git := func(args ...string) string {
		t.Helper()
		out, err := exec.Command("git", args...).CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %s", args, out)
		}
		return strings.TrimSpace(string(out))
	}
	seed, origin, checkout := filepath.Join(dir, "seed"), filepath.Join(dir, "origin.git"), filepath.Join(dir, "checkout")
	commit := func(name, content string) string {
		put(t, filepath.Join(seed, name), content)
		git("-C", seed, "add", name)
		git("-C", seed, "-c", "user.name=acme", "-c", "user.email=acme@example.com", "commit", "-qm", name)
		return git("-C", seed, "rev-parse", "HEAD")
	}
	git("init", "-q", "-b", "main", seed)
	sha = commit("AGENTS.md", "---\nhealth: true\n---\n")
	git("clone", "-q", "--bare", seed, origin)
	git("--git-dir="+origin, "config", "uploadpack.allowFilter", "true")
	git("clone", "-q", "--filter=blob:none", "--no-checkout", "file://"+origin, checkout)
	if whole {
		sha = commit("README.md", "A later merge.\n")
		git("--git-dir="+origin, "fetch", "-q", seed, "HEAD:refs/heads/main")
	}
	return sha, checkout
}

// A deployment, on the run or declared at its merge's commit, and a pass its seat may be owed,
// known before or probed now, and a history whose tokens wait for Python's repair, are Python's,
// left before anything is written, an older history's tables and its probe's row included.
func TestMergeChecksLeaveWhatGoDoesNotRead(t *testing.T) {
	deployed := base64.StdEncoding.EncodeToString([]byte("---\nhealth: true\ndeployed: true\n---\n"))
	for name, each := range map[string]struct {
		fields  string
		history string // what made history.db older than Go's writes leave it
	}{
		"deployment":          {fields: `"merge_sha": "abc", "health": {}, "deployed": "true"`},
		"declared deployment": {fields: `"repo": "/srv/acme"`},
		"owed pass":           {fields: `"live_at": 1, "health": {}, "deployed": null, "launched_session": "acme"`},
		"owed probe pass":     {fields: `"merge_sha": "abc", "repo": "/", "health": {"command": "true"}, "deployed": null, "launched_session": "acme"`, history: "ALTER TABLE runs DROP COLUMN no_review"},
		"repair owed":         {fields: `"merge_sha": "abc", "repo": "/", "health": {"command": "true"}, "deployed": null`, history: "PRAGMA user_version=1"},
		"typed probe pass":    {fields: `"merge_sha": "abc", "repo": "/", "health": {"command": "true"}, "deployed": null, "live_typed": {"line": "run fix-api is live."}`},
	} {
		t.Run(name, func(t *testing.T) {
			ak, _ := idleHome(t, `case "$*" in *mergeCommit*) echo '{"mergeCommit": {"oid": "abc"}}';;
				*contents/AGENTS.md?ref=abc*) echo '{"encoding": "base64", "content": "`+deployed+`"}';; esac`)
			put(t, filepath.Join(ak, "state", "plan-acme.md"), "- [ ] The work is done · check: `false` · acme · written 2026-10-23 09:00\n")
			if each.history != "" {
				older(t, each.history)
				put(t, filepath.Join(ak, "runs", "fix-api", "round-1", "executor", "events.jsonl"), "{}\n")
			}
			schema := tables(t)
			path := filepath.Join(ak, "runs", "fix-api", "run.json")
			before := fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/1", %s}`, time.Now().Unix(), each.fields)
			put(t, path, before)
			if err := checking(t, io.Discard).mergeChecks(); !errors.Is(err, errLeft) || read(t, path) != before {
				t.Fatalf("%v: %s", err, read(t, path))
			}
			if tables(t) != schema {
				t.Fatal("history.db was written")
			}
		})
	}
}

// older is history.db with run fix-api's row, then changed by statement as an older ak left it.
func older(t *testing.T, statement string) {
	t.Helper()
	history.Start(run.Fields("run_id", "fix-api"), nil)
	db, err := sqlite3.Open(history.Path())
	if err == nil {
		err = db.Exec(statement)
		db.Close()
	}
	if err != nil {
		t.Fatal(err)
	}
}

// tables is history.db's tables, their rows counted, and its version: "" where none stands.
func tables(t *testing.T) string {
	t.Helper()
	db := history.Look()
	defer db.Close()
	said := fmt.Sprint(db.Select("PRAGMA user_version"))
	for _, table := range db.Select("SELECT name, sql FROM sqlite_master ORDER BY name") {
		said += fmt.Sprint(table, db.Select("SELECT COUNT(*) FROM "+table.Text("name")))
	}
	return said
}

// A seat that comes to owe a pass while its probe runs has the pass recorded, as Python records it,
// and told by nobody: the next tick, reading it owed before it writes, hands its telling over.
func TestMergeChecksRecordAPassOwedSinceItsProbe(t *testing.T) {
	ak, _ := idleHome(t, "")
	home := filepath.Dir(ak)
	put(t, filepath.Join(home, "plan"), "- [ ] The work is done · check: `false` · acme · written 2026-10-23 09:00\n")
	path := filepath.Join(ak, "runs", "fix-api", "run.json")
	put(t, path, fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/1", "merge_sha": "abc", "repo": "/", `+
		`"health": {"command": "cp \"$HOME/plan\" \"$HOME/.agentkit/state/plan-acme.md\""}, "deployed": null, "launched_session": "acme"}`, time.Now().Unix()))
	older(t, "ALTER TABLE runs DROP COLUMN no_review")
	if err := checking(t, io.Discard).mergeChecks(); err != nil {
		t.Fatal(err)
	}
	kept, _ := run.ReadJSON(path)
	db := history.Look()
	probes := db.Select("SELECT exit FROM checks WHERE run_id='fix-api' AND kind='health'")
	db.Close()
	if !kept.Truthy("live_at") || kept.Has("live_notified") || len(probes) != 1 || probes[0]["exit"] != int64(0) {
		t.Fatalf("%v: %s", probes, run.Line(kept))
	}
	before, schema := read(t, path), tables(t)
	if err := checking(t, io.Discard).mergeChecks(); !errors.Is(err, errLeft) || read(t, path) != before || tables(t) != schema {
		t.Fatalf("%v: %s", err, read(t, path))
	}
}

// What a merge's commit declares is read on GitHub where its checkout lacks the commit, and kept;
// its `health:` passing there, given the commit, makes the run live, recorded and never typed.
func TestMergeHealthFoundOnGitHubGoesLive(t *testing.T) {
	agents := base64.StdEncoding.EncodeToString([]byte("---\nhealth: test \"$AK_MERGE_SHA\" = abc\n---\n"))
	ak, _ := idleHome(t, `case "$*" in *contents/AGENTS.md?ref=abc*) echo '{"encoding": "base64", "content": "`+agents+`"}';; esac`)
	path := filepath.Join(ak, "runs", "fix-api", "run.json")
	put(t, path, fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/1", "merge_sha": "abc", "repo": %q}`,
		time.Now().Unix(), t.TempDir()))
	var said bytes.Buffer
	if err := checking(t, &said).mergeChecks(); err != nil {
		t.Fatal(err)
	}
	record, _ := run.ReadJSON(path)
	if record.Has("health") || !record.Has("deployed") || record.Get("deployed") != nil || !record.Truthy("live_at") ||
		!record.Truthy("live_notified") || record.Str("live_note") != "routine ending: recorded, not typed" {
		t.Fatalf("recorded %s", run.Line(record))
	}
	if said.String() != "run fix-api is live: https://github.com/acme/api/pull/1. Recorded, not typed\n" {
		t.Errorf("said %q", said.String())
	}
}

// A live notice whose mark cannot be written is not said to be: the next tick tells it again.
func TestALiveNoticeNotWrittenIsNotSaid(t *testing.T) {
	ak, _ := idleHome(t, answers)
	dir := filepath.Join(ak, "runs", "fix-api")
	put(t, filepath.Join(dir, "run.json"), fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/1", "merge_sha": "abc", "live_at": 1, "health": {}, "deployed": null}`,
		time.Now().Unix()))
	if err := os.Mkdir(filepath.Join(dir, "delivery.tmp"), 0o700); err != nil {
		t.Fatal(err)
	}
	var said bytes.Buffer
	if err := checking(t, &said).mergeChecks(); err != nil {
		t.Fatal(err)
	}
	if record, _ := run.Read(dir); record.Truthy("live_notified") || strings.Contains(said.String(), "Recorded") {
		t.Fatalf("said %q of %s", said.String(), run.Line(record))
	}
}

// A break found past its window is kept until a seat takes it, its run no longer followed and its
// result opening on the NOT LIVE decision; a later merge going green ends it.  One watch.json
// cannot keep yet waits a tick, its run's failure in place.
func TestABreakIsKeptUntilToldOrGreen(t *testing.T) {
	ak, _ := idleHome(t, answers)
	broke := filepath.Join(ak, "runs", "broke")
	put(t, filepath.Join(broke, "run.json"), fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/2",
		"merge_sha": "b2", "launched_session": "acme", "health": {"command": "false", "output": "down\n\nstill down"}}`, time.Now().Unix()-4*3600))
	unsaved := filepath.Join(ak, "state", "watch.tmp")
	if err := os.MkdirAll(unsaved, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := checking(t, io.Discard).mergeChecks(); err != nil {
		t.Fatal(err)
	}
	if record, _ := run.Read(broke); !record.Has("health") {
		t.Fatal("a break nothing keeps lost its run's failure")
	}
	if _, err := os.Stat(filepath.Join(broke, "result.md")); err == nil {
		t.Fatal("a break nothing keeps was told")
	}
	if err := os.Remove(unsaved); err != nil {
		t.Fatal(err)
	}
	var said bytes.Buffer
	if err := checking(t, &said).mergeChecks(); err != nil {
		t.Fatal(err)
	}
	told := "health: false failed on main after this merge. https://github.com/acme/api/pull/2; down; still down. Fix the target."
	pending := watched(t, ak)["after_merge"].(map[string]any)["github.com/acme/api"].(map[string]any)["pending"].(map[string]any)
	if pending["line"] != told || pending["session"] != "acme" || pending["run"] != "broke" || pending["sha"] != "b2" {
		t.Fatalf("kept %v", pending)
	}
	if record, _ := run.Read(broke); record.Has("health") {
		t.Error("an expired probe is still followed")
	}
	if result := read(t, filepath.Join(broke, "result.md")); !strings.HasPrefix(result, "# NOT LIVE (0 of 0) — broke\nWhy: "+told) ||
		!strings.HasSuffix(result, "\n## Seat notice\n\n"+told+"\n") {
		t.Errorf("result.md holds %s", result)
	}
	if said.String() != "run broke's after-merge notice waits for a live seat at its prompt\n" {
		t.Errorf("said %q", said.String())
	}
	put(t, filepath.Join(ak, "runs", "green", "run.json"), fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/3",
		"merge_sha": "g3", "live_at": 1, "live_notified": 1, "health": {}, "deployed": null}`, time.Now().Unix()-60))
	said.Reset()
	tick := checking(t, &said)
	if err := tick.mergeChecks(); err != nil || tick.state.Dict("after_merge").Has("github.com/acme/api") {
		t.Fatalf("%v: %s", err, run.Line(tick.state))
	}
	if said.String() != "run broke's after-merge notice is over: github.com/acme/api went green\n" {
		t.Errorf("said %q", said.String())
	}
}
