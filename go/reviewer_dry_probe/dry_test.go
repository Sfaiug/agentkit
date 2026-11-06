//go:build unix

package dryprobe

import (
	"bytes"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
	"agentkit/internal/tick"
	"agentkit/internal/tmux"
)

func put(t *testing.T, path, data string, mode fs.FileMode) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(data), mode); err != nil {
		t.Fatal(err)
	}
}

func tree(t *testing.T, root string) map[string]string {
	t.Helper()
	got := map[string]string{}
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		got[path] = ""
		if !entry.IsDir() {
			data, err := os.ReadFile(path)
			got[path] = string(data)
			return err
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return got
}

func TestDryDoesNotCollectAccountUsage(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Fatal(err)
	}
	for _, snapshot := range []string{"missing", "stale"} {
		for _, used := range []int{10, 100} {
			t.Run(fmt.Sprintf("%s/%d", snapshot, used), func(t *testing.T) {
				home := t.TempDir()
				sockets, err := os.MkdirTemp("", "dryprobe-")
				if err != nil {
					t.Fatal(err)
				}
				t.Cleanup(func() { os.RemoveAll(sockets) })
				ak, bin := filepath.Join(home, ".agentkit"), filepath.Join(home, "bin")
				for key, value := range map[string]string{
					"HOME": home, "USERPROFILE": home, "TMUX_TMPDIR": sockets, "AGENTKIT_TMUX_SOCKET": "dryprobe",
					"AGENTKIT_SESSION": "", "AGENTKIT_ADAPTER_DIR": bin, "XDG_RUNTIME_DIR": t.TempDir(), "XDG_CONFIG_HOME": "",
					"AK_NOTIFY_SINK": "dry-run", "AK_RUN_ROLE": "", "PATH": bin + string(os.PathListSeparator) + os.Getenv("PATH"),
				} {
					t.Setenv(key, value)
				}
				put(t, filepath.Join(bin, "gh"), "#!/bin/sh\necho 'To get started, please run: gh auth login' >&2\nexit 4\n", 0o700)
				put(t, filepath.Join(bin, "antigravity.sh"), fmt.Sprintf("#!/bin/sh\n[ \"$1\" = usage ] || exit 1\nused=10\n[ \"${AGENTKIT_ACCOUNT:-default}\" != default ] || used=%d\nprintf '{\"meters\":[{\"name\":\"session\",\"used\":%%s,\"window_secs\":18000,\"resets_at\":2000000000}]}\\n' \"$used\"\n", used), 0o700)
				put(t, filepath.Join(ak, "config.toml"), "[audit]\non=false\n[models.gemini]\nharness='antigravity'\nmodel='gemini'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\naccounts=['default','second']\n", 0o600)
				put(t, filepath.Join(ak, "state", "gc.json"), run.Line(run.Fields("started_at", time.Now().Unix())), 0o600)
				put(t, filepath.Join(ak, "state", "session-acme.json"), run.Line(run.Fields("orchestrator", "gemini", "workers", []any{"gemini"}, "cwd", filepath.Join(home, "work", "acme"), "created", 1799000000, "conversation", "conv-acme", "id_source", "launcher", "resumable", true, "session_title", "acme")), 0o600)
				if snapshot == "stale" {
					meter := run.Fields("meters", []any{run.Fields("name", "session", "used", used, "window_secs", 18000, "resets_at", 2000000000)})
					put(t, filepath.Join(ak, "state", "usage.json"), run.Line(run.Fields("fetched_at", time.Now().Unix()-600, "providers", run.Fields("test", run.Fields("accounts", run.Fields("default", meter, "second", meter))))), 0o600)
				}
				rule := strings.Repeat("─", 40)
				put(t, filepath.Join(home, "screen"), "The patch is ready.\n"+rule+"\n>\n"+rule+"\n● [12:08:46] sleep 45 running\n"+rule+"\n? for shortcuts              agentkit (GPT-OSS 120B (Medium))  /agents · 1 task(s) · /tasks\n", 0o600)
				t.Cleanup(func() { tmux.Ask(tmux.Own(), "kill-server") })
				if err := tmux.Spawn(tmux.Own(), os.Getenv("PATH"), "new-session", "-d", "-s", "acme", "-x", "80", "-y", "24", "sh", "-c", "cat \"$HOME/screen\"; read _"); err != nil {
					t.Fatal(err)
				}
				pane, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "=acme:", "#{pane_id}")
				if err != nil {
					t.Fatal(err)
				}
				tmux.Ask(tmux.Own(), "set-option", "-t", "=acme:", tmux.Mark, "1")
				tmux.Ask(tmux.Own(), "set-option", "-t", "=acme:", tmux.HarnessPane, pane)
				for deadline := time.Now().Add(10 * time.Second); ; time.Sleep(10 * time.Millisecond) {
					shown, _ := tmux.Ask(tmux.Own(), "capture-pane", "-p", "-t", pane)
					if strings.Contains(shown, "The patch is ready.") {
						break
					}
					if time.Now().After(deadline) {
						t.Fatalf("never drew screen: %q", shown)
					}
				}
				before := tree(t, home)
				var out bytes.Buffer
				carried := tick.Dry(&out)
				after := tree(t, home)
				if !reflect.DeepEqual(after, before) {
					for path, value := range after {
						if old, exists := before[path]; !exists || old != value {
							t.Errorf("Dry changed %s (carried=%v)", strings.TrimPrefix(path, home), carried)
						}
					}
				}
			})
		}
	}
}
