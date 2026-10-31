package notify

import (
	"context"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/lock"
)

// Held runs fn holding the seat's typing lock, the one Python ak takes for what it types into a
// seat and writes of it (`notify.session_lock`), with the name the seat goes by now: a rename
// taken while it waited for the lock is followed.  A stop of ctx ends the wait.
func Held(ctx context.Context, name string, fn func(current string) error) error {
	for {
		current, _, err := config.ResolveSession(name)
		if err != nil {
			return err
		}
		path := filepath.Join(config.Home(), "state", "notify-"+current+".lock")
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			return err
		}
		file, err := lock.Wait(ctx, path)
		if err != nil {
			return err
		}
		now, _, err := config.ResolveSession(name)
		if err == nil && now == current {
			defer file.Close()
			return fn(current)
		}
		file.Close()
		if err != nil {
			return err
		}
	}
}
