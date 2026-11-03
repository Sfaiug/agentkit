package guard

import (
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"testing"
)

// nowhere is a real tool that cannot start: tmux answers nothing, as with no server.
const nowhere = "/nonexistent/tmux"

// seated is a home with a record for each seat, this process running in the first.
func seated(t *testing.T, seats ...string) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_INBOX_SESSION", "")
	t.Setenv("AGENTKIT_SESSION", seats[0])
	if err := os.MkdirAll(filepath.Join(home, ".agentkit", "state"), 0o777); err != nil {
		t.Fatal(err)
	}
	for _, seat := range seats {
		put(t, filepath.Join(home, ".agentkit", "state", "session-"+seat+".json"), `{"orchestrator": "opus"}`)
	}
	return home
}

func put(t *testing.T, path, text string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
		t.Fatal(err)
	}
}

func TestACommandEndsOnlyAtAnEndingSemicolon(t *testing.T) {
	got := commands([]string{"send-keys", "a;b", `c\;`, "d;", "kill-pane", ";", ";", "list-keys"})
	want := [][]string{{"send-keys", "a;b", `c\;`, "d"}, {"kill-pane"}, {"list-keys"}}
	if !slices.EqualFunc(got, want, slices.Equal[[]string]) {
		t.Fatalf("got %q", got)
	}
}

func TestServerOptionsReadAsGetopt(t *testing.T) {
	for _, each := range []struct {
		args   []string
		server []string
		first  int
	}{
		{[]string{"-L", "acme", "kill-server"}, []string{"-L", "acme"}, 2},
		{[]string{"-uLacme", "kill-server"}, []string{"-L", "acme"}, 1},
		{[]string{"-f", "/dev/null", "-S", "/s", "--", "ls"}, []string{"-S", "/s"}, 5},
		{[]string{"-L"}, []string{"-L", ""}, 1}, // a value nobody gave
	} {
		server, first := serverOptions(each.args)
		if !slices.Equal(server, each.server) || first != each.first {
			t.Errorf("%q: got %q, %d", each.args, server, first)
		}
	}
}

func TestAWordRunsACommandByNameAliasOrUniquePrefix(t *testing.T) {
	known := slices.Concat(ends, types)
	for word, want := range map[string]string{"kill-pane": "kill-pane", "killw": "kill-window", "send": "send-keys", "kill-ser": "kill-server",
		"kill-s": "", "send-": "", "": "", "new": "", "list-keys": ""} {
		if got := knownCommand(word, known); got != want {
			t.Errorf("%q runs %q, not %q", word, got, want)
		}
	}
	if got := knownCommand("new", starts); got != "new-session" {
		t.Errorf("new starts %q", got)
	}
}

func TestOptionsReadAsGetopt(t *testing.T) {
	if target, every, clear := options([]string{"-aC", "-tacme", "x"}, ""); target != "acme" || !every || !clear {
		t.Errorf("clustered: %q %v %v", target, every, clear)
	}
	if target, _, _ := options([]string{"-N", "3", "-t", "acme"}, "cN"); target != "acme" {
		t.Errorf("after a valued option: %q", target)
	}
	if target, every, _ := options([]string{"-ca", "-t", "acme"}, "cN"); target != "acme" || every {
		t.Errorf("a letter in a valued option's value: %q %v", target, every)
	}
	if target, _, _ := options([]string{"--", "-t", "acme"}, ""); target != "" {
		t.Errorf("past the options' end: %q", target)
	}
	if !hasFlag([]string{"-O", "-I"}, 'I', "") || hasFlag([]string{"-tI"}, 'I', "") || hasFlag([]string{"--", "-I"}, 'I', "") {
		t.Error("pipe-pane's -I")
	}
}

func TestWhatATmuxCallStartsSpeaksForTheSeat(t *testing.T) {
	seated(t, "acme")
	refused, run := Decide("tmux", nowhere, []string{"-L", "s", "new", "-d", ";", "neww", "x;", "list-keys", ";", "send-keys", `y\;`})
	want := []string{"-L", "s", "new", "-e", "AGENTKIT_SESSION=acme", "-e", "AK_TMUX_OWNER=acme", "-d", ";",
		"neww", "-e", "AGENTKIT_SESSION=acme", "x", ";", "list-keys", ";", "send-keys", `y\;`}
	if refused != "" || !slices.Equal(run, want) {
		t.Fatalf("%q, %q", refused, run)
	}
	given := []string{"-L", "s", "list-keys;"} // nothing started: the call as typed, to the letter
	if _, run := Decide("tmux", nowhere, given); !slices.Equal(run, given) {
		t.Fatalf("%q", run)
	}
}

func TestWhatTmuxCannotAnswerRefusesNothing(t *testing.T) {
	seated(t, "acme", "beta")
	for _, args := range [][]string{{"kill-server"}, {"kill-session", "-t", "beta"}, {"send-keys", "-t", "beta", "x"}} {
		if refused, run := Decide("tmux", nowhere, args); refused != "" || !slices.Equal(run, args) {
			t.Errorf("%q: %q, %q", args, refused, run)
		}
	}
}

// A guard that cannot read the seat's name runs the call untouched, where its answer hangs on it.
func TestAFailedGuardRunsTheCallUntouched(t *testing.T) {
	home := seated(t, "acme")
	put(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"), `{"renamed": "acme"}`)
	put(t, filepath.Join(home, ".agentkit", "config.toml"), `live_host = "prod"`+"\n")
	for name, args := range map[string][]string{"tmux": {"new-window"}, "gh": {"pr", "merge", "7"}, "scp": {"a", "prod:/b"}} {
		if refused, run := Decide(name, "/usr/bin/"+name, args); refused != "" || !slices.Equal(run, args) {
			t.Errorf("%s: %q, %q", name, refused, run)
		}
	}
	if refused, _ := Decide("git", "/usr/bin/git", []string{"worktree", "add", filepath.Join(home, "code", "x")}); refused == "" {
		t.Error("git's refusal asks no seat's name, and went with it")
	}
	if refused, run := Decide("ls", "/usr/bin/ls", []string{"-l"}); refused != "" || !slices.Equal(run, []string{"-l"}) {
		t.Errorf("a tool nothing guards: %q, %q", refused, run)
	}
}

func TestOnlyTheInboxMerges(t *testing.T) {
	seated(t, "acme", "inbox")
	for _, args := range [][]string{{"pr", "merge"}, {"--repo", "a/b", "pr", "-R", "a/b", "merge"}, {"pr", "--repo=a/b", "merge", "7"}} {
		if refused, _ := Decide("gh", "/usr/bin/gh", args); !strings.HasPrefix(refused, "ak refused `gh pr merge`") {
			t.Errorf("%q: %q", args, refused)
		}
	}
	for _, args := range [][]string{{"pr", "view", "merge"}, {"pr"}, {"-R", "pr", "merge"}} {
		if refused, _ := Decide("gh", "/usr/bin/gh", args); refused != "" {
			t.Errorf("%q: %q", args, refused)
		}
	}
	t.Setenv("AGENTKIT_SESSION", "inbox")
	if refused, _ := Decide("gh", "/usr/bin/gh", []string{"pr", "merge"}); refused != "" {
		t.Error(refused)
	}
}

// git walks `..` through a link to where the link leads, so no lexical cleaning may read it.
func TestACheckoutPathIsReadAsGitWalksIt(t *testing.T) {
	home := seated(t, "acme")
	project := filepath.Join(home, "code", "acme")
	away := filepath.Join(home, "away", "deep")
	for _, folder := range []string{project, away} {
		if err := os.MkdirAll(folder, 0o777); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Symlink(project, filepath.Join(away, "in")); err != nil {
		t.Fatal(err)
	}
	back, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(back) })
	if err := os.Chdir(away); err != nil {
		t.Fatal(err)
	}
	for _, each := range []struct {
		args    []string
		refused string // the path it names, "" where git may make it
	}{
		{[]string{"worktree", "add", "in/../fix"}, "in/../fix"},
		{[]string{"-C", "in", "worktree", "add", "-b", "x", "../fix"}, "../fix"},
		{[]string{"-c", "a=b", "--git-dir", "x", "worktree", "add", "-qfbx", "in/fix"}, "in/fix"},
		{[]string{"worktree", "add", "-bx", "--lock", "--reason", "in/no", "--", "in/fix"}, "in/fix"},
		{[]string{"worktree", "add", "here"}, ""},
		{[]string{"worktree", "add", "-b", "in/fix"}, ""}, // -b's value: no path named
		{[]string{"worktree", "list", "in/fix"}, ""},
		{[]string{"worktree"}, ""},
		{[]string{"-C"}, ""},
	} {
		refused, _ := Decide("git", "/usr/bin/git", each.args)
		if each.refused == "" && refused != "" || each.refused != "" && !strings.HasPrefix(refused, "ak refused `git worktree add "+each.refused+"`") {
			t.Errorf("%q: %q", each.args, refused)
		}
	}
}

func TestArgHost(t *testing.T) {
	for _, each := range []struct{ arg, tool, host string }{
		{"prod:/srv", "scp", "prod"}, {"deploy@prod:/srv", "scp", "prod"}, {"scp://deploy@prod:22/srv", "scp", "prod"},
		{"rsync://prod/srv", "rsync", "prod"}, {"prod", "scp", ""}, {"./prod:x", "scp", ""}, {"/a:b", "rsync", ""},
		{"prod", "sftp", "prod"}, {"deploy@prod", "sftp", "prod"},
	} {
		if got := argHost(each.arg, each.tool); got != each.host {
			t.Errorf("%s %q names %q", each.tool, each.arg, got)
		}
	}
}

func TestTheLiveHostReadsFromConfigOrIsNone(t *testing.T) {
	home := seated(t, "acme")
	config := filepath.Join(home, ".agentkit", "config.toml")
	for _, each := range []string{"", `live_host = 5`, `live_host = "prod`} {
		put(t, config, each+"\n")
		if refused, _ := Decide("scp", "/usr/bin/scp", []string{"a", "prod:/b"}); refused != "" {
			t.Errorf("%q: %q", each, refused)
		}
	}
	put(t, config, `live_host = "prod"`+"\n")
	if refused, _ := Decide("scp", "/usr/bin/scp", []string{"a", "prod:/b", "--exclude", "x"}); !strings.HasPrefix(refused, "ak refused `scp` to prod") {
		t.Error(refused)
	}
	for _, args := range [][]string{{"prod:/a", "."}, {"a"}, {}} {
		if refused, _ := Decide("scp", "/usr/bin/scp", args); refused != "" {
			t.Errorf("%q: %q", args, refused)
		}
	}
}

// Kept under the name it was launched with, whatever a rename left it going by.
func TestAnSshToTheLiveHostIsWrittenDown(t *testing.T) {
	home := seated(t, "acme")
	state := filepath.Join(home, ".agentkit", "state")
	live := filepath.Join(state, "live-acme.txt")
	put(t, filepath.Join(home, ".agentkit", "config.toml"), `live_host = "prod"`+"\n")
	args := []string{"-p", "22", "deploy@prod", "uptime"}
	if refused, run := Decide("ssh", "/usr/bin/ssh", args); refused != "" || !slices.Equal(run, args) {
		t.Fatalf("%q, %q", refused, run)
	}
	data, err := os.ReadFile(live)
	if err != nil {
		t.Fatal(err)
	}
	if at, err := strconv.ParseFloat(strings.TrimSpace(string(data)), 64); err != nil || at <= 0 {
		t.Fatalf("%q", data)
	}
	if err := os.Remove(live); err != nil {
		t.Fatal(err)
	}
	Decide("ssh", "/usr/bin/ssh", []string{"other", "uptime"})
	if _, err := os.Stat(live); err == nil {
		t.Error("an ssh elsewhere was written down")
	}
	if err := os.RemoveAll(state); err != nil {
		t.Fatal(err)
	}
	if refused, run := Decide("ssh", "/usr/bin/ssh", args); refused != "" || !slices.Equal(run, args) {
		t.Errorf("nowhere to write it: %q, %q", refused, run)
	}
}
