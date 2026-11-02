package harness

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/config"
)

var testServers = []Server{{Name: "browser", URL: "http://localhost:1/mcp"},
	{Name: "desktop", Command: "/usr/bin/python3", Args: []string{"/acme/desktop-mcp.py"}, Env: map[string]string{"XAUTHORITY": "/x", "DISPLAY": ":1"}}}

const testBlock = codexBegin + `
[mcp_servers.browser]
url = "http://localhost:1/mcp"

[mcp_servers.desktop]
command = "/usr/bin/python3"
args = ["/acme/desktop-mcp.py"]
env = { DISPLAY = ":1", XAUTHORITY = "/x" }

` + codexEnd + "\n"

const testClaude = `{"type": "http", "url": "http://localhost:1/mcp"}, "desktop": {"type": "stdio", "command": "/usr/bin/python3", "args": ["/acme/desktop-mcp.py"], "env": {"DISPLAY": ":1", "XAUTHORITY": "/x"}}`

// registered runs one harness's writing on a config holding text, in a fresh HOME; a nil text is
// a config not there.  It answers what it said, why it refused, and what the file holds after.
func registered(t *testing.T, name, file string, text *string) (string, string, string) {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	path := filepath.Join(home, file)
	if text != nil {
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(*text), 0o640); err != nil {
			t.Fatal(err)
		}
	}
	done, err := RegisterMCP(name, testServers)
	why := ""
	if err != nil {
		why = strings.ReplaceAll(err.Error(), path, "PATH")
	}
	after, _ := os.ReadFile(path)
	if entries, _ := os.ReadDir(filepath.Dir(path)); len(entries) > 1 {
		t.Errorf("left beside the config: %v", entries)
	}
	return strings.ReplaceAll(done, path, "PATH"), why, string(after)
}

func TestClaudeWritesWhatPythonWrites(t *testing.T) {
	text := func(s string) *string { return &s }
	whole := `{"browser": ` + testClaude
	for _, c := range []struct {
		name          string
		before        *string
		done, why, to string
	}{
		{"none", nil, "registered in PATH (user scope)", "", `{"mcpServers": ` + whole + "}}\n"},
		{"keeps every key in its place", text(`{"z":1.0,"mcpServers":{"acme":{"a":1},"browser":{"url":"old"}},"y":[null]}`), "registered in PATH (user scope)", "",
			`{"z": 1.0, "mcpServers": {"acme": {"a": 1}, "browser": ` + testClaude + `}, "y": [null]}` + "\n"},
		{"a null keeps its place", text(`{"mcpServers":null,"y":2}`), "registered in PATH (user scope)", "", `{"mcpServers": ` + whole + `}, "y": 2}` + "\n"},
		{"the same in another order", text(`{ "mcpServers":{"desktop":{"env":{"XAUTHORITY":"/x","DISPLAY":":1"},"args":["/acme/desktop-mcp.py"],"command":"/usr/bin/python3","type":"stdio"},"browser":{"url":"http://localhost:1/mcp","type":"http"}}}`),
			"already registered in PATH (user scope)", "", `{ "mcpServers":{"desktop":{"env":{"XAUTHORITY":"/x","DISPLAY":":1"},"args":["/acme/desktop-mcp.py"],"command":"/usr/bin/python3","type":"stdio"},"browser":{"url":"http://localhost:1/mcp","type":"http"}}}`},
		{"not JSON", text("{nope"), "", "PATH: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)", "{nope"},
		{"no object", text("[1]"), "", "PATH: expected a JSON object", "[1]"},
		{"servers no object", text(`{"mcpServers":[]}`), "", "PATH: mcpServers is not an object", `{"mcpServers":[]}`},
	} {
		t.Run(c.name, func(t *testing.T) {
			done, why, after := registered(t, "claude", ".claude.json", c.before)
			if done != c.done || why != c.why || after != c.to {
				t.Errorf("said %q, refused %q, wrote %q\nwanted %q", done, why, after, c.to)
			}
		})
	}
}

func TestCodexWritesWhatPythonWrites(t *testing.T) {
	text := func(s string) *string { return &s }
	stale := codexBegin + "\n[mcp_servers.old]\nurl = \"x\"\n" + codexEnd + "\n"
	half := "half of the agentkit block or more than one"
	for _, c := range []struct {
		name      string
		before    *string
		done, why string
		to        string
		unchanged bool
	}{
		{name: "none", done: "registered in PATH", to: testBlock},
		{name: "after what was written by hand", before: text("# mine\nx = 1\n\n\n"), done: "registered in PATH", to: "# mine\nx = 1\n\n" + testBlock},
		{name: "a stale block in its place", before: text("x = 1\n\n" + stale + "\n\n[t]\ny = 2\n"), done: "registered in PATH", to: "x = 1\n\n" + testBlock + "\n[t]\ny = 2\n"},
		{name: "no byte changes", before: text("c = 1979-05-27T07:32:00+02:00\nn = 5\n\n" + testBlock), done: "already registered in PATH", unchanged: true},
		{name: "line ends read as Python reads them", before: text("x = 1\r\n\r\n" + strings.ReplaceAll(testBlock, "\n", "\r\n")), done: "already registered in PATH", unchanged: true},
		{name: "a comment quoting a marker is no block", before: text("# see " + codexBegin + "\n"), done: "registered in PATH", to: "# see " + codexBegin + "\n\n" + testBlock},
		{name: "not TOML", before: text("x = = 1\n"), why: "PATH is not valid TOML, so nothing was changed: Invalid value (at line 1, column 5)", unchanged: true},
		{name: "half a block", before: text(codexBegin + "\n"), why: half, unchanged: true},
		{name: "two blocks", before: text(strings.Repeat(codexBegin+"\n"+codexEnd+"\n", 2)), why: half, unchanged: true},
		{name: "backwards", before: text(codexEnd + "\n" + codexBegin + "\n"), why: half, unchanged: true},
		{name: "a clash", before: text("[mcp_servers.desktop]\ncommand = \"x\"\n[mcp_servers.browser]\nurl = \"x\"\n"),
			why: "PATH already defines mcp_servers.browser, mcp_servers.desktop outside the agentkit block; remove those tables and run this again", unchanged: true},
		{name: "settings inside the block", before: text(codexBegin + "\nmodel = \"x\"\n" + codexEnd + "\n"), why: "registering would change settings outside the agentkit block", unchanged: true},
		{name: "markers in a string", before: text("x = \"\"\"\n" + codexBegin + "\n" + codexEnd + "\n\"\"\"\n"), why: "PATH: the block did not take effect", unchanged: true},
		{name: "what cannot hold the block", before: text("mcp_servers = 5\n"), why: "the block this would write does not parse: ", unchanged: true},
	} {
		t.Run(c.name, func(t *testing.T) {
			done, why, after := registered(t, "codex", filepath.Join(".codex", "config.toml"), c.before)
			if c.unchanged {
				c.to = *c.before
			}
			if done != c.done || after != c.to || (c.why == "") != (why == "") || !strings.Contains(why, c.why) {
				t.Errorf("said %q, refused %q, wrote %q\nwanted %q", done, why, after, c.to)
			}
			if c.to != "" && c.why == "" {
				if err := config.TOML(after); err != nil {
					t.Error(err)
				}
			}
		})
	}
}

func TestAHarnessWithNoHookWritesNothing(t *testing.T) {
	if done, err := RegisterMCP("muse", testServers); done != "" || err != nil {
		t.Fatalf("%q %v", done, err)
	}
}

func TestWritingKeepsTheModeAndANewFileIsOwnerOnly(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config")
	mode := func() os.FileMode {
		info, err := os.Stat(path)
		if err != nil {
			t.Fatal(err)
		}
		return info.Mode().Perm()
	}
	if err := writeConfig(path, "one"); err != nil {
		t.Fatal(err)
	}
	if mode() != 0o600 {
		t.Fatalf("new file %o", mode())
	}
	if err := os.Chmod(path, 0o640); err != nil {
		t.Fatal(err)
	}
	if err := writeConfig(path, "two"); err != nil {
		t.Fatal(err)
	}
	if data, _ := os.ReadFile(path); mode() != 0o640 || string(data) != "two" {
		t.Fatalf("%o %q", mode(), data)
	}
}

func TestKeptLinesCutWherePythonCuts(t *testing.T) {
	got := keptLines("a\nb c\x0cd\n\ne")
	want := []string{"a\n", "b ", "c\x0c", "d\n", "\n", "e"}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("%q", got)
	}
}
