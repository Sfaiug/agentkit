package gitcall

// IntegratedBase is the newest commit of upstream the checkout's HEAD took in, never behind base,
// Python's integrated_base: base where it took in none newer.
func IntegratedBase(g Git, base, upstream string) (string, error) {
	code, fork, err := g.Out("merge-base", "HEAD", upstream)
	if err != nil || code != 0 || fork == "" || fork == base {
		return base, err
	}
	code, _, err = g.Out("merge-base", "--is-ancestor", base, fork)
	if err != nil || code != 0 {
		return base, err
	}
	return fork, nil
}
