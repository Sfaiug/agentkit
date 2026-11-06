package browser

import (
	"cmp"
	"errors"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Tidy is the tick's browser tidy pass at now, as Python's browser.tidy runs it: the tabs nobody
// has used closed through DevTools, never the browser.  A tab whose url and title held for
// idleMinutes closes, but for the one changed last; past tabCap open tabs the oldest by last
// change close too; the last tab, frames and workers stay.  An answer that is no list of targets,
// a tab that does not close and a record that cannot be written cost the tick nothing, and say is
// told of what closed in one line.  False, nothing closed or written, leaves the pass to Python:
// DevTools behind a proxy, or an answer or a record only Python's limits read, or one holding a
// lone surrogate.
func Tidy(now float64, say func(string)) bool {
	body, err := ask("/json/list")
	if err != nil {
		return !errors.Is(err, ErrPython)
	}
	listed, err := decode(body)
	if err != nil {
		return false
	}
	targets, ok := listed.([]any)
	if !ok {
		return true
	}
	var pages []*run.Object
	for _, each := range targets {
		target, ok := each.(*run.Object)
		if !ok {
			return true // Python's .get on it raises
		}
		if target.Get("type") != "page" {
			continue
		}
		if _, ok := target.Get("id").(string); !ok {
			return true
		}
		pages = append(pages, target)
	}
	stored := run.NewObject()
	if data, err := os.ReadFile(records()); err == nil {
		value, err := decode(data)
		if err != nil {
			return false
		}
		if object, ok := value.(*run.Object); ok {
			stored = object
		}
	}
	// each page's record, kept while its url and title hold; the idle clock resets when they
	// change, and who opened the tab stays
	updated, order, changed := run.NewObject(), map[string]int{}, map[string]float64{}
	for i, page := range pages {
		id, address, title := page.Str("id"), page.Str("url"), page.Str("title")
		record, _ := stored.Get(id).(*run.Object)
		at, held := 0.0, false
		if record != nil && record.Get("url") == address && record.Get("title") == title {
			at, held = record.Num("last_change")
		}
		if !held {
			var first any = run.Float(now)
			var opener *run.Object
			if record != nil {
				if _, ok := record.Num("first_seen"); ok {
					first = record.Get("first_seen")
				}
				opener = record.Dict("opener")
			}
			record, at = run.NewObject(), now
			record.Set("first_seen", first)
			record.Set("last_change", now)
			record.Set("url", address)
			record.Set("title", title)
			if opener != nil {
				record.Set("opener", opener)
			}
		}
		updated.Set(id, record)
		order[id], changed[id] = i, at
	}
	// DevTools lists the newest first, so of two changed at once the earlier listed is the more
	// recently used: the cap never spends a live tab on a coin toss
	ids := updated.Keys()
	older := func(a, b string) int {
		return cmp.Or(cmp.Compare(changed[a], changed[b]), cmp.Compare(order[b], order[a]))
	}
	victims := map[string]bool{}
	if len(pages) > 1 {
		newest := slices.MaxFunc(ids, older)
		minutes, _ := new(big.Float).SetInt(idleMinutes()).Float64()
		for _, id := range ids {
			if id != newest && now-changed[id] >= minutes*60 {
				victims[id] = true
			}
		}
		if limit := tabCap(); limit.Cmp(big.NewInt(int64(len(pages)))) < 0 {
			for _, id := range slices.SortedFunc(slices.Values(ids), older)[:min(len(ids), len(pages)-int(limit.Int64()))] {
				victims[id] = true
			}
		}
		if len(victims) >= len(pages) {
			delete(victims, newest)
		}
	}
	var closed, names []string
	for _, id := range slices.SortedFunc(slices.Values(ids), older) {
		if !victims[id] {
			continue
		}
		if _, err := ask("/json/close/" + id); err != nil {
			continue
		}
		closed = append(closed, id)
		if len(names) < 3 {
			names = append(names, first(cmp.Or(strings.TrimFunc(updated.Dict(id).Str("title"), config.Space), "(untitled)"), 40))
		}
		updated.Delete(id)
	}
	if closed != nil {
		say(fmt.Sprintf("browser: closed %d idle tabs (%d → %d): %s", len(closed), len(pages), len(pages)-len(closed), strings.Join(names, ", ")))
	}
	tmp := filepath.Join(config.Home(), "state", "browser-tabs.tmp")
	if os.WriteFile(tmp, []byte(run.Encode(updated)+"\n"), 0o666) == nil {
		os.Rename(tmp, records())
	}
	return true
}

// decode is JSON as Python's json reads it, an error only where Go cannot read what Python may;
// what Python refuses is nothing.
func decode(data []byte) (any, error) {
	value, err := run.DecodeLimited(data)
	if errors.Is(err, run.ErrLimit) || errors.Is(err, run.ErrLoneSurrogate) {
		return nil, err
	}
	return value, nil
}
