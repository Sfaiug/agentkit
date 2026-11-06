package config

import (
	"os"
	"strings"
	"testing"
)

// A [defaults] that leaves its orchestrator out takes load()'s, so each change of the weekly audit
// saves, the file's [defaults] still written as it has them; the last reviewer taken out is refused,
// nothing written.
func TestSaveAuditReadsTheDefaultsLoadFillsIn(t *testing.T) {
	path := rememberIn(t, `[defaults]
workers = ["fable"]

[models.fable]
harness = "claude"
model = "claude-fable-5-1"
effort = "xhigh"
provider = "anthropic"

[models.astra]
harness = "codex"
model = "gpt-6-astra"
effort = "high"
provider = "openai"

[providers.anthropic]
mode = "subscription"

[providers.openai]
mode = "subscription"
`)
	for _, change := range []struct {
		key   string
		value any
	}{{"on", false}, {"workers", []string{"fable", "astra"}}, {"reviewers", []string{"astra"}}} {
		if err := SaveAudit(change.key, change.value, noKeep); err != nil {
			t.Fatalf("%s: %v", change.key, err)
		}
	}
	held, on, err := Audit()
	if err != nil || on || strings.Join(held.Workers, " ") != "fable astra" || strings.Join(held.Reviewers, " ") != "astra" {
		t.Fatalf("audit read back as %v %v %v", held, on, err)
	}
	before, _ := os.ReadFile(path)
	if !strings.Contains(string(before), "[defaults]\nworkers = [\"fable\"]\n") {
		t.Fatalf("[defaults] rewritten:\n%s", before)
	}
	if err := SaveAudit("reviewers", []string{}, noKeep); err == nil || !strings.Contains(err.Error(), "[audit].reviewers must name a model") {
		t.Fatalf("the last reviewer taken out: %v", err)
	}
	if after, _ := os.ReadFile(path); string(after) != string(before) {
		t.Fatalf("a refused change wrote:\n%s", after)
	}
}
