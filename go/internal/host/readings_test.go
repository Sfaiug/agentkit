package host

import (
	"os"
	"path/filepath"
	"testing"
)

func TestSliceLineReadsTheSliceElseTheDropInsCeiling(t *testing.T) {
	t.Setenv("AGENTKIT_TMUX_SOCKET", "")
	for _, c := range []struct {
		current, max string
		dropIn       float64
		want         string
	}{
		{"", "", 0, "slice agentkit.slice · 0 tasks · no ceiling set"},
		{"", "", 400, "slice agentkit.slice · 0 tasks · 0% of its ceiling"},
		{"", "200", 0, "slice agentkit.slice · 0 tasks · no ceiling set"},
		{"1", "max", 400, "slice agentkit.slice · 1 task · 0% of its ceiling"},
		{"5", "200", 400, "slice agentkit.slice · 5 tasks · 2% of its ceiling"}, // 2.5 rounds to even
	} {
		cgroup := t.TempDir()
		for name, value := range map[string]string{"pids.current": c.current, "pids.max": c.max} {
			if value != "" {
				os.WriteFile(filepath.Join(cgroup, name), []byte(value+"\n"), 0o644)
			}
		}
		if got := sliceLine(cgroup, c.dropIn); got != c.want {
			t.Errorf("%+v: got %q", c, got)
		}
	}
}

func TestTheLastDropInNamingTasksMaxWins(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("AGENTKIT_TMUX_SOCKET", "agentkit-test")
	for base, text := range map[string]string{"user": "TasksMax=300\n", "user.control": "[Slice]\nTasksMax = 500\nTasksMax=max\n"} {
		dir := filepath.Join(os.Getenv("XDG_CONFIG_HOME"), "systemd", base, "agentkit-test.slice.d")
		os.MkdirAll(dir, 0o755)
		os.WriteFile(filepath.Join(dir, "50-limits.conf"), []byte(text), 0o644)
	}
	if got := sliceCeiling(); got != 500 {
		t.Errorf("got %v, want 500", got)
	}
}
