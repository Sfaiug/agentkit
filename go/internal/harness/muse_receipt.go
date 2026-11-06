package harness

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strconv"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// museReceiptEnv names a launch's receipt to the hooks on its line (muse.py RECEIPT_ENV).
const museReceiptEnv = "AGENTKIT_MUSE_RECEIPT"

// Muse's TUI takes no session id, so each launch learns its own: a receipt, a folder in state/
// named in its record and its environment, into which its SessionStart links the session Muse
// reported and the processes the hook runs under (muse.py).  A resumed session is in it from the
// start.
func museLaunched(_, _, conversation string, _ *run.Object) (*run.Object, []string, error) {
	random := make([]byte, 16)
	rand.Read(random)
	token := hex.EncodeToString(random)
	path := museReceipt(token)
	if err := os.Mkdir(path, 0o700); err != nil {
		return nil, nil, err
	}
	if conversation != "" {
		if err := os.WriteFile(filepath.Join(path, "session"), []byte(conversation), 0o666); err != nil {
			return nil, nil, err
		}
	}
	return run.Fields("muse_launch", token), []string{museReceiptEnv + "=" + path}, nil
}

// museReceipt is the receipt a record's token names, "" for none.
func museReceipt(token string) string {
	if !launchToken.MatchString(token) {
		return ""
	}
	return filepath.Join(config.Home(), "state", "muse-launch-"+token)
}

// museStarted writes a SessionStart into that launch's receipt: the session Muse reported, and its
// lineage, the processes this hook runs under with their births, so a recycled pid is none of
// them, and every other session the registry already lists.  That Muse was born before its hook
// ran, so an entry an earlier holder of its pid left is among those, and any listed later under
// its pid is its own.  Each is linked, so the first stands; a receipt gone takes nothing.
func museStarted(receipt string, event *run.Object) {
	session := event.Str("session_id")
	if receipt == "" || !museSession.MatchString(session) {
		return
	}
	processes := []any{}
	for pid := os.Getppid(); pid > 1; {
		stat, read := host.ReadStat(pid)
		birth, born := museBirth(pid)
		if !read || !born {
			break
		}
		processes = append(processes, []any{run.Number(strconv.Itoa(pid)), birth})
		pid = stat.Parent
	}
	var listed []string
	for _, entry := range museRegistered() {
		if entry[0] != session {
			listed = append(listed, entry[0])
		}
	}
	earlier := []any{}
	for _, each := range slices.Compact(slices.Sorted(slices.Values(listed))) {
		earlier = append(earlier, each)
	}
	museWrite(receipt, "session", session, os.Link)
	museWrite(receipt, "lineage", run.Line(run.Fields("processes", processes, "earlier", earlier)), os.Link)
}

// museBirth is a process's birth as Python's host.process_identity writes it down.
func museBirth(pid int) (*run.Object, bool) {
	birth, ok := host.ReadIdentity(pid)
	return run.Fields("boot", birth.Boot, "ticks", int(birth.Ticks), "started_at", birth.StartedAt), ok
}

// museConversation is the session that launch reported, "" where it reported none yet; the one
// Muse's registry has since moved that launch's process to, once the registry says so, kept in
// the receipt for the seat to reopen on after that process is gone.  Muse's `/new` fires no hook.
func museConversation(record map[string]any) string {
	token, _ := record["muse_launch"].(string)
	path := museReceipt(token)
	if path == "" {
		return ""
	}
	session, err := os.ReadFile(filepath.Join(path, "session"))
	if err != nil || !museSession.Match(session) {
		return ""
	}
	if now := museFollowed(path); now != "" && now != string(session) {
		museWrite(path, "session", now, os.Rename)
		return now
	}
	return string(session)
}

// museFollowed is the one session the registry has given a process of that receipt's lineage
// since its hook, while that process lives as it was then; "" for no evidence, or more than one.
func museFollowed(path string) string {
	data, _ := os.ReadFile(filepath.Join(path, "lineage"))
	read, _ := run.Decode(data)
	lineage, _ := read.(*run.Object)
	if lineage == nil {
		return ""
	}
	listed, _ := lineage.Get("processes").([]any)
	earlier, _ := lineage.Get("earlier").([]any)
	births := map[string][]any{}
	for _, each := range listed {
		pair, _ := each.([]any)
		if len(pair) != 2 {
			return ""
		}
		// a pid that is no whole number names no process, as in Python
		if pid, err := strconv.Atoi(fmt.Sprint(pair[0])); err == nil {
			births["pid="+strconv.Itoa(pid)] = []any{pid, pair[1]}
		}
	}
	found := ""
	for _, entry := range museRegistered() {
		known := births[entry[1]]
		if known == nil || slices.Contains(earlier, any(entry[0])) {
			continue
		}
		if birth, born := museBirth(known[0].(int)); born && run.Equal(birth, known[1]) {
			if found != "" && found != entry[0] {
				return ""
			}
			found = entry[0]
		}
	}
	return found
}

// museRegistered is each (session, process) Muse's registry of live sessions lists, under its data
// home: one `<session>.json` each, `{"session_id": ..., "process_generation_hint": "pid=<pid>"}`
// (1.4.12).  A crashed Muse leaves its entries behind, under a pid another process may hold.
func museRegistered() [][2]string {
	// read, not globbed: the data home is a path, whatever pattern characters it holds
	registry := filepath.Join(share(), "muse", "runtime", "muse", "sessions")
	entries, _ := os.ReadDir(registry)
	var found [][2]string
	for _, entry := range entries {
		data, _ := os.ReadFile(filepath.Join(registry, entry.Name()))
		read, _ := run.Decode(data)
		listed, _ := read.(*run.Object)
		if listed == nil {
			continue
		}
		session, named := listed.Get("session_id").(string)
		hint, hinted := listed.Get("process_generation_hint").(string)
		if named && hinted && session+".json" == entry.Name() && museSession.MatchString(session) {
			found = append(found, [2]string{session, hint})
		}
	}
	return found
}

// museWrite puts text whole in the receipt's file `name` by place: a link, so the first stands, or
// a rename over it.
func museWrite(receipt, name, text string, place func(from, to string) error) {
	file, err := os.CreateTemp(receipt, "."+name+".")
	if err != nil {
		return
	}
	defer os.Remove(file.Name())
	_, err = file.WriteString(text)
	if file.Close() == nil && err == nil {
		place(file.Name(), filepath.Join(receipt, name))
	}
}
