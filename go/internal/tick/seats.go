package tick

import (
	"cmp"
	"math"
	"math/big"
	"os"
	"slices"
	"strconv"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// every is whether every seat the home holds now is one Go reads, and each reads as ok says.
func every(ok func(seat.Live) bool) func() bool {
	return func() bool {
		lives, known := seat.Lives(time.Now())
		return known && !slices.ContainsFunc(lives, func(live seat.Live) bool { return !ok(live) })
	}
}

// lives is every seat the home holds, read now for a row's step; errLeft where any is one Go does
// not read.
func lives() ([]seat.Live, error) {
	read, known := seat.Lives(time.Now())
	if !known {
		return nil, errLeft
	}
	return read, nil
}

// midturn is whether the seat holds a line its reopening owes it, for a move to another account or
// for anything else (watch.continue_turns).
func midturn(live seat.Live, account bool) bool {
	mark := live.File.Dict("midturn")
	return mark != nil && mark.Truthy("account") == account
}

// healthy is whether the health row's look at the seat is all it does (watch.health): nothing it
// stopped on to type past or ask about, no login to ask after, its pane named, its title its own,
// no notice to answer by its output, and no account to move it to or off.
func healthy(live seat.Live) bool {
	return healthReady(live) && live.Refused == "" && stays(live)
}

// refused is whether the health row's look, and the wait on its usage the refusal its record ends
// on puts it in, are all the row does there (watch.seat_account), which a dry tick says it would.
func refused(live seat.Live) bool { return live.Refused != "" && looked(live) }

// titleKept is whether the seat's title is the name it has, which the owner has not retitled
// (watch.follow_title) and sync_title has nothing to send for: a title it superseded is one it
// names the seat again.
func titleKept(live seat.Live) bool {
	if live.Record.Str("session_title") != live.Name || live.Record.Has("title_sync") {
		return false
	}
	title, _ := live.Title.(string)
	return (title == "" || title == live.Name) && !slices.Contains(live.Record.List("title_superseded"), any(title))
}

// stays is whether watch.seat_account leaves the seat on its account: its provider lists one
// subscription and the seat is on the one it opened on, with room on it, and its harness wrapped no
// turn up for want of any.
func stays(live seat.Live) bool {
	return seat.AccountIdle(live)
}

// health is the seat health row (watch.health): each seat looked at and its word published, as the
// later rows read it, while the look is all the row does there; the first it would do more at ends
// the tick there, before its publish.
func (t *ticking) health() error {
	names, known := seat.Seats(time.Now())
	if !known {
		return errLeft
	}
	for _, name := range names {
		if carried, err := seat.Health(name, func(live seat.Live) bool { return healthReady(live) || refused(live) }, t.log.line); err != nil || !carried {
			return cmp.Or(err, errLeft)
		}
	}
	return nil
}

// stamp is the exit clocks row where every seat is up (orch.stamp): a record not seen within
// seat.SeenEvery, or holding an exit clock, is seen now, its clock gone.
func (t *ticking) stamp() error {
	lives, err := lives()
	if err != nil {
		return err
	}
	now := t.clock().Unix()
	for _, live := range lives {
		err := seat.Update(live.Name, func(record *run.Object) bool {
			seen, dated := run.Num(record.Get("seen"))
			if !record.Truthy("exited_since") && dated && !(float64(now)-seen > seat.SeenEvery) {
				return false
			}
			record.Set("seen", run.Number(strconv.FormatInt(now, 10)))
			record.Delete("exited_since")
			return true
		})
		if err != nil {
			return err
		}
	}
	return stampGone(t.clock())
}

// awake is whether idle sleep leaves the seat be (sleep.tick): it does not rest at its prompt, with
// nobody in it, past its harness's prompt cache, nor while memory may be tight, which Go does not
// read and the tests' `AK_MAX_RUNS=0` turns off as it turns off Python's.
func awake(live seat.Live) bool {
	began, dated := run.Num(live.Began)
	if live.State != "at_prompt" || live.Attached || !dated || began == 0 {
		return true
	}
	if os.Getenv("AK_MAX_RUNS") != "0" {
		return false
	}
	launched, _ := run.Num(live.Record.Get("launched"))
	cache := math.Inf(1)
	block, err := config.Section(live.Own, "sleep")
	switch seconds := block["cache"].(type) {
	case *big.Int:
		cache, _ = new(big.Float).SetInt(seconds).Float64()
	case float64:
		cache = seconds
	}
	return err == nil && !(epoch(time.Now())-max(began, launched) > cache)
}
