//go:build unix

package tick

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

// failedNight is the front matter of a project whose night failed one test, its suite tests.
func failedNight(tests string) string {
	return "---\ntests: " + tests + "\nnightly: printf '%s' '{\"started\":\"night-1\",\"passed\":false,\"failed\":[\"tests/a.py::b\"]}'\n---\n# acme\n"
}

// readNights is one night reads row, what it logged, and its error.
func readNights(t *testing.T, env map[string]string) (string, error) {
	t.Helper()
	for key, value := range env {
		t.Setenv(key, value)
	}
	var out bytes.Buffer
	err := (&ticking{clock: time.Now, log: newLog(&out, io.Discard)}).nights()
	if err != nil && !errors.Is(err, errLeft) {
		t.Fatalf("night read: %v; %s", err, out.String())
	}
	return out.String(), err
}

// A night whose fix Go leaves to Python (its suite narrowed to the change) hands the tick over
// with nothing written: no task, no file of names, no stamp.
func TestANightLeftToPythonWritesNothing(t *testing.T) {
	ak, _ := checkoutHome(t, failedNight("export AK_CHANGED; true"))
	if _, err := readNights(t, map[string]string{"AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_PARENT_RUN": "", "AGENTKIT_RUN_DIR": ""}); !errors.Is(err, errLeft) {
		t.Fatalf("carried it: %v", err)
	}
	if written, _ := filepath.Glob(filepath.Join(ak, "tasks", "*", "night-*")); len(written) > 0 {
		t.Errorf("wrote %v", written)
	}
	if _, err := os.Stat(filepath.Join(ak, "state", "nightly.json")); err == nil {
		t.Error("stamped the night")
	}
}

// A night's fix descends from nothing that made it, whatever run the tick is under: its receipt
// is at depth 0 with no parent, as Python's records a seat launch, refused at its pick or not.
func TestANightFixDescendsFromNothing(t *testing.T) {
	ak, _ := checkoutHome(t, failedNight("true"))
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[defaults]\norchestrator = 'opus'\nworkers = ['opus']\nreviewers = ['opus']\n"+
		"[models.opus]\nharness = 'claude'\nmodel = 'opus'\neffort = 'high'\nprovider = 'acme'\n[providers.acme]\nmode = 'subscription'\n")
	tool := filepath.Join(t.TempDir(), "claude")
	put(t, tool, "#!/bin/sh\nexit 1\n") // signed out: the pick refuses the run, which starts no driver
	if err := os.Chmod(tool, 0o700); err != nil {
		t.Fatal(err)
	}
	said, _ := readNights(t, map[string]string{"AK_RUN_DEPTH": "2", "AK_MAX_RUNS": "0", "AK_PARENT_RUN": "parent-run", "AGENTKIT_RUN_DIR": "",
		"CLAUDE_CONFIG_DIR": "", "CLAUDE_CODE_OAUTH_TOKEN": "", "PATH": filepath.Dir(tool) + string(os.PathListSeparator) + os.Getenv("PATH")})
	found := 0
	for _, dir := range run.Dirs() {
		if record, _ := run.Read(dir); record != nil && record.Truthy("night") {
			found++
			if record.Truthy("run_depth") || record.Get("parent_run") != nil {
				t.Errorf("its receipt took the tick's ancestry: %s", run.Line(record))
			}
		}
	}
	if found != 1 {
		t.Fatalf("%d night runs, logging %q", found, said)
	}
}
