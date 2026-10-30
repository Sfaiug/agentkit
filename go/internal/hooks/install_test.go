package hooks

import (
	"bytes"
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

const owners = `{ "theme": "light",
  "hooks": { "Stop": [{"hooks": [{"type": "command", "command": "bash /x/mine.sh"}]}] } }
`

// Each settings file as given ("" for none) and what the heredoc of `adapters/claude.sh hooks`
// made of it, captured once on 30 Oct 2026 as `python3 - <file> 20261030 /acme/ak` in a
// temporary HOME: the sha256 of the file it wrote, else its exit code and stderr (%s for the
// file) with the file left as it was.
var heredoc = []struct{ name, given, sha, err string }{
	{"no file", "", "afd1e4bc08459f9622de5352702b7874a2f0ef6cb2df7f58641fe77c3d0a1d6c", ""},
	{"{}", "{}", "afd1e4bc08459f9622de5352702b7874a2f0ef6cb2df7f58641fe77c3d0a1d6c", ""},
	{"the owner's", owners, "cdc19829454b0e42d53e7dff1a8b245cf616f741fbf201425160b13e773c1367", ""},
	{"an older install's", `{"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "bash /old/agentkit/hooks/seat-state.sh"}, {"type": "command", "command": "bash /x/lint.sh"}]}], "Stop": [{"hooks": [{"type": "command", "command": "bash /old/agentkit/hooks/idle-compact-stop.sh"}]}]}}`,
		"3739775143bb1862fcd05d57934ac0e24285a139dda8abd64655ce3a9c8cbe8a", ""},
	{"a group shared with another tool", `{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "bash /x/lint.sh"}, {"type": "command", "command": "bash /old/hooks/orchestrator-stop.sh", "timeout": 5}]}]}}`,
		"7d6e9f13c0a6eff6069d410878a5f10af7ea8c4287dbe42ff15291f902dccbcc", ""},
	{"two of ours in one event across groups", `{"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"command": "bash /a/hooks/seat-state.sh"}, {"type": "command", "command": "bash /x/lint.sh"}]}, {"hooks": [{"command": "bash /b/hooks/idle-compact-stop.sh"}]}], "Stop": [{"hooks": [{"command": "bash /a/hooks/seat-state.sh"}]}, {"hooks": [{"command": "bash /b/hooks/seat-state.sh", "async": true}]}]}}`,
		"f051fc51415c4f6088b9ce47b0abf8b633c9cf01699e9bede4db04577f100784", ""},
	{"a list", "[]", "", "%s is not a JSON object; left alone\n"},
	{"not JSON", "{bad", "", "%s is not valid JSON (Expecting property name enclosed in double quotes: line 1 column 2 (char 1)); left alone\n"},
	{"hooks as a list", `{"hooks": [], "theme": "dark"}`, "d709b0b344078ca34672ca23b7bf9621f2e0a3816ed91083e6753513d3d9bcc0", ""},
	{"non-ASCII and U+007F", "{\"name\": \"caf\u00e9 \u2615 \U0001d11e\", \"del\": \"\x7f\", \"esc\": \"\\u00e9\"}",
		"c3acf2f96630eef7995f7ed361c133edb889316fe72d394dc45f922dc288d8bd", ""},
	{"0.1", `{"n": 0.1}`, "b526b693f646cede6519cede1a5efe8a196dc963eeea1a3b8207827f20df9ff3", ""},
	{"1e16", `{"n": 1e16}`, "1d0b9b62ee38b8d07216837e9669c1878e3277b83d9088a6e76ea7614c0247e4", ""},
	{"a 20-digit integer", `{"n": 12345678901234567890}`, "aa2bbe8a975842c576e5d73d7aecd3f2d6a8bb5e448859cb13cca319781f1b7d", ""},
	{"NaN", `{"n": NaN, "m": -Infinity}`, "5922b8f928b88005a8d61dba27aff7005b16be579ca1b0c0901b8b5aafce41a9", ""},
	{"a repeated key", `{"a": 1, "b": 2, "a": 3}`, "fabe3e9230cb8744deaa5bb9c26d022e113e35af0545c81dc13b21376d94d3ba", ""},
	// Go's own: Python crashes on the first and keeps the second, which no Go string holds
	{"not UTF-8", "{\"s\": \"\xff\"}", "", "%s is not valid JSON (not UTF-8); left alone\n"},
	{"a lone surrogate", `{"s": "\ud800"}`, "", "%s is not valid JSON (a lone surrogate); left alone\n"},
}

const root = "/acme/ak"

// said is what the table has run, as stdout says it.
const said = "bash /acme/ak/hooks/seat-state.sh on SessionStart, UserPromptSubmit, Stop, StopFailure, Notification, PermissionRequest, PostToolUse, PreCompact, PostCompact; bash /acme/ak/hooks/orchestrator-stop.sh on Stop, PreToolUse"

// table is the shipped manifest's, its settings file under a fresh HOME.
func table(t *testing.T) config.HookTable {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	found, ok, err := config.Hooks("claude")
	if err != nil || !ok {
		t.Fatalf("no [hooks.install] table: %v", err)
	}
	return found
}

func install(table config.HookTable) (code int, out, errOut string) {
	var stdout, stderr bytes.Buffer
	code = Install(table, root, &stdout, &stderr)
	return code, stdout.String(), stderr.String()
}

func TestInstallWritesWhatTheHeredocWrote(t *testing.T) {
	for _, each := range heredoc {
		t.Run(each.name, func(t *testing.T) {
			table := table(t)
			path, made := table.Settings, time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
			if each.given != "" {
				if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, []byte(each.given), 0o640); err != nil {
					t.Fatal(err)
				}
				if err := os.Chtimes(path, made, made); err != nil {
					t.Fatal(err)
				}
			}
			stamps := []string{time.Now().Format("20060102")}
			code, out, errOut := install(table)
			stamps = append(stamps, time.Now().Format("20060102"))
			wrote, _ := os.ReadFile(path)
			names, _ := filepath.Glob(path + "*")
			if each.sha == "" {
				if code != 1 || errOut != fmt.Sprintf(each.err, path) || out != "" || string(wrote) != each.given || len(names) != 1 {
					t.Fatalf("exit %d, stdout %q, stderr %q, file %q, files %q", code, out, errOut, wrote, names)
				}
				return
			}
			if code != 0 || errOut != "" || fmt.Sprintf("%x", sha256.Sum256(wrote)) != each.sha {
				t.Fatalf("exit %d, stderr %q, wrote:\n%s", code, errOut, wrote)
			}
			want := fmt.Sprintf("hooks: %s now runs %s\n", path, said)
			if each.given == "" {
				if out != want || len(names) != 1 {
					t.Fatalf("stdout %q, files %q", out, names)
				}
				return
			}
			backup := names[len(names)-1]
			stamp := strings.TrimPrefix(backup, path+".bak-")
			if out != fmt.Sprintf("backed up %s -> %s\n", path, backup)+want || len(names) != 2 || !slices.Contains(stamps, stamp) {
				t.Fatalf("stdout %q, files %q", out, names)
			}
			kept, _ := os.ReadFile(backup)
			info, err := os.Stat(backup)
			if err != nil || string(kept) != each.given || !info.ModTime().Equal(made) || runtime.GOOS != "windows" && info.Mode() != 0o640 {
				t.Fatalf("backup %q, %v, %v", kept, info, err)
			}
		})
	}
}

// A second run finds it wired and leaves the file as it was, saying so.
func TestASecondRunChangesNothing(t *testing.T) {
	table := table(t)
	if code, _, errOut := install(table); code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	made := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	if err := os.Chtimes(table.Settings, made, made); err != nil {
		t.Fatal(err)
	}
	wired, _ := os.ReadFile(table.Settings)
	code, out, errOut := install(table)
	after, _ := os.ReadFile(table.Settings)
	info, _ := os.Stat(table.Settings)
	names, _ := filepath.Glob(table.Settings + "*")
	if code != 0 || errOut != "" || out != fmt.Sprintf("hooks: %s already runs %s\n", table.Settings, said) ||
		!bytes.Equal(after, wired) || !info.ModTime().Equal(made) || len(names) != 1 {
		t.Fatalf("exit %d, stdout %q, stderr %q, files %q", code, out, errOut, names)
	}
}

// A command that is not a string is no entry of ours, where Python reads its str().
func TestACommandThatIsNoStringIsNotOurs(t *testing.T) {
	table := table(t)
	given := `{"hooks": [{"command": ["seat-state.sh"]}]}`
	if err := os.MkdirAll(filepath.Dir(table.Settings), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(table.Settings, []byte(`{"hooks": {"Stop": [`+given+`]}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if code, _, errOut := install(table); code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	wrote, _ := os.ReadFile(table.Settings)
	data, _ := run.Decode(wrote)
	stop := data.(*run.Object).Dict("hooks").List("Stop")
	if len(stop) != 3 || run.Line(stop[0]) != given {
		t.Fatalf("Stop is %s", run.Line(stop))
	}
}

// A settings directory that cannot be made exits 2, what is in its place left as it was.
func TestADirectoryThatCannotBeMadeExits2(t *testing.T) {
	table := table(t)
	if err := os.WriteFile(filepath.Dir(table.Settings), []byte("acme"), 0o600); err != nil {
		t.Fatal(err)
	}
	code, out, errOut := install(table)
	kept, _ := os.ReadFile(filepath.Dir(table.Settings))
	if code != 2 || out != "" || strings.Count(errOut, "\n") != 1 || string(kept) != "acme" {
		t.Fatalf("exit %d, stdout %q, stderr %q", code, out, errOut)
	}
}

// A file that cannot be read is refused as Python's OSError says it, and left as it was.
func TestAnUnreadableFileIsRefused(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows numbers its errors its own way")
	}
	table := table(t)
	if err := os.MkdirAll(table.Settings, 0o700); err != nil {
		t.Fatal(err)
	}
	code, out, errOut := install(table)
	want := fmt.Sprintf("cannot read %s: [Errno 21] Is a directory: '%s'\n", table.Settings, table.Settings)
	if info, err := os.Stat(table.Settings); code != 1 || out != "" || errOut != want || err != nil || !info.IsDir() {
		t.Fatalf("exit %d, stdout %q, stderr %q", code, out, errOut)
	}
}

// A backup that is the settings file itself, through a link, is refused as copy2 refuses it,
// both left as they were: the backup would otherwise end up holding the rewritten file.
func TestABackupThatIsTheFileIsRefused(t *testing.T) {
	for name, link := range map[string]func(string, string) error{"symbolic": os.Symlink, "hard": os.Link} {
		t.Run(name, func(t *testing.T) {
			table := table(t)
			path, given := table.Settings, "{}"
			backup := path + ".bak-" + time.Now().Format("20060102")
			if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, []byte(given), 0o600); err != nil {
				t.Fatal(err)
			}
			if err := link(path, backup); err != nil {
				t.Skip(err)
			}
			code, out, errOut := install(table)
			kept, _ := os.ReadFile(path)
			backedUp, _ := os.ReadFile(backup)
			want := fmt.Sprintf("'%s' and '%s' are the same file\n", path, backup)
			if code != 1 || out != "" || errOut != want || string(kept) != given || string(backedUp) != given {
				t.Fatalf("exit %d, stdout %q, stderr %q, file %q, backup %q", code, out, errOut, kept, backedUp)
			}
		})
	}
}
