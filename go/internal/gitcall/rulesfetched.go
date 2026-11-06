package gitcall

// FetchedRulesTip is the commit rulesRef names in repo as last fetched, "" for none or no repo,
// as Python's config.policy reads it: unlike RulesTip, origin is never asked, and nothing written.
func FetchedRulesTip(repo string) string {
	if repo == "" {
		return ""
	}
	tip, _ := Git{Repo: repo}.Try("rev-parse", "--verify", "--quiet", rulesRef)
	return tip
}
