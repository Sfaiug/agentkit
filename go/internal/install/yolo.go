package install

import (
	"fmt"
	"io"

	"agentkit/internal/config"
	"agentkit/internal/harness"
)

// yolo merges ak's yolo defaults into each harness's own settings on the server, as install.sh
// does after the rulebook; a file one cannot merge is left as it is, said, and the install goes on.
func yolo(out, errOut io.Writer) error {
	names, err := config.ManifestNames()
	if err != nil {
		return err
	}
	for _, name := range names {
		if err := harness.Yolo(name, out); err != nil {
			fmt.Fprintf(errOut, "note: %v; %s's yolo defaults are yours to set\n", err, name)
		}
	}
	return nil
}
