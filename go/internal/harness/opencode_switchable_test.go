package harness

import (
	"os"
	"path/filepath"
	"testing"
)

func TestOpenCodeSwitchesInPlaceOnlyToAVariantNoLaunchDefines(t *testing.T) {
	home, adapters := t.TempDir(), t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	answer := func(script string) {
		t.Helper()
		if err := os.WriteFile(filepath.Join(adapters, "opencode.sh"), []byte("#!/bin/sh\n"+script+"\n"), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	answer(`[ "$1 $2" = "variants acme/m" ] || [ "$1 $2" = "variants acme/m#none" ] || exit 2
printf '{"provider":{"acme":{"models":{"m":{"variants":{"none":{}}}}}}}\n'`)
	for _, each := range []struct {
		model, effort string
		takes         bool
	}{{"acme/m", "high", true}, {"acme/m", "none", false}, {"acme/m#none", "high", false}, {"acme/other", "high", false}} {
		if Switchable("opencode", each.model, each.effort) != each.takes {
			t.Errorf("%s at %s: switchable=%v", each.model, each.effort, !each.takes)
		}
	}
	for _, said := range []string{`echo '{"provider": []}'`, `echo '{"provider":{"acme":{"models":{"m":{}}}}}'`, "echo '{}'",
		`echo '{"provider":{}}'; exit 1`} {
		answer(said)
		if Switchable("opencode", "acme/m", "high") {
			t.Errorf("%s: an answer it cannot read switches in place", said)
		}
	}
	if !Switchable("claude", "acme/m", "none") {
		t.Error("a harness with no say of its own does not switch in place")
	}
}
