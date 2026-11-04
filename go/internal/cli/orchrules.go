package cli

import (
	"errors"
	"io"
	"os"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/hooks"
	"agentkit/internal/seat"
)

func init() { commands["orch rules"] = orchRules }

// orchRules says the seat it runs in read the rulebook file its prompt named, under the name it
// was launched with, as its hook reads it.
func orchRules(args []string, out, errOut io.Writer) int {
	known, err := rulebooks.RulebookRead(os.Getenv("AGENTKIT_SESSION"), strings.TrimFunc(args[0], config.Space))
	var refused hooks.RulebookRefusal
	if errors.As(err, &refused) {
		err = seat.Refusal(refused)
	}
	return orchAnswer("orch rules", "rulebook read", known, err, out, errOut)
}
