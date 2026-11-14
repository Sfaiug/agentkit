//go:build !windows

package cli

import (
	"bytes"
	"maps"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// A record `ak orch check` cannot read leaves the seat unchecked, exit 2, forgetting what an
// earlier check kept, and a case Python carries is handed over, exit 3, writing nothing: either
// before any model's turn, the pick's meters or the turn's folders are written.
func TestOrchCheckReadsEveryRecordBeforeItWritesAnything(t *testing.T) {
	config := func(extra string) string {
		return "[defaults]\norchestrator = \"opus\"\n" +
			"[models.opus]\nharness = \"claude\"\nmodel = \"claude-opus-5-5\"\neffort = \"xhigh\"\nprovider = \"anthropic\"\n" +
			"[models.astra]\nharness = \"codex\"\nmodel = \"gpt-6-astra\"\neffort = \"xhigh\"\nprovider = \"openai\"\n" +
			"[providers.anthropic]\nmode = \"subscription\"\n[providers.openai]\nmode = \"subscription\"\n" + extra
	}
	explicit := config("[done_check]\nmodel = \"astra\"\n")
	for _, each := range []struct {
		name, config string
		code         int
		said         string // the start of what it says
		// writes what the case reads, and names a folder it may not enter while it runs
		make func(t *testing.T, home string) (hidden string)
	}{
		{"typing receipts it cannot read", explicit, 2, "ak orch: could not check acme: ", func(t *testing.T, home string) string {
			if err := os.MkdirAll(filepath.Join(home, ".agentkit", "state", "input-acme.jsonl"), 0o700); err != nil {
				t.Fatal(err)
			}
			return ""
		}},
		{"a task it cannot tell is there", explicit, 2, "ak orch: could not check acme: ", func(t *testing.T, home string) string {
			write(t, filepath.Join(home, ".agentkit", "runs", "r-fix", "run.json"), `{"launched_session": "acme"}`)
			hidden := t.TempDir()
			write(t, filepath.Join(hidden, "task.md"), "Add a retry button.\n")
			if err := os.Symlink(filepath.Join(hidden, "task.md"), filepath.Join(home, ".agentkit", "runs", "r-fix", "task.md")); err != nil {
				t.Fatal(err)
			}
			return hidden
		}},
		{"a run's launching seat it cannot read", explicit, 2, "ak orch: " + filepath.Join("HOME", ".agentkit", "state", "session-old.json") + ": ", func(t *testing.T, home string) string {
			write(t, filepath.Join(home, ".agentkit", "runs", "r-fix", "run.json"), `{"launched_session": "old"}`)
			write(t, filepath.Join(home, ".agentkit", "state", "session-old.json"), "not JSON")
			return ""
		}},
		{"a run whose words Go does not keep", explicit, 3, "ak orch check: not implemented in Go yet\n", func(t *testing.T, home string) string {
			write(t, filepath.Join(home, ".agentkit", "runs", "r-fix", "run.json"), `{"launched_session": "acme", "title": "\ud800"}`)
			return ""
		}},
		{"a picture whose name Go does not keep", explicit, 3, "ak orch check: not implemented in Go yet\n", func(t *testing.T, home string) string {
			write(t, filepath.Join(home, ".agentkit", "state", "pictures-acme.jsonl"), `{"at": 1793872800, "name": "shot-\udcff.png", "data": "aGVsbG8="}`+"\n")
			return ""
		}},
	} {
		t.Run(each.name, func(t *testing.T) {
			home := sandbox(t)
			adapters := t.TempDir() // a turn's or a meter's: none is asked
			for _, harness := range []string{"claude", "codex"} {
				if err := os.WriteFile(filepath.Join(adapters, harness+".sh"), []byte("#!/bin/sh\nexit 0\n"), 0o700); err != nil {
					t.Fatal(err)
				}
			}
			t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
			write(t, filepath.Join(home, ".agentkit", "config.toml"), each.config)
			write(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"),
				`{"orchestrator": "opus", "cwd": "/code/acme", "conversation": "c-review", "reviewers": ["astra"]}`)
			write(t, filepath.Join(home, ".claude", "projects", "-code-acme", "c-review.jsonl"),
				`{"type": "user", "timestamp": "2026-11-05T10:00:00Z", "message": {"role": "user", "content": "Add a retry button."}}`+"\n")
			checked := filepath.Join(home, ".agentkit", "state", "checked-acme.txt")
			write(t, checked, "an earlier check's\n")
			hidden := each.make(t, home)
			before := tree(t, home)
			if hidden != "" {
				if os.Chmod(hidden, 0) != nil {
					t.Fatal(hidden)
				}
				t.Cleanup(func() { os.Chmod(hidden, 0o700) })
				if _, err := os.Stat(filepath.Join(hidden, "task.md")); err == nil {
					t.Skip("a folder of no access is entered anyway here")
				}
			}
			var out, errOut bytes.Buffer
			code := Main([]string{"orch", "check", "acme"}, &out, &errOut)
			if hidden != "" {
				os.Chmod(hidden, 0o700) // so the tree reads through the link as before
			}
			said := strings.ReplaceAll(each.said, "HOME", home)
			if code != each.code || out.Len() != 0 || !strings.HasPrefix(errOut.String(), said) {
				t.Fatalf("got (%d, %q, %q), want (%d, \"\", %q...)", code, out.String(), errOut.String(), each.code, said)
			}
			after, want := tree(t, home), maps.Clone(before)
			if each.code == 2 { // under the seat's lock, in ak's folders
				delete(want, checked)
				for path, text := range after {
					if _, had := before[path]; !had && (text == "directory" || strings.HasSuffix(path, ".lock")) {
						delete(after, path)
					}
				}
			}
			if !reflect.DeepEqual(want, after) {
				t.Fatal("it wrote into HOME")
			}
		})
	}
}
