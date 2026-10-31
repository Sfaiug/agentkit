package harness

import (
	"strings"
	"testing"
)

func TestProjectFolderIsClaudeCodes(t *testing.T) {
	// long names, one ASCII and one of wide characters, named so every gofmt aligns the table alike
	long, wide := strings.Repeat("x", 210), strings.Repeat("\u00e9", 150)+strings.Repeat("\U0001F680", 40)
	for cwd, want := range map[string]string{
		"/home/acme/code/fix-api":         "-home-acme-code-fix-api",
		"/home/acme/caf\u00e9/\U0001F680": "-home-acme-caf----",
		"/home/acme/" + long:              "-home-acme-" + strings.Repeat("x", 189) + "-jum450",
		"/home/acme/" + wide:              "-home-acme-" + strings.Repeat("-", 189) + "-1yrcfo",
	} {
		if got := projectFolder(cwd); got != want {
			t.Fatalf("projectFolder(%q) = %q, want %q", cwd, got, want)
		}
	}
}
