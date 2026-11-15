package host

import (
	"os"
	"path/filepath"
	"testing"
)

func TestSliceLineReadsTheSliceElseTheDropInsCeiling(t *testing.T) {
	t.Setenv("AGENTKIT_TMUX_SOCKET", "agentkit")
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
	if got, _ := dropInTasksMax("agentkit-test.slice"); got != 500 {
		t.Errorf("got %v, want 500", got)
	}
}

// The runs building are the runs slice's scopes but a line's check, at the top weight, and none
// once a scope's weight is unread; each reads its time on a CPU and, from its cpu.pressure, its
// time standing still for want of one.  Waiting longer than running holds a start, in tenths.
func TestTheRunsBuildingAndTheirCPU(t *testing.T) {
	runs := t.TempDir()
	scope := filepath.Join(runs, "run.scope")
	for path, text := range map[string]string{
		filepath.Join(scope, "cpu.weight"): "100\n", filepath.Join(runs, "check.scope", "cpu.weight"): "10000\n",
		filepath.Join(scope, "cpu.stat"): "usage_usec 1500\nuser_usec 1000\n",
		filepath.Join(scope, "cpu.pressure"): "some avg10=0.00 avg60=0.00 avg300=0.00 total=900\n" +
			"full avg10=0.00 avg60=0.00 avg300=0.00 total=700\n",
	} {
		os.MkdirAll(filepath.Dir(path), 0o755)
		os.WriteFile(path, []byte(text), 0o644)
	}
	if got := building(runs); len(got) != 1 || got[0] != scope {
		t.Errorf("building: %v", got)
	}
	ran, read := usec(scope)
	stood, stalled := usec(filepath.Join(scope, "cpu.pressure"))
	if ran != 1500 || stood != 700 || !read || !stalled {
		t.Errorf("usec: %v %v, %v %v", ran, read, stood, stalled)
	}
	os.Mkdir(filepath.Join(runs, "unread.scope"), 0o755)
	if got := building(runs); got != nil {
		t.Errorf("building beside an unread weight: %v", got)
	}
	for readings, want := range map[string]string{
		`{"building_cpu_used": 2, "building_cpu_waited": 6.25}`: "waiting for the runs' CPU · 6.2 cores waiting, 2 running",
		`{"building_cpu_used": 6, "building_cpu_waited": 2}`:    "",
		`{"building_cpu_waited": 6}`:                            "",
	} {
		t.Setenv("AK_HOST_READINGS", readings)
		if got, _ := Read().Starved(); got != want {
			t.Errorf("%s: %q", readings, got)
		}
	}
}
