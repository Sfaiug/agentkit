//go:build unix

package tick

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"syscall"
	"testing"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

const (
	user    = `echo '{"login": "acme"}'`
	answers = `case "$*" in "api user") ` + user + ` ;; *) echo '{"items": []}' ;; esac`
)

// idleHome is a home with nothing to act on, the audit off and no collection due, whose gh runs script, and where it
// keeps ak's own files.
func idleHome(t *testing.T, script string) (ak string, gh func(string)) {
	t.Helper()
	home, bin := t.TempDir(), t.TempDir()
	for key, value := range map[string]string{
		"HOME": home, "USERPROFILE": home, "TMUX_TMPDIR": t.TempDir(), "AGENTKIT_TMUX_SOCKET": "tick-test",
		"AGENTKIT_SESSION": "", "AGENTKIT_ADAPTER_DIR": "", "XDG_RUNTIME_DIR": t.TempDir(), "XDG_CONFIG_HOME": "",
		"AK_RUN_ROLE":    "",
		"AK_NOTIFY_SINK": "dry-run",
		"PATH":           bin + string(os.PathListSeparator) + os.Getenv("PATH"),
	} {
		t.Setenv(key, value)
	}
	ak = filepath.Join(home, ".agentkit")
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n")
	// a collection on record today: a due one would start this test binary as its collector
	put(t, filepath.Join(ak, "state", "gc.json"), fmt.Sprintf(`{"started_at": %d}`, time.Now().Unix()))
	gh = func(script string) {
		t.Helper()
		put(t, filepath.Join(bin, "gh"), "#!/bin/sh\n"+script+"\n")
		if err := os.Chmod(filepath.Join(bin, "gh"), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	gh(script)
	return ak, gh
}

// carries is whether a tick was carried out whole: Go did not leave it to Python, and it saved
// watch.json.
func carries(out, errOut io.Writer) bool {
	carried, failed := Carry(out, errOut)
	return carried && !failed
}

func put(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
}

// watched is the watch.json a tick left, as JSON.
func watched(t *testing.T, ak string) map[string]any {
	t.Helper()
	var state map[string]any
	if err := json.Unmarshal([]byte(read(t, filepath.Join(ak, "state", "watch.json"))), &state); err != nil {
		t.Fatal(err)
	}
	return state
}

// files is every path under root with what it holds.
func files(t *testing.T, root string) map[string]string {
	t.Helper()
	found := map[string]string{}
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		found[path] = ""
		if !entry.IsDir() {
			found[path] = read(t, path)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return found
}

// A tick on such a home says nothing, keeps what it does not know and records itself.
func TestATickKeepsWhatItDoesNotKnowAndRecordsItself(t *testing.T) {
	ak, _ := idleHome(t, answers)
	put(t, filepath.Join(ak, "state", "watch.json"), `{"mine": {"big": 12345678901234567890, "é": 1e3}, "gh_out": {"at": 1.0}, "boot_id": "another"}`)
	var out bytes.Buffer
	if !carries(&out, io.Discard) || out.Len() != 0 {
		t.Fatalf("printed %q", out.String())
	}
	text := read(t, filepath.Join(ak, "state", "watch.json"))
	if !strings.HasPrefix(text, "{\n  \"mine\": {\n    \"big\": 12345678901234567890,\n    \"\\u00e9\": 1000.0\n  },\n") || !strings.HasSuffix(text, "}\n") {
		t.Errorf("watch.json holds %s", text)
	}
	state := watched(t, ak)
	if _, ok := state["gh_out"]; ok {
		t.Error("gh answering left gh_out")
	}
	if state["boot_id"] == "another" {
		t.Error("the boot went unrecorded")
	}
	tick, _ := state["tick"].(map[string]any)
	slowest, _ := tick["slowest"].(map[string]any)
	if tick["started_at"] == nil || tick["ended_at"] == nil || slowest["pass"] == "" || slowest["seconds"] == nil {
		t.Errorf("tick is %v", tick)
	}
	if got := read(t, filepath.Join(ak, "state", "watch.tick.lock")); got == "" || got[len(got)-1] != '\n' {
		t.Errorf("the lock holds %q", got)
	}
}

// A logout is written down, an outage leaves that record, and each is its one line.
func TestALogoutIsRecordedAndAnOutageLeavesIt(t *testing.T) {
	ak, gh := idleHome(t, "echo 'To get started, please run:  gh auth login' >&2; exit 4")
	var out bytes.Buffer
	if !carries(&out, io.Discard) || out.String() != "gh is not logged in; PR checks skipped (To get started, please run: gh auth login)\n" {
		t.Fatalf("printed %q", out.String())
	}
	at := watched(t, ak)["gh_out"]
	if at == nil {
		t.Fatal("no logout on record")
	}
	gh("echo offline >&2; exit 1")
	out.Reset()
	if !carries(&out, io.Discard) || out.String() != "WARN GitHub is unavailable; PR checks skipped (offline)\n" {
		t.Fatalf("printed %q", out.String())
	}
	if got := watched(t, ak)["gh_out"]; !reflect.DeepEqual(got, at) {
		t.Errorf("gh_out went from %v to %v", at, got)
	}
}

// endedThere is a tick that left the rest to Python: what the rows before it said all it printed,
// no tick on record as ended, and the lock free.
func endedThere(t *testing.T, ak, said string) {
	t.Helper()
	var out, errOut bytes.Buffer
	if carries(&out, &errOut) || out.String() != said || errOut.Len() != 0 {
		t.Fatalf("carried it, printing %q %q", out.String(), errOut.String())
	}
	if text, err := os.ReadFile(filepath.Join(ak, "state", "watch.json")); err == nil && strings.Contains(string(text), `"tick"`) {
		t.Errorf("the tick was recorded as ended: %s", text)
	}
	if lock.Held(lockPath()) {
		t.Error("the lock is still held")
	}
}

// What a row finds to act on ends the tick there, and leaves it as it was.
func TestAnythingToActOnEndsTheTickThere(t *testing.T) {
	for path, content := range map[string]string{
		"runs/fix-api/run.json":            `{"state":"waiting_login"}`,
		"jobs/fix-api/job.json":            `{"tasks": [{"name": "fix-api.md", "state": "queued"}]}`,
		"state/session-acme.json":          "{}",
		"state/google-cloud-need":          "4096\n",
		"state/notification-outbox/a.json": "{}",
		"state/watch.json#stalls":          `{"stalls": {"acme": {"since": 1, "nudged_at": 2}}}`,
		"runs/fix-api/run.json#deployment": fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/1", "health": {}, "deployed": "true"}`,
			time.Now().Unix()),
		"state/watch.json#auth":      `{"auth_out": {"claude": {"ok": false}}}`,
		"state/watch.json#surrogate": `{"mine": "\ud800"}`,
		"config.toml":                "[audit]\non = true\n",
		"config.toml#absent":         "",
		"config.toml#renting":        "[audit]\non = false\n[google_cloud]\nactive = true\n",
	} {
		t.Run(path, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			path, _, _ := strings.Cut(path, "#")
			put(t, filepath.Join(ak, path), content)
			endedThere(t, ak, "")
			if got := read(t, filepath.Join(ak, path)); got != content {
				t.Errorf("%s holds %s", path, got)
			}
		})
	}
}

// A folder a row cannot read says nothing of what it holds, so the tick ends there, even where the
// record behind it would have said so itself.
func TestAFailedReadEndsTheTickThere(t *testing.T) {
	for name, place := range map[string]struct {
		file    string
		blocked string
		mode    os.FileMode
	}{
		"seat records": {"state/session-acme.json", "state", 0o100},
		"code":         {"../code/api/.git/HEAD", "../code", 0},
		"a code entry": {"../code/api/.git/HEAD", "../code/api", 0},
		"own checkout": {"../agentkit/.git/HEAD", "../agentkit", 0},
	} {
		t.Run(name, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			put(t, filepath.Join(ak, place.file), "[Slice]\nTasksMax=100\n")
			put(t, filepath.Join(ak, "state/watch.json"), "{}")
			blocked := filepath.Join(ak, place.blocked)
			if err := os.Chmod(blocked, place.mode); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { os.Chmod(blocked, 0o700) })
			if _, err := os.ReadDir(blocked); err == nil {
				t.Skip("this user reads every folder")
			}
			endedThere(t, ak, "")
		})
	}
}

// A tick that cannot save watch.json fails, saying why in its log dated as every other line there.
func TestASaveThatFailsIsSaidDatedInTheLog(t *testing.T) {
	ak, _ := idleHome(t, answers)
	if err := os.MkdirAll(filepath.Join(ak, "state", "watch.tmp"), 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(ak, "tmp", logName)
	put(t, path, "")
	stream := appending(t, path)
	if _, failed := Carry(stream, stream); !failed {
		t.Fatal("the save did not fail")
	}
	lines := strings.SplitAfter(read(t, path), "\n")
	last := lines[len(lines)-2]
	for _, line := range lines[:len(lines)-1] {
		if !stamped.MatchString(line) {
			t.Errorf("undated in the log: %q", line)
		}
	}
	if want := "ak watch: [Errno 21] Is a directory: '" + filepath.Join(ak, "state", "watch.tmp") + "'\n"; stamped.ReplaceAllString(last, "") != want {
		t.Errorf("the tick ended its log with %q", last)
	}
}

// A corrupt watch.json reads as a fresh one, as Python's load_state reads it, and a table that is
// none as an empty one.
func TestWatchJSONReadsAsLoadStateReadsIt(t *testing.T) {
	ak, _ := idleHome(t, answers)
	for _, text := range []string{"", "{", "[]", "\xff", `{"reviewed": 1, "own": [], "stalls": null, "seen_at": "x", "after_merge": 2}`} {
		put(t, filepath.Join(ak, "state", "watch.json"), text)
		state, ok := loadState()
		if !ok || !quiet(state) {
			t.Errorf("%q read as %v %v", text, state, ok)
		}
	}
	put(t, filepath.Join(ak, "state", "watch.json"), `{"seen_at": {"a": -1, "b": true, "c": 1e999, "d": 2.5, "e": NaN}}`)
	state, _ := loadState()
	if got := run.Line(state.Get("seen_at")); got != `{"a": 0, "b": 0, "c": 0, "d": 2.5, "e": 0}` {
		t.Errorf("seen_at read as %s", got)
	}
}

// A save lets a newer generation, a stall told and a menu's boot recovery win.
func TestASaveKeepsWhatOthersWroteSince(t *testing.T) {
	ak, _ := idleHome(t, answers)
	path := filepath.Join(ak, "state", "watch.json")
	put(t, path, `{"mine": 1, "stalls": {"old": {"a": 1}, "gone": {"a": 1}}, "seen_at": {"old": 2, "gone": 1}}`)
	state, _ := loadState()
	state.Set("mine", 2)
	put(t, path, `{"stalls": {"told": {"told": 1}, "gone": {"b": 2}, "untold": {"b": 2}}, "seen_at": {"old": 1, "gone": 2}, "boot_id": "b", "boot_resume": {"id": "b"}}`)
	if err := saveState(state); err != nil {
		t.Fatal(err)
	}
	got := watched(t, ak)
	want := map[string]any{"told": map[string]any{"told": 1.0}, "old": map[string]any{"a": 1.0}, "gone": map[string]any{"b": 2.0}}
	if !reflect.DeepEqual(got["stalls"], want) {
		t.Errorf("stalls are %v", got["stalls"])
	}
	if !reflect.DeepEqual(got["seen_at"], map[string]any{"old": 2.0, "gone": 2.0}) {
		t.Errorf("seen_at is %v", got["seen_at"])
	}
	if got["mine"] != 2.0 || got["boot_id"] != "b" || got["boot_resume"] == nil {
		t.Errorf("kept %v", got)
	}
	if _, err := os.Stat(filepath.Join(ak, "state", "watch.tmp")); !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("the temporary stayed: %v", err)
	}
}

// One place says a pass raised and a pass was slow, and keeps the slowest; a clock of the test's.
func TestThroughSaysWhatARowDid(t *testing.T) {
	idleHome(t, answers)
	var out bytes.Buffer
	now, tick := time.Unix(100, 0), &ticking{log: newLog(&out, io.Discard)}
	tick.clock = func() time.Time { return now }
	takes := func(took time.Duration, err error) func() error {
		return func() error {
			now = now.Add(took)
			return err
		}
	}
	tick.through([]pass{
		{"never carried", false, nil, nil},
		{"quick one", false, nil, takes(time.Second, nil)},
		{"slow one", false, nil, takes(1500*time.Millisecond, nil)},
		{"raises", false, nil, takes(0, &fs.PathError{Op: "read", Path: "/a", Err: errIsDir()})},
	})
	want := "slow one took 1.5 s\nWARN raises did not run: [Errno 21] Is a directory: '/a'\n"
	if out.String() != want {
		t.Errorf("printed %q", out.String())
	}
	if tick.slowestName != "slow one" || tick.slowest != 1500*time.Millisecond {
		t.Errorf("slowest %s %v", tick.slowestName, tick.slowest)
	}
}

// A row that finds what Go does not carry, by its read or by its step, ends the tick there, what
// the rows before did standing and none after asked.
func TestThroughEndsAtTheRowThatFindsWork(t *testing.T) {
	idleHome(t, answers)
	for name, ending := range map[string]pass{
		"its read": {"ends", false, func() bool { return false }, nil},
		"its step": {"ends", false, nil, func() error { return errLeft }},
	} {
		t.Run(name, func(t *testing.T) {
			var ran []string
			row := func(name string) pass {
				return pass{name, false, func() bool { ran = append(ran, name+" read"); return true }, func() error {
					ran = append(ran, name)
					return nil
				}}
			}
			tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
			if tick.through([]pass{row("before"), ending, row("after")}) || !reflect.DeepEqual(ran, []string{"before read", "before"}) {
				t.Errorf("ran %v", ran)
			}
		})
	}
}

// A pull request on another's repository is followed, and one merged is Python's, past what the
// tick has written; the account's own, or an empty search, or a search that fails, leaves nothing
// to follow.
func TestWhatTheSearchFinds(t *testing.T) {
	viewed := func(state, printed string) string {
		return `case "$*" in "api user") ` + user + ` ;; *"pr view"*) echo '{"state": "` + state + `"}' ;; *) ` + printed + ` ;; esac`
	}
	search := func(printed string) string { return viewed("OPEN", printed) }
	page := func(address string) string {
		return `echo '{"items": [{"pull_request": {"html_url": "` + address + `"}}]}'`
	}
	for name, step := range map[string]struct {
		script  string
		carried bool
		said    string
	}{
		"none":     {search(`echo '{"items": []}'; echo '{"items": []}'`), true, ""},
		"own":      {search(page("https://github.com/ACME/api/pull/1")), true, ""},
		"issue":    {search(`echo '{"items": [{"pull_request": null}]}'`), true, ""},
		"theirs":   {search(page("https://github.com/other/api/pull/1")), true, ""},
		"second":   {search(`echo '{"items": []}'; ` + page("https://github.com/other/api/pull/1")), true, ""},
		"merged":   {viewed("MERGED", page("https://github.com/other/api/pull/1")), false, ""},
		"unread":   {search(`echo '{"items": [1]}'`), false, ""},
		"fails":    {search(`echo down >&2; exit 1`), true, "WARN authored PR discovery failed: down\n"},
		"no pages": {search(`echo '{}'`), true, "WARN authored PR discovery failed: gh did not return arrays of pages\n"},
	} {
		t.Run(name, func(t *testing.T) {
			ak, _ := idleHome(t, step.script)
			var out bytes.Buffer
			if carries(&out, io.Discard) != step.carried || out.String() != step.said {
				t.Errorf("printed %q", out.String())
			}
			if watched(t, ak)["tick"] == nil {
				t.Error("the tick ended unrecorded")
			}
		})
	}
}

// Each line a tick writes into its log starts with its date and time, its own breaks too.
func TestTheLogDatesEachLine(t *testing.T) {
	_, live, _ := tickHome(t)
	stream := appending(t, live)
	newLog(stream, stream).line("one\n\nthree")
	lines := strings.Split(strings.TrimSuffix(read(t, live), "\n"), "\n")
	if len(lines) != 3 {
		t.Fatalf("the log holds %q", lines)
	}
	for _, line := range lines {
		if !stamped.MatchString(line) {
			t.Errorf("undated: %q", line)
		}
	}
}

func errIsDir() error { return syscall.EISDIR }
