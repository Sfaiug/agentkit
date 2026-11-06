package machines

import (
	"os"
	"path/filepath"
	"testing"
)

// The probe this program carries is tools/machine.sh, byte for byte, so the two cannot drift.
func TestTheCarriedProbeIsToolsMachine(t *testing.T) {
	want, err := os.ReadFile(filepath.Join("..", "..", "..", "tools", "machine.sh"))
	if err != nil || probe != string(want) {
		t.Errorf("go/internal/machines/machine.sh is not tools/machine.sh (%v): copy it over", err)
	}
}
