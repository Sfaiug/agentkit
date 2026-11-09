//go:build unix

package tick

import (
	"bytes"
	"io"
	"path/filepath"
	"testing"
)

// The rented machines row is Go's where googlecloud.Watch carries it: Google's key missing while
// ak may rent is the row's WARN line, in Python's words, a need noted taken first, as Python's
// takes it; and a need noted while ak may not rent is taken.
func TestTheRentedMachinesRowSaysAMissingKeyAndTakesANeed(t *testing.T) {
	ak, _ := idleHome(t, answers)
	config, need := filepath.Join(ak, "config.toml"), filepath.Join(ak, "state", "google-cloud-need")
	idle := read(t, config)
	put(t, config, idle+"[google_cloud]\nactive = true\n")
	put(t, need, "4096\n")
	var out bytes.Buffer
	if !carries(&out, io.Discard) || out.String() != "WARN rented machines did not run: not set up: "+
		"no Google service-account key at ~/.agentkit/secrets/google-cloud.json\n" || !missing(need) {
		t.Errorf("no key: printed %q", out.String())
	}
	put(t, config, idle)
	put(t, need, "4096\n")
	out.Reset()
	if !carries(&out, io.Discard) || out.Len() != 0 || !missing(need) {
		t.Errorf("not renting: printed %q", out.String())
	}
}
