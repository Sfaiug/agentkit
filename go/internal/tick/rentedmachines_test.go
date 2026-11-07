package tick

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"testing"
)

// The rented machines row is Go's where googlecloud.Watch carries it: a need noted while ak may
// rent ends the tick there, untouched; Google's key missing while it may is the row's WARN line,
// in Python's words; and a need noted while it may not is taken.
func TestTheRentedMachinesRowLeavesARentToPython(t *testing.T) {
	ak, _ := idleHome(t, answers)
	config, need := filepath.Join(ak, "config.toml"), filepath.Join(ak, "state", "google-cloud-need")
	idle := read(t, config)
	put(t, config, idle+"[google_cloud]\nactive = true\n")
	put(t, need, "4096\n")
	endedThere(t, ak, "")
	if got := read(t, need); got != "4096\n" {
		t.Errorf("the need holds %q", got)
	}
	os.Remove(need)
	var out bytes.Buffer
	if !carries(&out, io.Discard) || out.String() != "WARN rented machines did not run: not set up: "+
		"no Google service-account key at ~/.agentkit/secrets/google-cloud.json\n" {
		t.Errorf("no key: printed %q", out.String())
	}
	put(t, config, idle)
	put(t, need, "4096\n")
	out.Reset()
	if !carries(&out, io.Discard) || out.Len() != 0 || !missing(need) {
		t.Errorf("not renting: printed %q", out.String())
	}
}
