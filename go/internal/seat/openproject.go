package seat

import "agentkit/internal/gitcall"

// An open reads a project's last fetched rules. Only its first seat needs a fetch;
// an unreachable origin leaves it with the rules available locally, as Python does.
func openingRulebook(name, repo string) (string, error) {
	if repo != "" {
		g := gitcall.Git{Repo: repo, Env: gitcall.ProjectEnv(repo)}
		if ref, _ := g.Try("rev-parse", "--verify", "--quiet", rulesRef); ref == "" {
			if code, _, err := g.Fetch("--quiet", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*"); err == nil && code == 0 {
				g.Try("remote", "set-head", "origin", "--auto")
			}
		}
	}
	return rulebook(name, &repo)
}

// Hold the repository across launch so gc cannot collect it while its harness starts.
func openingCheckout(cwd string) (func(), error) {
	if _, checkout := Common(cwd); !checkout {
		return func() {}, nil
	}
	held, err := gitcall.PrepareCheckout(cwd)
	if err != nil {
		return nil, err
	}
	return func() { held.Close() }, nil
}
