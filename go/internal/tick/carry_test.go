//go:build unix

package tick

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"agentkit/internal/run"
)

const (
	user    = `echo '{"login": "acme"}'`
	answers = `case "$*" in "api user") ` + user + ` ;; *) echo '{"items": []}' ;; esac`
)

// idleHome is a home with nothing to act on and the audit off, whose gh runs script, and where it
// keeps ak's own files.
func idleHome(t *testing.T, script string) (ak string, gh func(string)) {
	t.Helper()
	home, bin := t.TempDir(), t.TempDir()
	for key, value := range map[string]string{
		"HOME": home, "USERPROFILE": home, "TMUX_TMPDIR": t.TempDir(), "AGENTKIT_TMUX_SOCKET": "tick-test",
		"AGENTKIT_SESSION": "", "AGENTKIT_ADAPTER_DIR": "", "XDG_RUNTIME_DIR": t.TempDir(), "XDG_CONFIG_HOME": "",
		"PATH": bin + string(os.PathListSeparator) + os.Getenv("PATH"),
	} {
		t.Setenv(key, value)
	}
	ak = filepath.Join(home, ".agentkit")
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n")
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
	if !Carry(&out, io.Discard) || out.Len() != 0 {
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
	if !Carry(&out, io.Discard) || out.String() != "gh is not logged in; PR checks skipped (To get started, please run: gh auth login)\n" {
		t.Fatalf("printed %q", out.String())
	}
	at := watched(t, ak)["gh_out"]
	if at == nil {
		t.Fatal("no logout on record")
	}
	gh("echo offline >&2; exit 1")
	out.Reset()
	if !Carry(&out, io.Discard) || out.String() != "WARN GitHub is unavailable; PR checks skipped (offline)\n" {
		t.Fatalf("printed %q", out.String())
	}
	if got := watched(t, ak)["gh_out"]; !reflect.DeepEqual(got, at) {
		t.Errorf("gh_out went from %v to %v", at, got)
	}
}

// What a read finds to act on leaves the tick to Python with nothing written.
func TestAnythingToActOnWritesNothing(t *testing.T) {
	for path, content := range map[string]string{
		"runs/fix-api":                "",
		"jobs/fix-api":                "",
		"secrets/acme":                "",
		"history.db":                  "",
		"state/session-acme.json":     "{}",
		"state/card-acme.json":        "{}",
		"state/alive.json":            "{}",
		"state/google-cloud-need":     "4096\n",
		"state/notification-outbox/a": "",
		"state/watch.json":            `{"reviewed": {"https://github.com/acme/api/pull/1": {}}}`,
		"state/watch.json#own":        `{"own": {"https://github.com/acme/api/pull/1": {}}}`,
		"state/watch.json#stalls":     `{"stalls": {"acme": {}}}`,
		"state/watch.json#seen":       `{"seen_at": {"acme": 1}}`,
		"state/watch.json#merge":      `{"after_merge": {"acme/api": {}}}`,
		"state/watch.json#auth":       `{"auth_out": {"claude": {"ok": false}}}`,
		"state/watch.json#tokens":     `{"worker_tokens": {"claude": {}}}`,
		"state/watch.json#surrogate":  `{"mine": "\ud800"}`,
		"config.toml":                 "[audit]\non = true\n",
		"config.toml#absent":          "",
		"config.toml#renting":         "[audit]\non = false\n[google_cloud]\nactive = true\n",
		"../code/api/.git/HEAD":       "",
		"../agentkit/.git/HEAD":       "",
		"../.config/systemd/user/tick-test.slice.d/ceiling.conf": "[Slice]\nTasksMax=100\n",
	} {
		t.Run(path, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			path, _, _ := strings.Cut(path, "#")
			put(t, filepath.Join(ak, path), content)
			before := files(t, filepath.Dir(ak))
			var out, errOut bytes.Buffer
			if Carry(&out, &errOut) || out.Len()+errOut.Len() != 0 {
				t.Fatalf("carried it, printing %q %q", out.String(), errOut.String())
			}
			if after := files(t, filepath.Dir(ak)); !reflect.DeepEqual(before, after) {
				t.Errorf("wrote %v", after)
			}
		})
	}
}

// A process of this HOME carrying ak's mark, or a seat's tag, is the leftover sweep's to judge.
func TestAMarkedProcessIsForTheSweep(t *testing.T) {
	idleHome(t, answers)
	if !noLeftovers() {
		t.Fatal("no process of this HOME, yet a leftover")
	}
	if _, err := os.Stat("/proc/self/environ"); err != nil {
		t.Skip("no /proc")
	}
	// /proc shows a process's environment as it started: only a child can hold the mark
	marked := startSleep(t, "AK_OWNER=1 2 3 4 ak watch")
	defer marked()
	if noLeftovers() {
		t.Error("a marked process went unseen")
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

// A pull request on another's repository is Python's to follow, past what the tick has written;
// the account's own, or an empty search, or a search that fails, leaves nothing to follow.
func TestWhatTheSearchFinds(t *testing.T) {
	search := func(printed string) string {
		return `case "$*" in "api user") ` + user + ` ;; *) ` + printed + ` ;; esac`
	}
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
		"theirs":   {search(page("https://github.com/other/api/pull/1")), false, ""},
		"second":   {search(`echo '{"items": []}'; ` + page("https://github.com/other/api/pull/1")), false, ""},
		"unread":   {search(`echo '{"items": [1]}'`), false, ""},
		"fails":    {search(`echo down >&2; exit 1`), true, "WARN authored PR discovery failed: down\n"},
		"no pages": {search(`echo '{}'`), true, "WARN authored PR discovery failed: gh did not return arrays of pages\n"},
	} {
		t.Run(name, func(t *testing.T) {
			ak, _ := idleHome(t, step.script)
			var out bytes.Buffer
			if Carry(&out, io.Discard) != step.carried || out.String() != step.said {
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

// startSleep runs a child holding the environment word, for as long as the test lasts.
func startSleep(t *testing.T, word string) func() {
	t.Helper()
	child := exec.Command("sleep", "60")
	child.Env = append(os.Environ(), word)
	if err := child.Start(); err != nil {
		t.Fatal(err)
	}
	stop := func() {
		child.Process.Kill()
		child.Wait()
	}
	// Start returns a moment before the exec has filled in what /proc shows
	environ := filepath.Join("/proc", strconv.Itoa(child.Process.Pid), "environ")
	for deadline := time.Now().Add(time.Minute); ; time.Sleep(time.Millisecond) {
		if data, _ := os.ReadFile(environ); strings.Contains(string(data), word) {
			return stop
		}
		if time.Now().After(deadline) {
			stop()
			t.Fatal("the child's environment never showed")
		}
	}
}
