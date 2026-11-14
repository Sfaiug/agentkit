package harness

import (
	"bytes"
	"context"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// antigravityOwned is the conversation the seat owns (antigravity.py `conversation`).
func antigravityOwned(record map[string]any) string {
	return antigravityLearn(antigravityEvidence(record), true)
}

// antigravityEvidence is what of a seat's record says which conversation it owns.
func antigravityEvidence(record map[string]any) *run.Object {
	data := run.Fields("id_source", record["id_source"], "conversation", record["conversation"], "antigravity_launch", record["antigravity_launch"])
	if seen, ok := record["antigravity_open"].(map[string]any); ok {
		data.Set("antigravity_open", run.Fields("launch", seen["launch"], "conversation", seen["conversation"]))
	}
	return data
}

// learned is each conversation this process learned a launch's own agy holds open, by that
// launch's token, until Claim writes it down as the command ends.
var learned = struct {
	sync.Mutex
	by map[string]string
}{by: map[string]string{}}

// antigravityLearn is the conversation the record gives the seat, else the one this process
// learned its launch's own agy holds open, else the one it holds open now, less those other seats
// own: none for none, nor a guess between two.  Learning, what it learns now it keeps, for Claim to
// write down beside the launch's token, so it outlives the process and a stale launch's is never a
// later one's; nothing is written before the command ends, which may yet hand the seat over or
// run dry.  Else it only asks, keeping nothing and taking no lock (antigravityNamed).  "" for none.
func antigravityLearn(record *run.Object, learn bool) string {
	mine := antigravityMine(record)
	token, launched := record.Get("antigravity_launch").(string)
	if mine != "" || !launched {
		return mine
	}
	// One learning at a time, from the records as they stand: a caller's copy may predate this
	// launch's claim, and another seat's may land while the fds are read.  An ask answers a
	// moment early, as one reading just before that claim landed would.
	if learn {
		claiming, err := lock.Wait(context.Background(), antigravityClaimLock())
		if err != nil {
			return ""
		}
		defer claiming.Close()
	}
	learned.Lock()
	defer learned.Unlock()
	owns := func(kept *run.Object) string {
		if mine := antigravityMine(kept); mine != "" {
			return mine
		}
		launch, _ := kept.Get("antigravity_launch").(string)
		return learned.by[launch]
	}
	name, seat, others := antigravitySeats(token)
	if name == "" {
		return ""
	}
	if mine := owns(seat); mine != "" {
		return mine
	}
	held := antigravityHeld(token)
	for _, other := range others {
		delete(held, owns(other))
	}
	if open := slices.Collect(maps.Keys(held)); len(open) == 1 {
		if learn {
			learned.by[token] = open[0]
		}
		return open[0]
	}
	return ""
}

// Claim writes down, as a command ends, each conversation it learned a seat's launch holds open
// (antigravity.py `conversation`), where carried: none for a command handed over or run dry.  The
// process then knows none, as the next command starts.
func Claim(carried bool) {
	learned.Lock()
	claims := learned.by
	learned.by = map[string]string{}
	learned.Unlock()
	if !carried || len(claims) == 0 {
		return
	}
	claiming, err := lock.Wait(context.Background(), antigravityClaimLock())
	if err != nil {
		return
	}
	defer claiming.Close()
	for token, conversation := range claims {
		antigravityClaim(token, conversation)
	}
}

// antigravityClaimLock is the lock Python's claim takes too, one at a time across seats.
func antigravityClaimLock() string {
	return filepath.Join(config.Home(), "state", "antigravity-claim.lock")
}

// antigravityMine is what that record alone says its seat owns: a launcher's id, or the one its
// launch saw (antigravity.py `owned`).
func antigravityMine(record *run.Object) string {
	if record.Str("id_source") == "launcher" {
		return record.Str("conversation")
	}
	if seen := record.Dict("antigravity_open"); seen != nil && run.Equal(seen.Get("launch"), record.Get("antigravity_launch")) {
		return seen.Str("conversation")
	}
	return ""
}

// antigravityHeld is each conversation a process carrying that launch's token holds its .db open of,
// read from Linux's /proc: none elsewhere (antigravity.py `held_open`).
func antigravityHeld(token string) map[string]bool {
	want, held := []byte(antigravityLaunchEnv+"="+token), map[string]bool{}
	root, err := filepath.EvalSymlinks(antigravityConversations())
	if err != nil {
		return held
	}
	pids, _ := os.ReadDir("/proc")
	for _, pid := range pids {
		environ, err := os.ReadFile(filepath.Join("/proc", pid.Name(), "environ"))
		if err != nil || !slices.ContainsFunc(bytes.Split(environ, []byte{0}), func(pair []byte) bool { return bytes.Equal(pair, want) }) {
			continue
		}
		fds, _ := os.ReadDir(filepath.Join("/proc", pid.Name(), "fd"))
		for _, fd := range fds {
			path, err := os.Readlink(filepath.Join("/proc", pid.Name(), "fd", fd.Name()))
			stem, db := strings.CutSuffix(filepath.Base(path), ".db")
			if err == nil && db && filepath.Dir(path) == root && antigravityConversation.MatchString(stem) {
				held[stem] = true
			}
		}
	}
	return held
}

// antigravitySeats is the seat whose record carries that launch's token, "" for none, and every
// other seat's record, as they stand: a rename pointer is no seat's.
func antigravitySeats(token string) (name string, seat *run.Object, others []*run.Object) {
	for _, path := range config.SeatFiles() {
		kept, _ := run.ReadJSON(path)
		if kept == nil || kept.Has(config.Renamed) {
			continue
		}
		if name == "" && kept.Get("antigravity_launch") == token {
			name, seat = strings.TrimSuffix(strings.TrimPrefix(filepath.Base(path), "session-"), ".json"), kept
		} else {
			others = append(others, kept)
		}
	}
	return name, seat, others
}

// antigravityClaim writes the conversation that launch learned into the record of the seat
// carrying its token, as config.update_session does, under the claim lock its caller holds and
// the record's: only where that seat still carries the token and owns nothing yet, and no other
// seat owns that conversation.  The records are read again once the record's lock is held, as a
// launch writing another seat's record takes that record's lock alone, and may resume the
// conversation there while this one waits.
func antigravityClaim(token, conversation string) {
	name, _, _ := antigravitySeats(token)
	if name == "" {
		return
	}
	state := filepath.Join(config.Home(), "state")
	held, err := lock.Wait(context.Background(), filepath.Join(state, ".session-"+name+".lock"))
	if err != nil {
		return
	}
	defer held.Close()
	now, seat, others := antigravitySeats(token)
	if now != name || antigravityMine(seat) != "" ||
		slices.ContainsFunc(others, func(other *run.Object) bool { return antigravityMine(other) == conversation }) {
		return
	}
	seat.Set("antigravity_open", run.Fields("launch", token, "conversation", conversation))
	path := filepath.Join(state, "session-"+name+".json")
	tmp := strings.TrimSuffix(path, ".json") + ".tmp"
	if os.WriteFile(tmp, []byte(run.Encode(seat)+"\n"), 0o666) == nil {
		os.Rename(tmp, path)
	}
}
