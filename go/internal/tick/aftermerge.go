package tick

import (
	"cmp"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/handback"
	"agentkit/internal/history"
	"agentkit/internal/lock"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// breaks is the rest of after_merge_checks for one repository: its oldest failing merge after the
// newest passing one is handed back to fix, once.  The break is kept in watch.json until a seat
// at its prompt is told it, however long past its window, with its composer mark, so a line whose
// Enter did not land gets its Enter and is never typed twice; one told stays told until a later
// merge passes, or no red is left.  A dry tick writes no run and types nothing: it says the break
// it would hand back.
func (t *ticking) breaks(key string, merges []*merge, now float64) error {
	episodes := t.state.Dict("after_merge")
	var expired []string
	for _, each := range merges {
		if each.verdict == "failed" && !inWindow(each.record, now) && !t.dry {
			expired = append(expired, each.name)
		}
	}
	// once the episode owns the evidence, a probe past its window needs no more following
	closeHealth := func() error {
		for _, name := range expired {
			err := run.Change(filepath.Join(run.Runs(), name), func(current *run.Object) error {
				if !current.Truthy("live_at") { // without its failure, an earlier live_at ends the episode as a pass
					current.Delete("health")
				}
				return nil
			})
			if err != nil {
				return err
			}
		}
		return nil
	}
	episode, stored := episodes.Get(key).(*run.Object)
	switch kept := episodes.Get(key).(type) {
	case string:
		episode, stored = run.NewObject(), true
		if kept != "" {
			episode.Set("notified", kept)
		}
		episodes.Set(key, episode)
	case *run.Object:
	default:
		if kept != nil {
			episodes.Delete(key)
		}
		episode = run.NewObject()
	}
	if notified := episode.Str("notified"); notified != "" {
		ended, ok := dated(episode, "finished")
		if !ok {
			ended, ok = run.Num(episode.Get("at"))
		}
		last := -1
		for i, each := range merges {
			if each.sha == notified {
				last = i
			}
		}
		switch {
		case last >= 0:
			// its own re-run going green ends it too, so a later break gets told
			if !slices.ContainsFunc(merges[last:], func(each *merge) bool { return each.verdict == "passed" }) {
				return closeHealth()
			}
		case !ok, slices.ContainsFunc(merges, func(each *merge) bool { return each.verdict == "passed" && each.finished > ended }),
			!slices.ContainsFunc(merges, func(each *merge) bool { return slices.Contains([]string{"failed", "pending", "unknown"}, each.verdict) }):
		default:
			return closeHealth()
		}
		episodes.Delete(key)
		episode, stored = run.NewObject(), false
	}
	pending := episode.Dict("pending")
	if pending != nil {
		finished, ok := dated(pending, "finished")
		switch {
		case pending.Str("source") != "health" || pending.Str("line") == "" || pending.Str("sha") == "" || !ok || pending.Str("run") == "":
			// a line typed before is finished before its receipt goes
			if mark := pending.Dict("typed"); mark != nil && mark.Truthy("line") && !t.dry {
				if name := marked(seat.Up(), mark); name != "" {
					switch handback.Tell(name, mark.Str("line"), mark, func(*run.Object) error { return nil }, t.log.line) {
					case "":
						return errLeft
					case handback.Sent:
					default:
						return nil
					}
				}
			}
			episode.Delete("pending")
			if len(episode.Keys()) == 0 && stored {
				episodes.Delete(key)
			}
			pending = nil
		case slices.ContainsFunc(merges, func(each *merge) bool {
			return each.verdict == "passed" && (each.finished > finished || each.sha == pending.Str("sha"))
		}):
			episodes.Delete(key)
			t.log.line(fmt.Sprintf("run %s's after-merge notice is over: %s went green", pending.Str("run"), key))
			pending = nil
		}
	}
	if pending == nil {
		at := -1
		for i, each := range merges {
			if each.verdict == "passed" {
				at = -1
			} else if each.verdict == "failed" && at < 0 {
				at = i
			}
		}
		if at < 0 {
			return closeHealth()
		}
		if slices.ContainsFunc(merges[at+1:], func(each *merge) bool { return each.verdict == "unknown" }) {
			t.log.line(fmt.Sprintf("WARN %s: a newer merge's health is unreadable; the after-merge notice waits a tick", key))
			return nil
		}
		broke, branch := merges[at], any("main")
		for _, key := range []string{"base", "target"} {
			if broke.record.Truthy(key) {
				branch = broke.record.Get(key)
			}
		}
		target, _ := branch.(string) // the branch merged into, short: `origin/main` is `main`
		target = cmp.Or(strings.TrimPrefix(target, "origin/"), "main")
		var session any
		if name := run.Seat(broke.record); name != "" {
			session = name
		}
		pending = run.Fields("sha", broke.sha, "line", fmt.Sprintf("%s failed on %s after this merge. %s. Fix the target.", broke.check, target, broke.at),
			"typed", nil, "run", broke.name, "check", broke.check, "source", "health", "finished", run.Float(broke.finished),
			"target", target, "session", session)
		// kept until it is told or its repository goes green: a seat asleep or in a turn is
		// told at its next prompt, past the window its merge leaves meanwhile.  Until watch.json
		// keeps it, its run's health is its only record, so it waits a tick, that left in place.
		episodes.Set(key, run.Fields("pending", pending))
		if !t.keep() {
			return nil
		}
	}
	keeps, err := keepsHistory(t.dry)
	if err != nil {
		return err
	}
	name, check, target := pending.Str("run"), pending.Get("check"), cmp.Or(pending.Str("target"), "main")
	if t.dry {
		t.log.line(fmt.Sprintf("would hand run %s back for %s on %s: %s", name, run.Text(check), target, pending.Str("line")))
		return nil
	}
	told, err := t.tellBreak(name, pending.Str("session"), key, pending.Str("line"), pending.Dict("typed"), func(mark *run.Object) error {
		pending.Set("typed", mark)
		t.keep()
		return nil
	})
	switch {
	case err != nil:
		return err
	case told:
		episodes.Set(key, run.Fields("notified", pending.Get("sha"), "at", run.Float(now), "run", name, "check", check,
			"finished", pending.Get("finished")))
		t.keep()
		if keeps { // broke_after_merge: what got past review and landing, written once, as it is told
			history.Update(name, t.log.line, "broke_after_merge", "health")
		}
		t.log.line(fmt.Sprintf("handed run %s back for %s on %s after its merge", name, run.Text(check), target))
	case pending.Truthy("typed"):
		t.log.line(fmt.Sprintf("run %s's after-merge notice sits in a composer; the next tick presses Enter", name))
	default:
		t.log.line(fmt.Sprintf("run %s's after-merge notice waits for a live seat at its prompt", name))
	}
	return closeHealth()
}

// tellBreak is after_merge_deliver for a run's break: its NOT LIVE line, under the run's
// delivery lock, goes to the seat tellSeat picks, the run's own seat its own.  A merge whose own
// seat took it is settled by it.  Whether a seat was told.
func (t *ticking) tellBreak(name, session, key, line string, typed *run.Object, receipt func(*run.Object) error) (bool, error) {
	dir := filepath.Join(run.Runs(), name)
	if err := os.MkdirAll(dir, 0o777); err != nil {
		return false, err
	}
	held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return false, err
	}
	defer held.Close()
	record, _ := run.Read(dir)
	line, err = loop.NotLive(dir, line)
	if err != nil {
		return false, err
	}
	told, err := t.tellSeat(session, key, line, typed, receipt)
	if told != "" && record != nil && record.Truthy("merged") && run.Seat(record) == told {
		handback.Told(dir, record) // its NOT LIVE decision settles the merge held for it
	}
	return told != "", err
}

// tellSeat is after_merge_seat and its telling: the line goes through the hand-back into the
// seat its mark names while that one is up, else session's own, woken where it sleeps and none
// until then, else the newest seat up whose runs merged into the repository key names; only at
// that seat's prompt.  The seat told, "" for none.
func (t *ticking) tellSeat(session, key, line string, typed *run.Object, receipt func(*run.Object) error) (string, error) {
	tell := func(name string) string { return handback.Tell(name, line, typed, receipt, t.log.line) }
	told := func(name, said string) (string, error) {
		switch said {
		case "":
			return "", errLeft
		case handback.Sent:
			return name, nil
		}
		return "", nil
	}
	if name := marked(seat.Up(), typed); name != "" {
		return told(name, tell(name))
	}
	if own, _, err := config.ResolveSession(session); session != "" && err == nil {
		if said := tell(own); said != handback.Gone {
			return told(own, said)
		}
	}
	newest, found := "", 0
	live := map[string]int{}
	for name, born := range seat.Up() {
		if resolved, _, err := config.ResolveSession(name); err == nil {
			name = resolved
		}
		live[name] = born
	}
	read := run.Every(func(_ string, merged *run.Object) bool {
		pr, _ := merged.Get("pr").(string)
		name := run.Seat(merged)
		born, there := live[name]
		if merged.Truthy("merged") && there && repoKey(pr) == key && (born > found || born == found && name > newest) {
			newest, found = name, born
		}
		return true
	})
	if !read {
		return "", errLeft
	}
	if newest == "" {
		return "", nil
	}
	return told(newest, tell(newest))
}

// marked is the seat up whose tmux birth a typed line's mark names, "" for none.
func marked(up map[string]int, mark *run.Object) string {
	if mark == nil || !mark.Has("seat") {
		return ""
	}
	for name, born := range up {
		if run.Equal(born, mark.Get("seat")) {
			return name
		}
	}
	return ""
}

// keep writes the after-merge marks down at once, whether it did; one that fails is said.
func (t *ticking) keep() bool {
	err := t.save()
	if err != nil {
		t.log.line("WARN could not record the after-merge mark: " + config.PyError(err))
	}
	return err == nil
}
