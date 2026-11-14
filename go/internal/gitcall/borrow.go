package gitcall

// CloneBorrowing clones g's checkout to target borrowing its objects, for one check, Python's
// gitcall.clone_borrowing.  It says which repository it is, as nothing else about it does: under
// names of their own, 169 clones each sent one machine the whole history until its memory was
// full (2 Nov 2026), and measured their suites afresh.
func (g Git) CloneBorrowing(target string, how ...string) error {
	if _, err := g.Must(append(append([]string{"clone", "--quiet", "--shared"}, how...), g.Repo, target)...); err != nil {
		return err
	}
	clone := g
	clone.Repo = target
	_, err := clone.Must("config", "ak.repository", RepositoryID(g.Repo))
	return err
}
