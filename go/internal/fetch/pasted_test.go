package fetch

import (
	"testing"

	"agentkit/internal/commandhelp"
)

// The `ak fetch` a pasted path's fallback line leaves asks for that path, once its shell has
// read the line.
func TestRetryFetchesThePath(t *testing.T) {
	for _, path := range []string{"/Users/acme/a.pdf", "/Users/acme/owner's report.pdf", `/Users/acme/literal\ space.pdf`,
		`/Users/acme/"a" b\\c.pdf`, "/Users/acme/'quoted'"} {
		words, ok := commandhelp.ShellSplit(retry(path))
		if !ok || len(words) != 3 || words[0] != "ak" || words[1] != "fetch" {
			t.Fatalf("retry(%q) = %q", path, retry(path))
		}
		if got, problem := normalize(words[2]); got != path || problem != "" {
			t.Errorf("retry(%q) = %q asks for %q %s", path, retry(path), got, problem)
		}
	}
}
