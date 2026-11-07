package cli

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"

	"agentkit/internal/config"
)

// A new seat with no --model reads usage to pick its orchestrator.  Every case Go leaves to Python
// is settled before that read, so a home it hands over is as it was; past the read, an adapter that
// is missing, declines or cannot start is an error naming it, as Python's is.
func TestAnOpenPastItsUsageReadNeverHandsOver(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the fake adapters are shell scripts")
	}
	const echo = "[models.acme]\nharness='echo'\nmodel='echo-1'\neffort='low'\nprovider='test'\n[providers.test]\nmode='subscription'\n"
	const meter = `{"meters": [{"name": "weekly", "used": 40, "window_secs": 604800}]}`
	// the rules a seat's rulebook starts from, where `go test` built this program away from them
	rules := filepath.Join(config.Repo(), "orchestrator.md")
	if _, err := os.Stat(rules); err != nil {
		write(t, rules, "the rules\n")
		t.Cleanup(func() { os.Remove(rules) })
	}
	answering := func(interactive string) string {
		return "#!/bin/sh\ncase \"$1\" in usage) echo '" + meter + "' ;; interactive) " + interactive + " ;; esac\n"
	}
	for _, each := range []struct {
		name, config, script string
		said                 string // "" where Go hands the open over
	}{
		{"[defaults] efforts", echo + "[defaults]\nefforts = { acme = { effort = 'high' } }\n", answering("echo /bin/sh"), ""},
		{"no adapter", echo, "", "no adapter for harness 'echo'"},
		{"an adapter that declines", echo, answering("echo refused >&2; exit 1"),
			"the echo adapter's interactive exited 1 without a command for acme: refused"},
		{"a CRLF #! line", echo, strings.ReplaceAll(answering("echo /bin/sh"), "\n", "\r\n"), "interactive could not start"},
		{"no #! line", echo, strings.TrimPrefix(answering("echo /bin/sh"), "#!/bin/sh\n"), "interactive could not start"},
	} {
		for _, preview := range []bool{true, false} {
			t.Run(each.name+map[bool]string{true: ", previewed", false: ", opened"}[preview], func(t *testing.T) {
				if _, err := exec.LookPath("tmux"); err != nil && !preview {
					t.Skip("an open needs tmux")
				}
				home := sandbox(t)
				adapters := filepath.Join(home, "adapters")
				t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
				write(t, filepath.Join(home, ".agentkit", "config.toml"), each.config)
				write(t, filepath.Join(adapters, "echo.toml"), "version = 1\n")
				if each.script != "" {
					write(t, filepath.Join(adapters, "echo.sh"), each.script)
					os.Chmod(filepath.Join(adapters, "echo.sh"), 0o700)
				}
				back, _ := os.Getwd()
				os.Chdir(home)
				t.Cleanup(func() { os.Chdir(back) })
				in, typed, _ := os.Pipe()
				typed.WriteString("\n") // the orchestrator usage picks
				typed.Close()
				stdin := os.Stdin
				os.Stdin = in
				t.Cleanup(func() { os.Stdin = stdin; in.Close() })

				before := tree(t, home)
				var out, errOut bytes.Buffer
				code := orchNew("crew", map[string]string{"--workers": "acme"}, preview, &out, &errOut)
				_, read := os.Stat(filepath.Join(home, ".agentkit", "state", "usage.json"))
				if each.said == "" {
					if code != 3 || !reflect.DeepEqual(before, tree(t, home)) {
						t.Fatalf("got %d (%q), home changed: %v; want a hand-over leaving it as it was", code, errOut.String(),
							!reflect.DeepEqual(before, tree(t, home)))
					}
					return
				}
				if code != 2 || !strings.HasPrefix(errOut.String(), "ak orch: ") || !strings.Contains(errOut.String(), each.said) || read != nil {
					t.Fatalf("got %d (%q), usage read: %v; want an error past the usage read saying %q", code, errOut.String(), read == nil, each.said)
				}
			})
		}
	}
}
