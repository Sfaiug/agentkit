//go:build unix

package config

import (
	"testing"

	"agentkit/internal/lock"
)

// Every edit of config.toml holds ~/.agentkit's flock, Python's policy migration's, from its read
// until the file is replaced, so none writes over another's change or the config.tmp they share.
func TestEditsHoldTheHomeLockThroughRecordPreparation(t *testing.T) {
	rememberIn(t, tickModels)
	ticks, err := OpenModelTicks()
	if err != nil {
		t.Fatal(err)
	}
	for _, edit := range []func(keep func() error) error{
		func(keep func() error) error { return ListAccounts("fuel", []string{"a1"}, keep) },
		func(keep func() error) error {
			return ticks.Tick("acme", "m1", "Model One", []string{"high"}, nil, keep)
		},
	} {
		held := false
		if err := edit(func() error { held = lock.Held(Home()); return nil }); err != nil {
			t.Fatal(err)
		}
		if !held {
			t.Fatal("records prepared without ~/.agentkit's lock")
		}
	}
}
