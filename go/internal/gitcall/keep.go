package gitcall

// NoAutoGC turns off git's background maintenance, whose locks could outlive a stopped turn.
// The caller holds the repository lock through preparation and launch.
func (g Git) NoAutoGC() error {
	for _, setting := range [][2]string{{"gc.auto", "0"}, {"maintenance.auto", "false"}} {
		said, err := g.Try("config", "--local", "--get", setting[0])
		if err != nil {
			return err
		}
		if said != setting[1] {
			if _, err := g.Must("config", "--local", "--replace-all", setting[0], setting[1]); err != nil {
				return err
			}
		}
		if said, err = g.Try("config", "--get", setting[0]); err != nil {
			return err
		}
		if said != setting[1] {
			if _, err := g.Must("config", "--worktree", "--replace-all", setting[0], setting[1]); err != nil {
				return err
			}
		}
	}
	return nil
}
