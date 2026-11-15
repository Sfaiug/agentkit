package harness

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"regexp"
	"strings"

	"agentkit/internal/config"
)

func init() {
	verbs["grokbuild models"] = grokbuildModels
}

// grokID is a model id as `grok models` lists one.
var grokID = regexp.MustCompile(`^[A-Za-z0-9._/-]+$`)

// grokbuildModels is adapters/grokbuild.sh's `models`, on the login $AGENTKIT_ACCOUNT names: `grok
// models` names the models it runs (`  * grok-4.7 (default)`, `  - grok-4.6`) and no effort, so
// each takes the efforts the [catalog] table gives it, and one the table does not know goes
// unsaid.  1 where the listing fails or names nothing: config.catalog decides what stands in.
func grokbuildModels(_ []string, out, errOut io.Writer) int {
	login, _, err := config.Account("grokbuild")
	if err != nil {
		fmt.Fprintf(errOut, "ak adapter: %s\n", err)
		return 1
	}
	listing := exec.Command(Binary("grok"), "models")
	listing.Env = login.Environ(os.Environ())
	said, err := listing.Output()
	var rows [][]string
	for _, line := range strings.Split(string(said), "\n") {
		// as awk splits a line: at runs of blanks, none leading
		fields := strings.FieldsFunc(line, func(r rune) bool { return r == ' ' || r == '\t' })
		if len(fields) >= 2 && (fields[0] == "*" || fields[0] == "-") && grokID.MatchString(fields[1]) {
			rows = append(rows, []string{fields[1], "", ""})
		}
	}
	if err != nil || len(rows) == 0 {
		return 1
	}
	catalogued(out, "grokbuild", rows)
	return 0
}
