package gitcall

import (
	"context"
	"os"

	"agentkit/internal/lock"
)

// NoAutoGC turns git's own gc off in the checkout: linked worktrees share this config, and a
// turn's detached gc can lock all their HEADs, then leave those locks behind when the worker
// stops its leftover processes.  It holds the lock gc takes on the shared git directory.
func NoAutoGC(repo string) error {
	held, err := PrepareCheckout(repo)
	if err != nil {
		return err
	}
	held.Close()
	return nil
}

// PrepareCheckout disables automatic collection and holds the shared git directory until
// its caller closes the file: preparation waits for gc, and gc skips preparation in progress.
func PrepareCheckout(repo string) (*os.File, error) {
	g := Git{Repo: repo, Env: ProjectEnv(repo)}
	held, err := HoldRepository(g)
	if err != nil {
		return nil, err
	}
	if err := g.NoAutoGC(); err != nil {
		held.Close()
		return nil, err
	}
	return held, nil
}

// HoldRepository takes the shared git directory exclusively, so preparation and branch
// deletion cannot overlap a fetch or collection operating on the same repository.
func HoldRepository(g Git) (*os.File, error) {
	common, err := g.Must("rev-parse", "--path-format=absolute", "--git-common-dir")
	if err != nil {
		return nil, err
	}
	return lock.Wait(context.Background(), common)
}
