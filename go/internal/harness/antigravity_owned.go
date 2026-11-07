package harness

import (
	"bytes"
	"context"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// antigravityOwned reads the conversation the seat owns, learned where its launch's own agy holds
// one open, and written down where it claims (antigravity.py `conversation`).
func antigravityOwned(claim bool) func(record map[string]any) string {
	return func(record map[string]any) string {
		data := run.Fields("id_source", record["id_source"], "conversation", record["conversation"], "antigravity_launch", record["antigravity_launch"])
		if seen, ok := record["antigravity_open"].(map[string]any); ok {
			data.Set("antigravity_open", run.Fields("launch", seen["launch"], "conversation", seen["conversation"]))
		}
		return antigravityLearn(data, claim)
	}
}

// antigravityLearn is the conversation the record gives the seat, else the one store its launch's
// own agy holds open, less those other seats own: none for none, nor a guess between two.  A claim
// writes that one down beside the launch's token, so it outlives the process and a stale launch's
// is never a later one's; a listing or an admission only asks, writing nothing.  "" for none.
func antigravityLearn(record *run.Object, claim bool) string {
	mine := antigravityMine(record)
	token, launched := record.Get("antigravity_launch").(string)
	if mine != "" || !launched {
		return mine
	}
	if claim {
		// One claim at a time, from the records as they stand: a caller's copy may predate this
		// launch's claim, and another seat's may land while the fds are read.
		held, err := lock.Wait(context.Background(), filepath.Join(config.Home(), "state", "antigravity-claim.lock"))
		if err != nil {
			return ""
		}
		defer held.Close()
	}
	name, others := "", map[string]bool{}
	for _, path := range config.SeatFiles() {
		kept, _ := run.ReadJSON(path)
		if kept == nil || kept.Has(config.Renamed) {
			continue
		}
		if name == "" && kept.Get("antigravity_launch") == token {
			name, mine = strings.TrimSuffix(strings.TrimPrefix(filepath.Base(path), "session-"), ".json"), antigravityMine(kept)
		} else {
			others[antigravityMine(kept)] = true
		}
	}
	if name == "" || mine != "" {
		return mine
	}
	held := antigravityHeld(token)
	for other := range others {
		delete(held, other)
	}
	open := slices.Collect(maps.Keys(held))
	if len(open) != 1 || claim && antigravitySaw(name, run.Fields("launch", token, "conversation", open[0])) != nil {
		return ""
	}
	return open[0]
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

// antigravitySaw writes what the launch saw into the seat's record as config.update_session does:
// under the record's lock, into a record still there and no rename pointer.
func antigravitySaw(name string, seen *run.Object) error {
	state := filepath.Join(config.Home(), "state")
	held, err := lock.Wait(context.Background(), filepath.Join(state, ".session-"+name+".lock"))
	if err != nil {
		return err
	}
	defer held.Close()
	path := filepath.Join(state, "session-"+name+".json")
	record, _ := run.ReadJSON(path)
	if record == nil || record.Has(config.Renamed) {
		return nil
	}
	record.Set("antigravity_open", seen)
	tmp := strings.TrimSuffix(path, ".json") + ".tmp"
	if err := os.WriteFile(tmp, []byte(run.Encode(record)+"\n"), 0o666); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}
