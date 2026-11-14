//go:build unix

package tick

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/harness"
)

// namingHome is a home whose seat acme's Claude transcript is written, beside a seat beta of that
// record, and the name ak gives acme's transcript.
func namingHome(t *testing.T, beta map[string]any) string {
	t.Helper()
	ak, _ := idleHome(t, "")
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non=false\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[models.agy]\nharness='antigravity'\nmodel='agy'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	acme := map[string]any{"orchestrator": "opus", "conversation": "conv-acme", "cwd": t.TempDir()}
	for name, record := range map[string]map[string]any{"acme": acme, "beta": beta} {
		data, _ := json.Marshal(record)
		put(t, filepath.Join(ak, "state", "session-"+name+".json"), string(data))
	}
	names, _ := harness.ReadBy("claude", acme)
	put(t, names[0], `{"type":"user","message":{"role":"user","content":"Add a retry button."}}`+"\n")
	return names[1]
}

// A seat whose conversation Go leaves to Python to name hands the row over before any seat's
// transcript is given its name.
func TestConversationNamesHandOverBeforeKeepingAny(t *testing.T) {
	kept := namingHome(t, map[string]any{"orchestrator": "agy", "conversation": "conv-beta", "id_source": "antigravity-hook", "cwd": t.TempDir()})
	if err := keepConversations(); !errors.Is(err, errLeft) {
		t.Fatalf("the row ended on %v", err)
	}
	if _, err := os.Stat(kept); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("acme's transcript was kept: %v", err)
	}
}

// A seat whose `left` Python's pass raises on ends the row on Python's error, the seats before it
// given their names.
func TestConversationNamesEndOnWhatPythonRaises(t *testing.T) {
	kept := namingHome(t, map[string]any{"orchestrator": "opus", "conversation": "conv-beta", "cwd": t.TempDir(), "left": 42})
	if err := keepConversations(); err == nil || err.Error() != "'int' object is not iterable" {
		t.Fatalf("the row ended on %v", err)
	}
	if _, err := os.Stat(kept); err != nil {
		t.Fatalf("acme's transcript was not kept: %v", err)
	}
}
