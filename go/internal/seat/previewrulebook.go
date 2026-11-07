package seat

// PreviewRulebook is the rulebook a preview of a new seat named `name`, filed under `repo` ("" for
// none), writes, as Python's dry run does: the project's rules as last fetched, since a preview
// fetches nothing, and never those of the project a gone seat's record under the name says.
func PreviewRulebook(name, repo string) (string, error) { return rulebook(name, &repo) }
