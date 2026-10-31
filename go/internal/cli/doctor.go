package cli

import (
	"fmt"
	"io"

	"agentkit/internal/config"
)

func init() { commands["doctor"] = doctor }

// doctor refuses a manifest that is not TOML, as Python's does once it reads the config; the
// rest is Python's.  Python reports on the host first, which Go does not yet, so Go refuses
// without that report only what no real home holds: the manifests Go ships always read, and a
// broken one comes only from $AGENTKIT_ADAPTER_DIR.  A config.toml Python refuses is refused
// there, after its report.
func doctor(_ []string, _, errOut io.Writer) int {
	if err := config.Manifests(); err != nil {
		fmt.Fprintf(errOut, "ak doctor: %s\n", err)
		return 2
	}
	return notImplemented(errOut, "doctor")
}
