package tick

import (
	"cmp"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/notify"
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

// refused is whether the health row's look, and the wait on its usage the refusal its record ends
// on puts it in, are all the row does there (watch.seat_account), which a dry tick says it would.
func refused(live seat.Live) bool { return live.Refused != "" && looked(live) }

// titleKept is whether the seat's title is the name it has, which the owner has not retitled
// (watch.follow_title) and sync_title has nothing to send for: a title it superseded is one it
// names the seat again.  A harness that takes no title, reading none, has none to follow or send,
// where title_record retires no title sends of an earlier conversation.
func titleKept(live seat.Live) bool {
	if harness.Untitled(live.Own) && live.Title == nil {
		return !live.Record.Has("title_conversation") || run.Equal(live.Record.Get("title_conversation"), live.Record.Get("conversation"))
	}
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

// health is the seat health row (watch.health): the worker tokens polled, then each seat looked at
// and its word published, as the later rows read it, while the look is all the row does there, or
// keeps the stall its screen shows short of typing past it, asking its owner about one an hour old
// and nothing more after; the first it would do more at ends the tick there, before its publish.
// A stall held of a seat whose record is gone is Python's to forget.  A dry tick's look acts on
// nothing and says what it would type.
func (t *ticking) health() error {
	if err := t.pollTokens(); err != nil {
		return err
	}
	names, known := seat.Seats(time.Now())
	stalls := t.state.Dict("stalls")
	if !known || slices.ContainsFunc(stalls.Keys(), func(name string) bool { return missing(statePath("session-" + name + ".json")) }) {
		return errLeft
	}
	for _, name := range names {
		var kept *run.Object
		owner, line := "", ""
		carried, err := seat.Health(name, func(live seat.Live) bool {
			held, _ := stalls.Get(live.Name).(*run.Object)
			if held != nil && held.Truthy("told") {
				return asked(live)
			}
			if !stalling(live) {
				return held == nil && (healthReady(live) || refused(live))
			}
			var keeps bool
			kept, line, keeps = seat.KeepStall(live, held, epoch(time.Now()))
			owner = live.Name
			return keeps
		}, t.log.line, t.dry)
		if err != nil || !carried {
			return cmp.Or(err, errLeft)
		}
		if kept != nil {
			stalls.Set(owner, kept)
		}
		if line != "" {
			t.log.line(line)
		}
	}
	return nil
}

// stalling is whether the health row's look at the seat finds a stall it keeps without typing
// (watch.health): one on a screen it reads, its own login fine and no notice standing, on the
// account it stays on, where the row's catch-all takes it.
func stalling(live seat.Live) bool {
	return live.Stall != nil && live.Login == nil && looked(live) && notify.Last(live.Name) == nil && live.Refused == "" &&
		stays(live) && strings.TrimFunc(live.Pane, config.Space) != ""
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
