//go:build !windows

package cli

import (
	"bytes"
	"maps"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// `ak plan` settles whether Go makes the done check a finished plan owes before it lists anything
// or writes more than its locks: a run whose words Go does not keep hands the listing over, no turn
// taken.
func TestAPlanOwingACheckPythonMakesHandsOverBeforeAnything(t *testing.T) {
	models := "[defaults]\norchestrator = \"opus\"\n" +
		"[models.opus]\nharness = \"claude\"\nmodel = \"claude-opus-5-5\"\neffort = \"xhigh\"\nprovider = \"anthropic\"\n" +
		"[models.astra]\nharness = \"codex\"\nmodel = \"gpt-6-astra\"\neffort = \"xhigh\"\nprovider = \"openai\"\n" +
		"[providers.anthropic]\nmode = \"subscription\"\n[providers.openai]\nmode = \"subscription\"\n"
	for name, each := range map[string]struct{ config, run string }{
		"a run whose words Go does not keep": {models + "[done_check]\nmodel = \"astra\"\n", `{"launched_session": "acme", "title": "\ud800"}`},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			t.Setenv("AGENTKIT_SESSION", "acme")
			adapters := t.TempDir() // a turn's or a meter's: none is asked
			for _, harness := range []string{"claude", "codex"} {
				write(t, filepath.Join(adapters, harness+".sh"), "#!/bin/sh\nexit 0\n")
				os.Chmod(filepath.Join(adapters, harness+".sh"), 0o700)
			}
			t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
			write(t, filepath.Join(home, ".agentkit", "config.toml"), each.config)
			write(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"),
				`{"orchestrator": "opus", "cwd": "/code/acme", "conversation": "c-review", "reviewers": ["astra"]}`)
			write(t, filepath.Join(home, ".claude", "projects", "-code-acme", "c-review.jsonl"),
				`{"type": "user", "timestamp": "2026-11-05T10:00:00Z", "message": {"role": "user", "content": "Add a retry button."}}`+"\n")
			write(t, filepath.Join(home, ".agentkit", "state", "plan-acme.md"),
				"- [x] The upload page has a retry button · check: `true` · acme · written 2026-11-05 10:05 · done 0123456789ab\n")
			write(t, filepath.Join(home, ".agentkit", "runs", "r-fix", "run.json"), each.run)
			before := tree(t, home)
			var out, errOut bytes.Buffer
			if code := Main([]string{"plan"}, &out, &errOut); code != 3 || out.Len() != 0 || errOut.String() != "ak plan: not implemented in Go yet\n" {
				t.Fatalf("got (%d, %q, %q)", code, out.String(), errOut.String())
			}
			after := tree(t, home)
			for path := range after {
				if _, had := before[path]; !had && strings.HasSuffix(path, ".lock") {
					delete(after, path)
				}
			}
			if !maps.Equal(before, after) {
				t.Fatal("it wrote into HOME")
			}
		})
	}
}
