package harness

import (
	"bytes"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// antigravityOwned is the conversation the seat owns (antigravity.py `conversation`).
func antigravityOwned(record map[string]any) string {
	data := run.Fields("id_source", record["id_source"], "conversation", record["conversation"], "antigravity_launch", record["antigravity_launch"])
	if seen, ok := record["antigravity_open"].(map[string]any); ok {
		data.Set("antigravity_open", run.Fields("launch", seen["launch"], "conversation", seen["conversation"]))
	}
	return antigravityOpen(data)
}

// antigravityOpen is the conversation the record gives the seat, else the one store its launch's
// own agy holds open, less those other seats own: none for none, nor a guess between two; "" for
// none.  Python's claim writes that one down beside the launch's token, so it outlives the
// process; Go only asks, as each of its readers may yet hand the seat over or run dry, and nothing
// is written before that.  The records are read as they stand: a caller's copy may predate a claim.
func antigravityOpen(record *run.Object) string {
	mine := antigravityMine(record)
	token, launched := record.Get("antigravity_launch").(string)
	if mine != "" || !launched {
		return mine
	}
	found, others := false, map[string]bool{}
	for _, path := range config.SeatFiles() {
		kept, _ := run.ReadJSON(path)
		if kept == nil || kept.Has(config.Renamed) {
			continue
		}
		if !found && kept.Get("antigravity_launch") == token {
			found, mine = true, antigravityMine(kept)
		} else {
			others[antigravityMine(kept)] = true
		}
	}
	if !found || mine != "" {
		return mine
	}
	held := antigravityHeld(token)
	for other := range others {
		delete(held, other)
	}
	if open := slices.Collect(maps.Keys(held)); len(open) == 1 {
		return open[0]
	}
	return ""
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
