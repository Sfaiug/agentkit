package harness

import (
	"fmt"
	"io"
	"os"
	"strings"
)

func init() {
	verbs["opencode variants"] = opencodeVariantsVerb
}

// opencodeVariantsVerb is adapters/opencode.sh's `variants <model>`: the document opencodeVariants
// writes, for a move to a variant it defines to restart.  A named account is refused first, as that
// script refuses one for every verb.
func opencodeVariantsVerb(args []string, out, errOut io.Writer) int {
	if account := os.Getenv("AGENTKIT_ACCOUNT"); account != "" {
		fmt.Fprintf(errOut, "opencode: account %s refused; OpenCode keeps logins and sessions in one opencode.db, so a login of its own cannot resume a conversation\n", account)
		return 1
	}
	if len(args) < 1 {
		fmt.Fprintln(errOut, "opencode.sh variants needs <model>")
		return 2
	}
	fmt.Fprintln(out, opencodeVariants(args[0]))
	return 0
}

// opencodeVariants is adapters/opencode.sh's turn_variants: the layered config document defining
// the variants a launch on model defines itself, which OpenCode merges into the model's own by
// name, and reads only as it starts.  `none`, a model running at no effort, is always defined,
// empty: a model with a `none` of its own keeps its settings, any other runs bare.  MiMo's API
// reads its one reasoning control, `thinking`, only from a variant's `extraBody`, so a `mimo/`
// model's `none` turns it off and its `high` on.  Spliced in unescaped, as the script prints it.
func opencodeVariants(model string) string {
	provider, id, cut := strings.Cut(model, "/")
	if !cut {
		id = model
	}
	id, _, _ = strings.Cut(id, "#")
	variants := `"none":{}`
	if provider == "mimo" {
		variants = `"none":{"extraBody":{"thinking":{"type":"disabled"}}},"high":{"extraBody":{"thinking":{"type":"enabled"}}}`
	}
	return `{"provider":{"` + provider + `":{"models":{"` + id + `":{"variants":{` + variants + `}}}}}}`
}
