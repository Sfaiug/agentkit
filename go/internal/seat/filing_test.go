package seat

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// filingHome is a home with the checkout acme and the seat fix-api filed under nothing.
func filingHome(t *testing.T) (home, state string) {
	t.Helper()
	home = sandbox(t)
	if err := os.MkdirAll(filepath.Join(home, "code", "acme", ".git"), 0o700); err != nil {
		t.Fatal(err)
	}
	record(t, home, "fix-api", nil)
	return home, filepath.Join(home, ".agentkit", "state")
}

// A read Go cannot make, what the key does not reach, leaves the verb to Python with nothing filed.
func TestFilingLeavesToPythonWhatGoCannotRead(t *testing.T) {
	onAcme := func(home string) string { return filepath.Join(home, "code", "acme") }
	for name, build := range map[string]func(t *testing.T, home, state string){
		"a run record Go cannot keep": func(t *testing.T, home, state string) {
			write(t, filepath.Join(home, ".agentkit", "runs", "r", "run.json"), `{"state": "queued", "title": "\ud800"}`)
		},
		"another seat's record Go cannot keep": func(t *testing.T, home, state string) {
			write(t, filepath.Join(state, "session-other.json"), `{"title": "\ud800"}`)
		},
		"a run whose seat's rename chain loops, ended or not": func(t *testing.T, home, state string) {
			write(t, filepath.Join(state, "session-a.json"), `{"renamed": "b"}`)
			write(t, filepath.Join(state, "session-b.json"), `{"renamed": "a"}`)
			runRecord(t, home, "r", map[string]any{"state": "pass", "launched_session": "a"})
		},
		"a plan that is not UTF-8": func(t *testing.T, home, state string) {
			record(t, home, "other", map[string]any{"repo": onAcme(home)})
			write(t, filepath.Join(state, "plan-other.md"), "- [ ] \xff\n")
		},
		"a line's path Go reads otherwise": func(t *testing.T, home, state string) {
			runRecord(t, home, "r", map[string]any{"state": "queued", "launched_session": "other", "repo": onAcme(home)})
			write(t, filepath.Join(state, "plan-other.md"), "- [ ] x · check: `t` · ~/code/../acme#abc1234 · written 2026-10-20 09:00\n")
		},
		"a runs folder that cannot be listed": func(t *testing.T, home, state string) {
			write(t, filepath.Join(home, ".agentkit", "runs"), "")
		},
		"the seat's own record unparsable": func(t *testing.T, home, state string) {
			write(t, filepath.Join(state, "session-fix-api.json"), "{")
		},
		"a checkout's place that cannot be looked at": func(t *testing.T, home, state string) {
			if err := os.Symlink("loop", filepath.Join(home, "code", "loop")); err != nil {
				t.Fatal(err)
			}
		},
	} {
		t.Run(name, func(t *testing.T) {
			home, state := filingHome(t)
			build(t, home, state)
			path := filepath.Join(state, "session-fix-api.json")
			before, _ := os.ReadFile(path)
			said, known, err := File("fix-api", "acme", 80, time.Now())
			if known || said != "" || err != nil {
				t.Fatal(said, known, err)
			}
			if after, _ := os.ReadFile(path); string(after) != string(before) {
				t.Error(string(after))
			}
		})
	}
}

// A name only Python's casefold or expanduser can place is left to it, with nothing filed; spelled
// exactly it needs neither.
func TestFilingLeavesToPythonWhatOnlyPythonCanPlace(t *testing.T) {
	home, state := filingHome(t)
	if err := os.MkdirAll(filepath.Join(home, "code", "Straße", ".git"), 0o700); err != nil {
		t.Fatal(err)
	}
	for _, named := range []string{"STRASSE", "ACME", "/nowhere/ß", "~bob/code/acme"} {
		if said, known, err := File("fix-api", named, 80, time.Now()); known || said != "" || err != nil {
			t.Error(named, said, known, err)
		}
	}
	if kept, _ := run.ReadJSON(filepath.Join(state, "session-fix-api.json")); kept.Has("filed") {
		t.Error(run.Line(kept))
	}
	for _, named := range []string{"acme", "Straße"} {
		if said, known, err := File("fix-api", named, 80, time.Now()); !known || err != nil || !strings.HasPrefix(said, "filed fix-api under "+named+"\n") {
			t.Error(named, said, known, err)
		}
	}
}

// What Python's changed_files reads as nothing changed is told as nothing.
func TestFilingHearsNothingFromARunThatChangesNothingItCanName(t *testing.T) {
	for name, build := range map[string]func(t *testing.T, home, dir string, fields map[string]any){
		"a saved task whose front matter Python refuses": func(t *testing.T, home, dir string, fields map[string]any) {
			write(t, filepath.Join(dir, "task.md"), "---\nbogus: 1\nfiles: a.py\n---\n# t\n")
		},
		"a worktree git cannot read": func(t *testing.T, home, dir string, fields map[string]any) {
			fields["worktree"], fields["base_sha"] = t.TempDir(), "abc1234"
			write(t, filepath.Join(dir, "task.md"), "---\nfiles: a.py\n---\n# t\n")
		},
	} {
		t.Run(name, func(t *testing.T) {
			home, _ := filingHome(t)
			fields := map[string]any{"state": "queued", "launched_session": "", "repo": filepath.Join(home, "code", "acme")}
			build(t, home, filepath.Join(home, ".agentkit", "runs", "r"), fields)
			runRecord(t, home, "r", fields)
			said, known, err := File("fix-api", "acme", 80, time.Now())
			if !known || err != nil || said != "filed fix-api under acme\nnothing else in flight on acme" {
				t.Fatal(said, known, err)
			}
			kept, _ := run.ReadJSON(filepath.Join(home, ".agentkit", "state", "session-fix-api.json"))
			if kept.Str("repo") != filepath.Join(home, "code", "acme") || !kept.Truthy("filed") {
				t.Error(run.Line(kept))
			}
		})
	}
}

// A path that is not UTF-8 cannot be printed as Python reads it, so nothing is filed.
func TestFilingLeavesToPythonAChangedPathThatIsNotText(t *testing.T) {
	home, state := filingHome(t)
	tree := t.TempDir()
	git := func(args ...string) string {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", tree, "-c", "user.name=t", "-c", "user.email=t@example.com"}, args...)...)
		out, err := cmd.Output()
		if err != nil {
			t.Skip("git here cannot hold it: ", err)
		}
		return strings.TrimSpace(string(out))
	}
	git("init", "-q")
	git("commit", "-q", "--allow-empty", "-m", "base")
	if err := os.WriteFile(filepath.Join(tree, "\xff"), nil, 0o600); err != nil {
		t.Skip("this file system holds only text names")
	}
	git("add", ".")
	runRecord(t, home, "r", map[string]any{"state": "running", "launched_session": "other", "repo": filepath.Join(home, "code", "acme"),
		"worktree": tree, "base_sha": git("rev-parse", "HEAD")})
	if said, known, err := File("fix-api", "acme", 80, time.Now()); known || said != "" || err != nil {
		t.Fatal(said, known, err)
	}
	if kept, _ := run.ReadJSON(filepath.Join(state, "session-fix-api.json")); kept.Has("filed") {
		t.Error(run.Line(kept))
	}
}
