package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// Pictures `ak orch check` cannot read leave the seat unchecked, exit 2, even where its owner
// said nothing, as Python's check reads them with its other records.
func TestOrchCheckReadsThePicturesWhateverTheOwnerSaid(t *testing.T) {
	home := sandbox(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.opus]\nharness = \"claude\"\n"+
		"model = \"claude-opus-5-5\"\neffort = \"xhigh\"\nprovider = \"anthropic\"\n"+
		"[providers.anthropic]\nmode = \"subscription\"\n")
	write(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"),
		`{"orchestrator": "opus", "cwd": "/code/acme", "conversation": "c-review"}`)
	write(t, filepath.Join(home, ".claude", "projects", "-code-acme", "c-review.jsonl"),
		`{"type": "assistant", "timestamp": "2026-11-05T10:00:00Z", "message": {"role": "assistant", "content": "Ready."}}`+"\n")
	if err := os.Mkdir(filepath.Join(home, ".agentkit", "state", "pictures-acme.jsonl"), 0o700); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	if code := Main([]string{"orch", "check", "acme"}, &out, &errOut); code != 2 {
		t.Fatalf("exit %d, want 2: %q %q", code, out.String(), errOut.String())
	}
}
