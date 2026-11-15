package seat

import (
	"io/fs"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// feeds is whether a state/ entry feeds a seat's word, row or card where Go does not carry it,
// which hands the whole home to Python.  A listing reads tmux and the records, a seat's word its
// own files and watch.json (orch.listing, watch.session_state); login-refusals.json its rung 1a
// reads itself (runOnALogin), and everything else passes over, whatever its name or type.  So these
// feed one: a listed seat's own file of a kind or shape Go does not read, but those its done checks
// keep, which no word reads; watch.json where quiet refuses it; and `server`, which makes this ak
// the server's client.
func feeds(state string, entry fs.DirEntry, names, live []string) bool {
	switch entry.Name() {
	case "watch.json":
		return !quiet(filepath.Join(state, entry.Name()))
	case "server":
		return true
	}
	name, owned := config.SeatFileOwner(entry.Name())
	if !owned || !slices.Contains(names, name) {
		return false
	}
	kind, _, _ := strings.Cut(entry.Name(), "-")
	suffix := strings.TrimPrefix(entry.Name(), kind+"-"+name+".")
	// no word reads its done checks' counts and pictures, nor what its seat file's write lands
	// through, whatever stands there that write's WARN (watch.seat_write)
	if slices.Contains([]string{"verified", "unverified", "pictures"}, kind) || kind == "seat" && suffix == "tmp" {
		return false
	}
	return entry.IsDir() || config.SessionName(name) != name ||
		!slices.Contains(kinds[kind], suffix) && !owedWrite(kind, suffix) && !launchKind(kind, suffix) && !goneKind(kind, suffix) &&
			!goneQuestionKind(kind, name, suffix) && !revivalKind(kind, suffix) && !pastKind(state, name, kind, suffix) &&
			!(slices.Contains(live, name) && looksKind(kind, suffix))
}

// kinds are the files state/ may hold for a seat, by kind: its record, its seat file, the lock it
// is written under and its announce lock, its typing lock, the plan of a seat the owner stopped,
// whose word no plan decides, what its last done check that found no gap read, mid-replace too,
// which plan reads to weigh whether a finished plan owes another, the last answer to whether it
// owes one, which only that answer reads (plan.checkOwed), as does that answer's write on its way
// (owedWrite), and the latch its stop hook keeps a turn's start in, which no word reads.
var kinds = map[string][]string{"session": {"json"}, "seat": {"json", "lock", "announce"}, "notify": {"lock"},
	"plan": {"md"}, "handover": {"md"}, "verify": {"lock"}, "checked": {"txt", "txt.new"}, "owed": {"json"}, "stop": {"json"}}

// quiet is whether watch.json holds nothing a seat's word reads but what Go reads: the logins the
// tick found, which the ladder's first rungs read themselves, and stalls only those a word reads as
// held and told (wordStalls).  No word reads its other keys, whatever they hold.
func quiet(path string) bool {
	data, err := run.ReadJSON(path)
	if err != nil || data == nil {
		return false
	}
	stalls := data.Dict("stalls")
	return !data.Has("stalls") || stalls != nil && wordStalls(stalls)
}
