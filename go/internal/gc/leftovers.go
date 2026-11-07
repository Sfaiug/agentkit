package gc

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/job"
	"agentkit/internal/run"
)

// What the collector plans for what nothing outside runs and jobs comes back for: an artifact
// past its day, a gone seat's file, a harness's entries naming a gone checkout, a temporary
// entry, an entry of ak's home and an ended conversation.

// ephemeral is each registered artifact under ~/.agentkit/tmp past its day, its writer gone,
// held by nobody and unlocked (retention.ephemeral_plan).
func (r *reads) ephemeral() []Item {
	sockets := unixSockets()
	var found []Item
	for _, path := range children(tmpDir()) {
		name := filepath.Base(path)
		if !safe(path) || strings.HasSuffix(name, ".agentkit-ephemeral.json") || strings.HasSuffix(name, ".part") {
			continue
		}
		receipt := marker(path)
		record := r.json(receipt)
		if record == nil || !run.Equal(record.Get("version"), run.Number("1")) ||
			!slices.Contains([]string{"smoke", "viewer", "update"}, record.Str("kind")) || record.Get("path") != path ||
			!record.Has("pid") || writerActive(record) {
			continue
		}
		if !expired(first(record, "finished_at", "created_at"), r.now, day) || busy(path, r.paths) {
			continue
		}
		var live []string // only a smoke tree's dead sockets go with it
		if record.Str("kind") == "smoke" {
			live = sockets
		}
		snapshot, ok := tree(path, live, nil)
		if !ok || slices.ContainsFunc(snapshot, func(each entry) bool { return r.now-float64(each.mtime)/1e9 < day }) ||
			present(receipt+".part") || !leaseFree(receipt) {
			continue
		}
		found = append(found, Item{"remove", record.Str("kind"), path, "", takeEphemeral(path, receipt, record.Str("kind") == "smoke", snapshot)})
	}
	return found
}

// leaseFree is whether no writer holds the receipt's lease.
func leaseFree(receipt string) bool {
	if !safe(receipt) {
		return false
	}
	file, err := open(receipt, false)
	if err != nil {
		return false
	}
	defer file.Close()
	return unlocked(file)
}

// seatFiles is every `<kind>-<seat>.*` state file of a seat that is gone, a day after its last
// write: no record, tmux holding none by the name, and no run of it going or owed a hand-back
// (gc.stale_seat_files).
func (r *reads) seatFiles() []Item {
	folder := filepath.Join(config.Home(), "state")
	if !safe(folder) {
		return nil
	}
	launched := map[string]bool{}
	for _, dir := range children(runsDir()) {
		record := r.json(filepath.Join(dir, "run.json"))
		if record == nil || !run.Active(record) && !(needsRecovery(record) && !record.Truthy("recovery_acknowledged_at")) &&
			!record.Truthy("handback_pending") {
			continue
		}
		if seat, named := launchedSession(record); named {
			if name, _, err := config.ResolveSession(seat); err == nil {
				launched[name] = true
			}
		}
	}
	var found []Item
	for _, path := range children(folder) {
		if name, ok := r.seatGone(path); ok && !launched[name] && !r.seated(name) {
			found = append(found, Item{"remove", "seat-file", path, "seat " + name + " is gone", takeSeatFile(path)})
		}
	}
	return found
}

// seatGone is the seat a state file is named for, where that seat has no record and the file
// has not been written for a day (gc.seat_file_stale).
func (r *reads) seatGone(path string) (string, bool) {
	name, ok := config.SeatFileOwner(filepath.Base(path))
	if !ok || !safe(path) || !isFile(path) {
		return "", false
	}
	record, err := config.SessionPath(name)
	if err != nil || present(record) {
		return "", false
	}
	info, _ := os.Lstat(path)
	return name, expired(mtime(info), r.now, day)
}

// harnessEntries is each harness file whose trust or MCP entries name a gone smoke sandbox or
// checkout (retention.harness_plan).
func (r *reads) harnessEntries() []Item {
	var found []Item
	for _, file := range harness.ConfigEntries() {
		if trust, mcp := r.staleEntries(file.File, file.Trust, file.MCP); trust+mcp > 0 {
			why := fmt.Sprintf("%d trust entries and %d MCP servers name a gone smoke sandbox or checkout", trust, mcp)
			found = append(found, Item{"prune", "harness-entries", file.File, why, takeHarness(file.File, file.Trust, file.MCP)})
		}
	}
	return found
}

// staleEntries is how many of a harness file's trusted directories name a gone sandbox or
// checkout, and how many of its MCP servers name one anywhere; none for a file that is a link,
// not ours, or does not parse (retention.harness_pruned).
func (r *reads) staleEntries(file, trust, mcp string) (int, int) {
	data, err := readBytes(file)
	if err != nil || !isFile(file) || !utf8.Valid(data) {
		return 0, 0
	}
	var document map[string]any
	if strings.HasSuffix(file, ".toml") {
		document, _ = config.ReadTOML(string(data))
	} else {
		value, err := run.DecodeLimited(data)
		if errors.Is(err, run.ErrLoneSurrogate) || errors.Is(err, run.ErrLimit) {
			r.python = true
		}
		document = members(value)
	}
	trusted, servers := 0, 0
	for key := range members(document[trust]) {
		if gonePath(key) {
			trusted++
		}
	}
	for _, entry := range members(document[mcp]) {
		if slices.ContainsFunc(texts(entry), gonePath) {
			servers++
		}
	}
	return trusted, servers
}

// members is a parsed table's or object's values by key, none for anything else.
func members(value any) map[string]any {
	switch value := value.(type) {
	case map[string]any:
		return value
	case *run.Object:
		found := map[string]any{}
		for _, key := range value.Keys() {
			found[key] = value.Get(key)
		}
		return found
	}
	return nil
}

// texts is every string inside a parsed JSON or TOML value.
func texts(value any) []string {
	var found []string
	switch value := value.(type) {
	case string:
		found = append(found, value)
	case *run.Object, map[string]any:
		for _, each := range members(value) {
			found = append(found, texts(each)...)
		}
	case []any:
		for _, each := range value {
			found = append(found, texts(each)...)
		}
	}
	return found
}

// gonePath is a place inside a `~/.agentkit/tmp/smoke-*` sandbox or a `~/.agentkit/wt/*`
// checkout that is gone (retention.gone_path).
func gonePath(value string) bool {
	if !strings.HasPrefix(value, "/") || climbs(config.Pure(value)) {
		return false
	}
	for _, root := range [][2]string{{tmpDir(), "smoke-"}, {wtDir(), ""}} {
		if below(value, root[0]) {
			top, _, _ := strings.Cut(strings.TrimPrefix(config.Pure(value), root[0]+"/"), "/")
			return strings.HasPrefix(top, root[1]) && !present(filepath.Join(root[0], top))
		}
	}
	return false
}

// tmpEntries is each stale top-level /tmp entry (gc.stale_tmp_entries).
func (r *reads) tmpEntries() []Item {
	return r.tmpBase("/tmp")
}

// tmpBase is each top-level entry of that folder nothing changed for two days and nobody holds,
// ours alone.  A harness owning an entry by its name judges it its own way, which Go has not
// ported: there the plan is Python's.
func (r *reads) tmpBase(base string) []Item {
	names, err := listdir(base)
	if err != nil || len(names) == 0 {
		return nil
	}
	paths := r.every()
	if paths == nil {
		return nil
	}
	var found []Item
	for _, name := range names {
		if protected(name) {
			continue
		}
		if harness.OwnsTmp(name) {
			r.python = true
			continue
		}
		path := filepath.Join(base, name)
		if why := r.untouched(path, paths, tmpAge); why != "" {
			found = append(found, Item{"remove", "tmp-entry", path, why, takeTmp(path)})
		}
	}
	return found
}

// protected is a dot entry, a tmux socket or a systemd-private folder: never the collector's.
func protected(name string) bool {
	return strings.HasPrefix(name, ".") || strings.HasPrefix(name, "tmux-") || strings.HasPrefix(name, "systemd-private-")
}

// untouched is why that entry goes, or "" where it stays: ours alone, nothing in it changed for
// `age`, and held by nobody (gc.untouched).
func (r *reads) untouched(path string, paths []string, age float64) string {
	if busy(path, paths) {
		return ""
	}
	newest, ok := newestChange(path)
	if !ok || !expired(newest, r.now, age) {
		return ""
	}
	return fmt.Sprintf("untouched for %d days", int(math.Floor((r.now-newest)/day)))
}

// newestChange is the newest change of any entry of a tree, false where it is not ours alone to
// take: an entry another user's, a link at the top, a socket, fifo or device inside, or anything
// unreadable (gc.tmp_tree_newest).  A file counts its inode's change, which a restored time does
// not move; a folder its contents' alone, which a daily tmpfiles pass leaves.
func newestChange(path string) (float64, bool) {
	changed := func(info fs.FileInfo, st stat) float64 {
		if info.IsDir() {
			return float64(st.mtime) / 1e9
		}
		return float64(max(st.mtime, st.ctime)) / 1e9
	}
	if !safe(path) {
		return 0, false
	}
	info, st, ok := lstat(path)
	if !ok {
		return 0, false
	}
	newest := changed(info, st)
	if !isDir(path) {
		return newest, true
	}
	for stack := []string{path}; len(stack) > 0; {
		current := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		names, err := listdir(current)
		if err != nil {
			return 0, false
		}
		for _, name := range names {
			child := filepath.Join(current, name)
			info, st, ok := lstat(child)
			if !ok || st.uid != uint32(os.Getuid()) {
				return 0, false
			}
			newest = max(newest, changed(info, st))
			if info.Mode()&fs.ModeSymlink != 0 {
				continue
			}
			if !safe(child) {
				return 0, false
			}
			if info.IsDir() {
				stack = append(stack, child)
			}
		}
	}
	return newest, true
}

// repoTmpEntries is the /tmp rule for each repository's TMPDIR directly under /var/tmp, from
// ~/.agentkit/env/<repo>.env; any other TMPDIR is named once and left alone
// (gc.stale_repo_tmp_entries).
func (r *reads) repoTmpEntries() []Item {
	names, err := listdir(filepath.Join(config.Home(), "env"))
	if err != nil {
		return nil
	}
	var found []Item
	seen := map[string]bool{}
	for _, name := range names {
		if !strings.HasSuffix(name, ".env") {
			continue
		}
		env, err := config.RepoEnv(stem(name))
		value, set := env["TMPDIR"]
		if err != nil || !set || seen[value] {
			continue
		}
		seen[value] = true
		// only the plain case: canonical, so no link and no `..`, and directly under /var/tmp
		if filepath.Dir(config.Pure(value)) != "/var/tmp" || config.Resolve(value) != value {
			// a TMPDIR gc never sweeps is named once a pass, and left alone
			skipped := Item{"skip", "repo-tmp", value, "not a canonical path directly under /var/tmp", nil}
			skipped.take = func(c *collection) (bool, error) {
				c.report(skipped.said())
				return false, nil
			}
			found = append(found, skipped)
			continue
		}
		found = append(found, r.tmpBase(value)...)
	}
	return found
}

// stem is a file's name less its suffix, as Python's PurePath.stem reads it.
func stem(name string) string {
	if at := strings.LastIndex(name, "."); at > 0 && at < len(name)-1 {
		return name[:at]
	}
	return name
}

// homeEntries is the largest parts of each of ak's home folders nothing changed for its age,
// whole: at the top of ~/.agentkit anything not ak's own a week, a task file and a file fetched
// from the Mac a run directory's age.  What a process holds, and a task file a job still names,
// stay (gc.stale_home_entries).
func (r *reads) homeEntries() []Item {
	paths := r.every()
	if paths == nil {
		return nil
	}
	paths = append(slices.Clone(paths), r.taskFiles()...)
	var found []Item
	for _, folder := range []struct {
		path string
		age  float64
	}{
		{config.Home(), gcAge},
		{filepath.Join(config.Home(), "tasks"), runAge},
		{filepath.Join(config.UserHome(), ".agentkit", "macbridge", "inbox"), runAge},
	} {
		found = append(found, r.homeFolder(folder.path, folder.age, paths)...)
	}
	return found
}

// own is what ak keeps at the top of its home (config.OWN).
var own = []string{"agentkit.git", "bin", "config.toml", "env", "history.db", "history.db-journal", "history.db-wal",
	"history.db-shm", "history.lock", "history.log", "jobs", "macbridge", "rules.md", "runs", "secrets", "state", "tasks",
	"tmp", "versions", "work", "wt"}

// homeFolder is a folder's entries nothing changed for its age; one with something newer inside
// is looked into.
func (r *reads) homeFolder(folder string, age float64, paths []string) []Item {
	names, err := listdir(folder)
	if err != nil {
		return nil
	}
	var found []Item
	for _, name := range names {
		path := filepath.Join(folder, name)
		if folder == config.Home() && slices.Contains(own, name) {
			continue
		}
		if why := r.untouched(path, paths, age); why != "" {
			found = append(found, Item{"remove", "home-entry", path, why, takeHomeEntry(path, age)})
		} else if isDir(path) && safe(path) {
			found = append(found, r.homeFolder(path, age, paths)...)
		}
	}
	return found
}

// taskFiles is every task file a job still names: a queued task's is read when its turn comes.
func (r *reads) taskFiles() []string {
	var named []string
	if !safe(job.Jobs()) {
		return nil
	}
	for _, dir := range children(job.Jobs()) {
		if job := r.json(job.ReceiptPath(filepath.Base(dir))); job != nil {
			for _, task := range job.List("tasks") {
				if task, ok := task.(*run.Object); ok && isText(task.Get("task_file")) {
					named = append(named, task.Str("task_file"))
				}
			}
		}
	}
	return named
}

func isText(value any) bool {
	_, ok := value.(string)
	return ok
}

// conversations is each conversation a harness keeps as rows of its own database that it names
// idle for a run directory's age, by its id, then each one a harness keeps in files and never
// ends itself that nobody wrote to for as long and nobody holds open; never one a seat holds
// (gc.stale_conversations).
func (r *reads) conversations() []Item {
	idle, known := harness.IdleConversations(r.now - runAge)
	if !known {
		r.python = true
	}
	var found []Item
	for _, each := range idle {
		if r.free(each.Harness, each.ID) {
			why := fmt.Sprintf("untouched for %d days", int(runAge/day))
			found = append(found, Item{"remove", "conversation", each.ID, why, takeIdle(each)})
		}
	}
	paths := r.every()
	if paths == nil {
		return found
	}
	for _, store := range harness.ConversationStores(func(folder string) []string {
		names, _ := listdir(folder)
		return names
	}) {
		for _, path := range glob(store.Root, store.Pattern) {
			why := r.conversationStale(path, paths)
			if named := store.ID.FindStringSubmatch(filepath.Base(path)); why != "" && named != nil && r.free(store.Harness, named[1]) {
				found = append(found, Item{"remove", "conversation", path, why, takeConversation(store.Harness, path, named[1])})
			}
		}
	}
	return found
}

// free is whether no seat holds that conversation of that harness (gc.conversation_free), the
// seats read once, and only once one would go: a seat's harness may write down what it follows.
func (r *reads) free(name, conversation string) bool {
	if r.holds == nil {
		r.holds = r.seatsHold()
	}
	return !r.holds(name, conversation)
}

// seatsHold is whether a seat holds that conversation of that harness, the seats' records read as
// they are now (gc.held_conversations): its current one and each it left; every one of a harness
// a seat of which cannot say which it holds; and every one at all where a record does not read
// whole or a seat's harness is no name.  A record Go reads otherwise than Python does makes the
// plan Python's.
func (r *reads) seatsHold() func(name, conversation string) bool {
	every := func(string, string) bool { return true }
	state := filepath.Join(config.Home(), "state")
	entries, err := os.ReadDir(state)
	if errors.Is(err, fs.ErrNotExist) {
		entries, err = nil, nil // no state yet, so no seat
	}
	if err != nil {
		return every
	}
	held, unknown := map[string]bool{}, map[string]bool{}
	// hold is what a seat's record says of one of its conversations: false where its harness is no name
	hold := func(own, conversation any) bool {
		name, _ := own.(string)
		id, _ := conversation.(string)
		switch {
		case name == "":
			return false
		case id != "":
			held[id] = true
		default:
			unknown[name] = true
		}
		return true
	}
	for _, entry := range entries {
		if !strings.HasPrefix(entry.Name(), "session-") || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		path := filepath.Join(state, entry.Name())
		data, err := os.ReadFile(path)
		if errors.Is(err, fs.ErrNotExist) && !present(path) {
			continue // gone since the listing
		}
		value, decoded := run.DecodeLimited(data)
		if errors.Is(decoded, run.ErrLoneSurrogate) || errors.Is(decoded, run.ErrLimit) {
			r.python = true
		}
		record, _ := value.(*run.Object)
		if err != nil || decoded != nil || !utf8.Valid(data) || record == nil {
			return every
		}
		if record.Has(config.Renamed) {
			if _, pointer := record.Get(config.Renamed).(string); pointer && len(record.Keys()) == 1 {
				continue // a rename's pointer
			}
			return every
		}
		left, listed := record.Get("left").([]any)
		if !listed && record.Has("left") {
			return every
		}
		for _, was := range left {
			if was, ok := was.(*run.Object); !ok || !hold(was.Get("harness"), was.Get("conversation")) {
				return every
			}
		}
		// the conversation it is on, as every reader of a seat's record hands it to its harness
		own, conversation := seatHarness(record), ""
		if own != "" {
			var fields map[string]any
			json.Unmarshal(data, &fields)
			conversation = harness.Current(own, fields)
		}
		if !hold(own, conversation) {
			return every
		}
	}
	return func(name, conversation string) bool { return held[conversation] || unknown[name] }
}

// seatHarness is the harness a seat's record orchestrates on, "" where the config names none
// (orch.seat_harness).
func seatHarness(record *run.Object) string {
	model, err := config.ModelNamed(record.Str("orchestrator"))
	if err != nil {
		return ""
	}
	return model.Harness
}

// glob is what Python's Path.glob finds under root, in Path order: each `*` any name, dot names
// among them, a folder through a link counting as one, and a pattern ending in `/` folders only.
func glob(root, pattern string) []string {
	parts := strings.Split(pattern, "/")
	folders := parts[len(parts)-1] == ""
	if folders {
		parts = parts[:len(parts)-1]
	}
	found := []string{root}
	for i, part := range parts {
		var next []string
		for _, dir := range found {
			entries, _ := os.ReadDir(dir)
			for _, entry := range entries {
				path := filepath.Join(dir, entry.Name())
				if matched, _ := filepath.Match(part, entry.Name()); matched && (i == len(parts)-1 && !folders || isDir(path)) {
					next = append(next, path)
				}
			}
		}
		found = next
	}
	slices.SortFunc(found, func(a, b string) int {
		return slices.Compare(strings.Split(a, "/"), strings.Split(b, "/"))
	})
	return found
}

// conversationStale is why that conversation goes, "" where it stays (gc.conversation_stale).
func (r *reads) conversationStale(path string, paths []string) string {
	if !safe(path) || busy(path, paths) {
		return ""
	}
	at, ok := lastFileWrite(path)
	if !ok || !expired(at, r.now, runAge) {
		return ""
	}
	return fmt.Sprintf("untouched for %d days", int(math.Floor((r.now-at)/day)))
}

// lastFileWrite is when a conversation's file, or the newest file in its folder, last changed;
// an empty folder's own time; false for anything else, or what cannot all be read.  Only files
// count: a harness rescanning its sessions changes their folders' times (gc.last_write).
func lastFileWrite(path string) (float64, bool) {
	info, err := os.Lstat(path)
	if err != nil {
		return 0, false
	}
	if isFile(path) {
		return mtime(info), true
	}
	if !isDir(path) {
		return 0, false
	}
	newest, files, whole := 0.0, 0, true
	var walk func(string)
	walk = func(dir string) {
		entries, err := os.ReadDir(dir)
		if err != nil {
			whole = false
		}
		for _, entry := range entries {
			child := filepath.Join(dir, entry.Name())
			if isDir(child) {
				if entry.Type()&fs.ModeSymlink == 0 {
					walk(child)
				}
			} else if info, err := os.Lstat(child); err != nil {
				whole = false
			} else {
				newest, files = max(newest, mtime(info)), files+1
			}
		}
	}
	walk(path)
	if files == 0 {
		newest = mtime(info)
	}
	return newest, whole
}
