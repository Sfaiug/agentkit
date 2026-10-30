package hooks

import (
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// A copy of the shipped table whose file is ak's own, under a harness name of the test's own.
const own = `[hooks.install]
form = "file"
settings = "~/.acme/hooks/agentkit.json"
matchers = { PostToolUse = "ask_user_question", PreToolUse = "ask_user_question" }

[hooks.install.events]
UserPromptSubmit = ["seat-state.sh"]
Stop = ["seat-state.sh", "orchestrator-stop.sh"]
StopCancelled = ["seat-state.sh"]
StopFailure = ["seat-state.sh"]
Notification = ["seat-state.sh"]
PostToolUse = ["seat-state.sh"]
PreToolUse = ["orchestrator-stop.sh"]
`

// What the Python adapter's heredoc for that table wrote, captured once on 30 Oct 2026 as
// `python3 -` with REPO=/acme/ak in a temporary HOME, and what stdout says it runs.
const (
	ownSha  = "0fff0d1a4092bdac281df796d85bf426311da2197ed410eb1c6dd8f6e210ab8c"
	ownSaid = "bash /acme/ak/hooks/seat-state.sh on UserPromptSubmit, Stop, StopCancelled, StopFailure, Notification, PostToolUse; bash /acme/ak/hooks/orchestrator-stop.sh on Stop, PreToolUse"
)

// ownTable is that table, its file under a fresh HOME.
func ownTable(t *testing.T) config.HookTable {
	home, adapters := t.TempDir(), t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	if err := os.WriteFile(filepath.Join(adapters, "acme.toml"), []byte(own), 0o600); err != nil {
		t.Fatal(err)
	}
	found, ok, err := config.Hooks("acme")
	if err != nil || !ok || !found.File {
		t.Fatalf("no file of ak's own: %+v %v", found, err)
	}
	return found
}

// sha is the sha256 of the file's bytes.
func sha(t *testing.T, path string) string {
	wrote, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return fmt.Sprintf("%x", sha256.Sum256(wrote))
}

// The file is written as the heredoc wrote it, then found there and left alone, then, once it
// differs, moved to the day's backup, its mode and time kept, and written again.
func TestTheFileIsWhatTheHeredocWrote(t *testing.T) {
	table := ownTable(t)
	path, made := table.Settings, time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	code, out, errOut := install(table)
	if code != 0 || errOut != "" || out != fmt.Sprintf("hooks: %s now runs %s\n", path, ownSaid) || sha(t, path) != ownSha {
		t.Fatalf("exit %d, stdout %q, stderr %q", code, out, errOut)
	}
	// what json.load reads as the same is installed, however it is spaced
	if err := os.WriteFile(path, []byte(run.Line(document(table, root))), 0o666); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(path, made, made); err != nil {
		t.Fatal(err)
	}
	code, out, errOut = install(table)
	info, _ := os.Stat(path)
	names, _ := filepath.Glob(path + "*")
	if code != 0 || errOut != "" || out != fmt.Sprintf("hooks: %s already installed, running %s\n", path, ownSaid) ||
		!info.ModTime().Equal(made) || len(names) != 1 {
		t.Fatalf("exit %d, stdout %q, stderr %q, files %q", code, out, errOut, names)
	}
	if err := os.WriteFile(path, []byte("{}"), 0o640); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o640); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(path, made, made); err != nil {
		t.Fatal(err)
	}
	stamps := []string{time.Now().Format("20060102")}
	code, out, errOut = install(table)
	stamps = append(stamps, time.Now().Format("20060102"))
	names, _ = filepath.Glob(path + ".bak-*")
	if code != 0 || errOut != "" || len(names) != 1 || !slices.Contains(stamps, strings.TrimPrefix(names[0], path+".bak-")) ||
		out != fmt.Sprintf("backed up %s -> %s\nhooks: %s now runs %s\n", path, names[0], path, ownSaid) || sha(t, path) != ownSha {
		t.Fatalf("exit %d, stdout %q, stderr %q, backups %q", code, out, errOut, names)
	}
	kept, _ := os.ReadFile(names[0])
	info, err := os.Stat(names[0])
	if err != nil || string(kept) != "{}" || !info.ModTime().Equal(made) || runtime.GOOS != "windows" && info.Mode() != 0o640 {
		t.Fatalf("backup %q, %v, %v", kept, info, err)
	}
}

// Whatever else is in the file's place, unreadable as a directory is, is moved aside too.
func TestADirectoryInTheFilesPlaceIsMovedAside(t *testing.T) {
	table := ownTable(t)
	if err := os.MkdirAll(table.Settings, 0o700); err != nil {
		t.Fatal(err)
	}
	code, _, errOut := install(table)
	info, err := os.Stat(table.Settings + ".bak-" + time.Now().Format("20060102"))
	if code != 0 || errOut != "" || err != nil || !info.IsDir() || sha(t, table.Settings) != ownSha {
		t.Fatalf("exit %d, stderr %q, backup %v %v", code, errOut, info, err)
	}
}

// A hooks directory that cannot be made exits 1, the heredoc's traceback, in one line.
func TestAHooksDirectoryThatCannotBeMadeExits1(t *testing.T) {
	table := ownTable(t)
	home := filepath.Dir(filepath.Dir(table.Settings))
	if err := os.WriteFile(home, []byte("acme"), 0o600); err != nil {
		t.Fatal(err)
	}
	code, out, errOut := install(table)
	kept, _ := os.ReadFile(home)
	if code != 1 || out != "" || strings.Count(errOut, "\n") != 1 || string(kept) != "acme" {
		t.Fatalf("exit %d, stdout %q, stderr %q", code, out, errOut)
	}
}

// The hooks directory is made as the home is spelled, never cleaned, as Python's makedirs makes
// it: a `..` after a name is that name's parent, made where it is missing.
func TestTheHooksDirectoryIsMadeAsTheHomeIsSpelled(t *testing.T) {
	table := ownTable(t)
	home := os.Getenv("HOME")
	table.Settings = filepath.Join(home, "missing") + string(filepath.Separator) + filepath.Join("..", "chosen", "hooks", "agentkit.json")
	code, _, errOut := install(table)
	if code != 0 || errOut != "" || sha(t, filepath.Join(home, "chosen", "hooks", "agentkit.json")) != ownSha {
		t.Fatalf("exit %d, stderr %q", code, errOut)
	}
}
