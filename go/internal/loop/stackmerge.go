package loop

import (
	"errors"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// deliveryLock serializes merges in the checked stack's order, Python's merge_lock. File locks
// do not order contenders: a suffix releases the lock until its green prefix has left the line.
func (l *loop) deliveryLock(path string) (held *os.File, err error) {
	waiting := false
	mark := func() error {
		if waiting {
			return nil
		}
		if err := l.save(func(record *run.Object) { record.Set("delivery_wait", os.Getpid()) }); err != nil {
			return err
		}
		waiting = true
		return nil
	}
	defer func() {
		if waiting {
			if unmarked := write(l.dir, func(record *run.Object) { record.Delete("delivery_wait") }); err == nil && unmarked != nil {
				held.Close()
				held, err = nil, unmarked
			}
		}
	}()
	for {
		held, err = lock.Try(path)
		if errors.Is(err, lock.ErrHeld) {
			if err = mark(); err != nil {
				return nil, err
			}
			held, err = lock.Wait(l.ctx, path)
		}
		if err != nil {
			return nil, err
		}
		current, err := read(l)
		if err != nil {
			held.Close()
			return nil, err
		}
		members := lineMembers(filepath.Base(path))
		if !green(current.Dict("waiting_on")) || len(members) == 0 || members[0].dir == l.dir || !green(members[0].record.Dict("waiting_on")) {
			return held, nil
		}
		held.Close()
		held = nil
		if err = mark(); err != nil {
			return nil, err
		}
		if err = l.pause(time.Second); err != nil {
			return nil, err
		}
	}
}
