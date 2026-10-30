package run

import (
	"fmt"
	"os"
	"slices"
	"sort"
	"time"

	"agentkit/internal/config"
)

func seconds(at time.Time) float64 {
	return float64(at.UnixNano()) / 1e9
}

// FirstNumber is the first of the keys holding a true value as a number, else 0.
func FirstNumber(record *Object, keys ...string) float64 {
	for _, key := range keys {
		if record.Truthy(key) {
			value, _ := record.Num(key)
			return value
		}
	}
	return 0
}

// InLine is whether a record holds a place in its landing line, of the states Go shows: a
// running green delivery (`land.member`).
func InLine(record *Object) bool {
	wait := record.Dict("waiting_on")
	if record.Str("state") != "running" || wait == nil || record.Truthy("merged") {
		return false
	}
	_, joined := wait.Get("joined").(Number)
	_, line := wait.Get("line").(string)
	return wait.Has("land") && !wait.Has("fix") && line && joined
}

// NeedsRecovery is work a resume could still carry on; `blocked` never is, as the task itself
// is wrong, and a stop is a deliberate end.
func NeedsRecovery(record *Object) bool {
	switch record.Str("state") {
	case "queued", "running", "pass", "blocked", "stopped", "not_needed":
		return false
	case "interrupted", "exhausted", "stalled", "waiting_login":
		return true
	}
	return record.Truthy("recovery_pending")
}

func RecoveryReason(record *Object) string {
	switch state := record.Str("state"); {
	case slices.Contains([]string{"error", "exhausted", "stalled", "waiting_login"}, state) && record.Truthy("error"):
		return Text(record.Get("error"))
	case state == "fail" && record.Truthy("recovery_pending"):
		return "Resume attempt failed; `ak run status` shows the failed checks or review."
	}
	return firstText(record, "The run stopped before recording completion.", "interruption_reason", "error")
}

// Seat is the seat the run was launched from, by its name now, or "".
func Seat(record *Object) string {
	// `session` is what a record written before the field was renamed calls the same thing
	value := record.Get("launched_session")
	if !record.Truthy("launched_session") {
		value = record.Get("session")
	}
	name, _ := value.(string)
	if name == "" {
		return ""
	}
	seat, _, err := config.ResolveSession(name)
	if err != nil {
		return ""
	}
	return seat
}

// tickAdmitted is whether the tick may take up this ending rather than a person: only an
// untold ending under a day old, from a seat that still exists.
func tickAdmitted(record *Object, now time.Time) bool {
	for _, key := range []string{"handed_back", "recovery_notified", "recovery_acknowledged_at"} {
		if record.Truthy(key) {
			return false
		}
	}
	finished, ok := record.Num("finished_at")
	if age := seconds(now) - finished; !ok || !(0 <= age && age < 86400) {
		return false
	}
	path, err := config.SessionPath(Seat(record))
	info, failed := os.Stat(path)
	return Seat(record) != "" && err == nil && failed == nil && info.Mode().IsRegular()
}

// TickAdmission says why the tick may take up this ending, or "" where it is a person's.
func TickAdmission(record *Object, now time.Time) string {
	if !tickAdmitted(record, now) {
		return ""
	}
	return fmt.Sprintf("session %s exists; ending under 24h old; not handed back, carded or acknowledged", Seat(record))
}

// Going is whether the run keeps its seat working while it lasts: the states that resume
// themselves, a run stopped to wait on an older run's change, and an error the tick will
// retry while it still admits it.
func Going(record *Object, now time.Time) bool {
	state := record.Str("state")
	switch {
	case state == "stopped" && record.Dict("lease_wait") != nil && !record.Truthy("lease_restarted"):
		return true
	case (state == "error" || state == "waiting") && !tickAdmitted(record, now):
		return false
	case slices.Contains(goes, state):
		return true
	}
	_, retry := record.Num("error_retry_at")
	return state == "error" && retry
}

// Actionable is a run still owed something: unfinished, a failure under seven days old,
// or a passed change nobody delivered yet.
func Actionable(record *Object, now time.Time) bool {
	if record.Truthy("recovery_acknowledged_at") {
		return false
	}
	at, ok := record.Num(firstKey(record, "finished_at", "started_at"))
	recent := Failed(record) && ok && seconds(now)-GCAge < at && at <= seconds(now)
	pending := record.Str("state") == "pass" && record.Truthy("repo")
	for _, key := range []string{"merged", "no_merge", "on_target", "review_pr", "review_posted"} {
		pending = pending && !record.Truthy(key)
	}
	return Active(record) || NeedsRecovery(record) || recent || pending
}

// GCAge is the status window: what ended longer ago and needs nothing more is history.
const GCAge = 7 * 86400

// firstKey is the first of the keys holding a true value, else the last, as Python's `or` picks.
func firstKey(record *Object, keys ...string) string {
	for _, key := range keys[:len(keys)-1] {
		if record.Truthy(key) {
			return key
		}
	}
	return keys[len(keys)-1]
}

type later struct {
	when float64
	id   any
}

// An Index holds, newest first, the runs that may replace another: merged runs by title,
// and runs relaunched `from:` a branch by repository and branch.
type Index map[string][]later

func indexKey(kind string, repo any, name string) string {
	return kind + "\x00" + Encode(repo) + "\x00" + name
}

// NewIndex indexes the records whose ending, else start, is a number.
func NewIndex(records []*Object) Index {
	index := Index{}
	for _, other := range records {
		when, ok := other.Num(firstKey(other, "finished_at", "started_at"))
		if !ok && !truthy(other.Get(firstKey(other, "finished_at", "started_at"))) {
			when, ok = 0, true
		}
		if !ok {
			continue
		}
		entry := later{when, other.Get("run_id")}
		if title := other.Str("title"); other.Truthy("merged") && title != "" {
			index[title] = append(index[title], entry)
		}
		if from := other.Str("from"); from != "" {
			key := indexKey("from", other.Get("repo"), from)
			index[key] = append(index[key], entry)
			if other.Truthy("merged") {
				key := indexKey("merged-from", other.Get("repo"), from)
				index[key] = append(index[key], entry)
			}
		}
	}
	for _, entries := range index {
		sort.SliceStable(entries, func(i, j int) bool { return entries[i].when > entries[j].when })
	}
	return index
}

// superseded is whether a later run replaced this one: a merged run of its title, or a run
// relaunched from its branch.
func (index Index) superseded(record *Object) bool {
	title, branch := record.Str("title"), record.Str("branch")
	if (title == "" && branch == "") || record.Truthy("merged") {
		return false
	}
	mine, ok := record.Num(firstKey(record, "finished_at", "started_at"))
	if !ok {
		mine = 0
	}
	for _, entry := range append(index[title], index[indexKey("from", record.Get("repo"), branch)]...) {
		if !Equal(entry.id, record.Get("run_id")) && entry.when > mine {
			return true
		}
	}
	return false
}

// Word is the listing's word for a run: working, needs you or done; an ending already its
// orchestrator's -- handed back or waiting for its seat's next quiet prompt, acknowledged,
// or superseded -- reads done.
func Word(record *Object, index Index, now time.Time) string {
	settled := record.Truthy("handed_back") || record.Truthy("handback_pending") ||
		record.Truthy("recovery_acknowledged_at") || index.superseded(record)
	switch {
	case Going(record, now):
		return "working"
	case (NeedsRecovery(record) || Failed(record)) && !settled:
		return "needs you"
	}
	return "done"
}
