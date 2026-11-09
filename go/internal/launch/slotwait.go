package launch

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// waitSlot is a run's wait for its slot in its driver, Python's gate.wait_for_slot: a run this
// process does not wait for goes on as it stands; a waiting one polls now, then once a poll
// (slotPoll), asking the decision its launch's first poll asked (decide), and says in its log what holds it,
// once, and, let in after a gate held it, that it waited.  Behind the first in line, which alone
// can be let in, it skips its polls, which are count waits, in its waiter where it has one
// (becomeWaiter).  loop.ErrLeft where Go leaves the wait to Python, nothing of that poll written.
func waitSlot(ctx context.Context, dir string) error {
	poll, _ := slotPoll()
	id := filepath.Base(dir)
	// back from its waiter, it skipped polls, and said what held it before it went
	kind, skipped := "", cameBack()
	announced := skipped
	for polled := false; ; polled = true {
		if polled {
			select {
			case <-ctx.Done():
				return context.Cause(ctx)
			case <-time.After(time.Duration(poll * float64(time.Second))):
			}
			if behindFirst(id, poll) {
				skipped = true
				becomeWaiter(dir)
				continue
			}
		}
		slots, err := holdAdmission(ctx)
		if err != nil {
			return err
		}
		var decided *admission
		var record *run.Object
		err = run.Change(dir, func(waiting *run.Object) error {
			if pid, _ := waiting.Int("pid"); waiting.Str("state") != "queued" || !waiting.Truthy("slot_waiting") || pid != os.Getpid() {
				return nil // let in by its launch, stopped, or another process's: the driver's adoption says
			}
			if !polled {
				kind = waiting.Str("slot_wait_kind") // what held it before this process: its launch
			}
			if skipped {
				run.SetAll(waiting, "slot_waited", true, "slot_wait_kind", "count")
				kind, skipped = "count", false
			}
			var err error
			if decided, err = decide(waiting); err != nil {
				return err
			}
			if decided.leftToPython(waiting) {
				return ErrPython
			}
			decided.settle(waiting)
			record = waiting
			return decided.save()
		})
		slots.Close()
		switch {
		case errors.Is(err, ErrPython):
			return loop.ErrLeft
		case err != nil || decided == nil:
			return err
		case decided.in:
			return waited(dir, record, cmp.Or(kind, "count"))
		}
		kind = cmp.Or(record.Str("slot_wait_kind"), kind)
		if !announced {
			// right after a poll that held it the record's reason is what Python's slot_note says
			fmt.Println(record.Str("slot_wait_reason"))
			announced = true
		}
	}
}

// waited puts first in the run's log that it waited for its slot, where a gate held it, how long,
// and the gate it went past on a stall, and says so: the log's start is the launch's own, and its
// driver writes to it as it goes.
func waited(dir string, record *run.Object, kind string) error {
	if !record.Truthy("slot_waited") {
		return nil
	}
	queued, _ := record.Num("queued_at")
	stall := ""
	if record.Truthy("slot_stall") {
		stall = " · " + record.Str("slot_stall")
	}
	line := fmt.Sprintf("waited %d min for a slot (%s)%s\n", max(0, int((now()-queued)/60)), kind, stall)
	log, err := os.OpenFile(filepath.Join(dir, "log.txt"), os.O_RDWR, 0)
	if err != nil {
		return err
	}
	defer log.Close()
	held, err := io.ReadAll(log)
	if err == nil {
		_, err = log.WriteAt(append([]byte(line), held...), 0)
	}
	fmt.Print(line)
	return err
}

// behindFirst is whether runs/.slots.queue still has the run waiting behind its first, and is not
// yet stale for it, Python's waiter.behind_first: its first polls every poll, and once that stops
// the run next in line comes back after two, the one behind it a poll later, and so on.
func behindFirst(id string, poll float64) bool {
	saved, read := queued()
	place := slices.Index(saved.queue, id)
	age := now() - saved.at
	return read && place > 0 && 0 <= age && age < float64(1+place)*poll
}
