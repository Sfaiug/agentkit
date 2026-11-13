package harness

import "strings"

// OpencodeVariants is adapters/opencode.sh's turn_variants: the layered config document defining
// the variants a launch on model defines itself, which OpenCode merges into the model's own by
// name, and reads only as it starts.  `none`, a model running at no effort, is always defined,
// empty: a model with a `none` of its own keeps its settings, any other runs bare.  MiMo's API
// reads its one reasoning control, `thinking`, only from a variant's `extraBody`, so a `mimo/`
// model's `none` turns it off and its `high` on.  Spliced in unescaped, as the script prints it.
func OpencodeVariants(model string) string {
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
