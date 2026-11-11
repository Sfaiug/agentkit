package helper

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/lock"
)

// Back is what the machine giving back the piece of shard, which ended there with code (Gone),
// does, Python's run_suite: a VM out of memory doubles the MiB its repository's next VMs get
// (least), and one ssh dropped is said, as else a suite the machine lost reads as one it ran.
func (a *Away) Back(shard string, code int, say func(string)) error {
	switch code {
	case short:
		path := filepath.Join(config.Home(), "state", "helper-memory-"+a.repo)
		// suites of one repository's stacks end at once: each reads, raises and replaces it whole
		held, err := lock.Wait(context.Background(), filepath.Join(filepath.Dir(path), "."+filepath.Base(path)+".lock"))
		if err != nil {
			return err
		}
		defer held.Close()
		mb, temp := max(2*a.MemoryMB, least(a.repo)), filepath.Join(filepath.Dir(path), "."+filepath.Base(path)+".tmp")
		if err := os.WriteFile(temp, fmt.Appendf(nil, "%d\n", mb), 0o666); err != nil {
			return err
		}
		if err := os.Rename(temp, path); err != nil {
			return err
		}
		say(fmt.Sprintf("the suite helper's VMs of %d MiB ran out of memory: its next VMs get %d MiB", a.MemoryMB, mb))
	case lost:
		say(fmt.Sprintf("the suite helper %s lost AK_SHARD=%s; it runs again on the first machine with room, this one included", a.Alias, shard))
	}
	return nil
}
