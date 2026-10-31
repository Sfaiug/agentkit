// Package seat is what Go knows of the seats. Read takes the home in once, into the seats it
// knows or a no wherever Python's answer hangs on anything that reading leaves out, and decides
// each word from that reading alone; each later piece widens what Read knows, here.
package seat

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	"agentkit/internal/agent"
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
	"agentkit/internal/tmux"
)

// A Seat is one tmux no longer holds, only its record, as Python's orch.listing offers it, with
// the word and tally its runs give it (watch.session_state, handback.seat_tallies).
type Seat struct {
	Name, Project, Word, Tally, Orchestrator, Workers string
	Warning                                           string // why its record's models read as `?`
	Created                                           float64
	reason, restart                                   string
	since, repo                                       any
	infer                                             bool     // the record holds no repo
	unowned                                           bool     // would resume its record's conversation, and it names none: Python offers it no row
	closed                                            bool     // its seat file holds the owner's stop mark
	home                                              []string // where the menu files it (orch.home_key)
	follow                                            move     // what its last answer moves in its record
}

// A Home is what Read knows: the seats with rows, in Python's order, and the seat of every
// record, row or not, for what the listing writes into it.
type Home struct {
	Seats   []Seat
	records []Seat
	models  map[string]config.Model
}

// Seatless is whether the home holds no record at all.
func (home Home) Seatless() bool { return len(home.records) == 0 }

// kinds are the files state/ may hold for a seat, by kind: its record and its lock, its seat
// file's, its typing lock, and the plan of a seat the owner stopped, whose word no plan decides.
var kinds = map[string][]string{"session": {"json"}, ".session": {"lock"}, "seat": {"json", "lock", "announce"}, "notify": {"lock"},
	"plan": {"md"}}

var (
	recordFields = []string{"orchestrator", "workers", "cwd", "created", "conversation", "id_source", "resumable", "session_title", "repo"}
	seatFields   = slices.Concat([]string{"word", "reason", "unsent", "word_since", "word_from", "session", "stopped_at", "closed_by_owner", "unasked"}, waits)
	runFields    = []string{"run_id", "title", "repo", "started_at", "finished_at", "state", "merged", "launched_session"}
)

// A ran is one of a seat's runs: its directory's name, its record, and how long since run.json
// was written.
type ran struct {
	name   string
	record *run.Object
	quiet  float64
}

// Read is the home, and whether Go knows it: no record where milestone 6b found none, else
// only seats on no tmux server, with records, seat files and runs it follows.
func Read(now time.Time) (Home, bool) {
	state := filepath.Join(config.Home(), "state")
	entries, err := os.ReadDir(state)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return Home{}, false
	}
	var names []string
	for _, entry := range entries {
		if name, ok := sessionFile(entry.Name()); ok {
			names = append(names, name)
		}
	}
	if len(names) == 0 {
		return Home{}, seatless()
	}
	var planned []string
	for _, entry := range entries {
		if entry.Name() == "watch.lock" || entry.Name() == "watch.json" && quiet(filepath.Join(state, "watch.json")) {
			continue
		}
		kind, rest, _ := strings.Cut(entry.Name(), "-")
		name, suffix, _ := strings.Cut(rest, ".")
		// a seat removed leaves its locks, which writers hold or wait on, and its stop mark, which
		// no listing reads (forget)
		if !slices.Contains(names, name) && entry.Type().IsRegular() && (suffix == "lock" || kind == "seat" && suffix == "json") {
			continue
		}
		if entry.IsDir() || !slices.Contains(names, name) || name == "" || config.SessionName(name) != name || !slices.Contains(kinds[kind], suffix) {
			return Home{}, false
		}
		if kind == "plan" {
			planned = append(planned, name)
		}
	}
	models, err := config.Models()
	offered, unread := config.Offered()
	runs, known := readRuns(names, now)
	if err != nil || unread != nil || !known || !OnNoServer() {
		return Home{}, false
	}
	home := Home{models: models}
	stands := sync.OnceValue(listed)
	for _, name := range names {
		seat, ok := read(state, name, models, offered, runs[name], now)
		if !ok || !seat.closed && slices.Contains(planned, name) {
			return Home{}, false
		}
		home.records = append(home.records, seat)
		if !seat.unowned {
			repo, _ := seat.repo.(string)
			seat.home = homeKey(repo, stands)
			home.Seats = append(home.Seats, seat)
		}
	}
	// the seats the owner stopped come last, for the menu's past screen (orch.numbered)
	past := func(seat Seat) int {
		if seat.closed {
			return 1
		}
		return 0
	}
	slices.SortFunc(home.Seats, func(a, b Seat) int {
		return cmp.Or(cmp.Compare(past(a), past(b)), slices.Compare(a.home, b.home), cmp.Compare(a.Created, b.Created), cmp.Compare(a.Name, b.Name))
	})
	for i, seat := range home.Seats {
		if seat.Word == "idle" {
			home.Seats[i].reason = fmt.Sprintf("session closed: press %d to reopen", i+1)
			if seat.closed {
				home.Seats[i].reason = "session closed by the owner: reopen it from past sessions"
			}
			if seat.restart != "" {
				home.Seats[i].reason += " · " + seat.restart
			}
		}
	}
	return home, true
}

// read is the seat one record holds, from it, its seat file and its runs.
func read(state, name string, models map[string]config.Model, offered []string, mine []ran, now time.Time) (Seat, bool) {
	record, err := run.ReadJSON(filepath.Join(state, "session-"+name+".json"))
	if err != nil || record == nil {
		return Seat{}, false
	}
	seat, known := recorded(state, name, record, models)
	if !known {
		return Seat{}, false
	}
	if seat.Warning == "" { // a record Python cannot read moves nothing
		if seat.follow, known = follows(record, models, offered); !known {
			return Seat{}, false
		}
	}
	previous, err := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	if err != nil && !errors.Is(err, fs.ErrNotExist) || err == nil && (previous == nil || !only(previous, seatFields)) {
		return Seat{}, false
	}
	// Python offers a stopped seat that owns no conversation a fresh start, which Go does not word yet
	if seat.closed, known = stopped(previous); !known || seat.closed && seat.unowned {
		return Seat{}, false
	}
	if seat.Created == 0 {
		seat.Created = float64(now.Unix())
	}
	if seat.infer {
		seat.repo = vote(mine)
	}
	seat.Project = "no project"
	if repo, _ := seat.repo.(string); repo != "" {
		seat.Project = base(repo)
	}
	var going []ran
	merged := 0
	for _, each := range mine {
		if each.record.Str("state") == "running" {
			going = append(going, each)
			continue
		}
		finished := run.FirstNumber(each.record, "finished_at", "started_at")
		if seconds(now)-run.GCAge <= finished && finished <= seconds(now) {
			merged++
		}
	}
	if len(mine) > 0 {
		seat.Tally = fmt.Sprintf("%d running · %d merged", len(going), merged)
	}
	if len(going) > 0 {
		seat.Word = "working"
		seat.reason, seat.since = working(going)
	}
	return seat, true
}

// recorded is the seat a record holds as far as the record alone says; false where Go does not
// follow that record.
func recorded(state, name string, record *run.Object, models map[string]config.Model) (Seat, bool) {
	restart, known := harness.Reopens(models[record.Str("orchestrator")].Harness)
	workers, complaint, crewed := crew(record.Get("workers"), models)
	created, dated := number(record.Get("created"))
	// as launched, or as reconcile leaves a record whose harness proves no conversation it names
	resumable := record.Get("resumable") == true || restart != "" && record.Get("resumable") == false
	if !only(record, recordFields) || !known || !crewed || !dated || !text(record.Get("cwd")) || !text(record.Get("repo")) ||
		!text(record.Get("conversation")) || record.Str("id_source") != "launcher" || !resumable {
		return Seat{}, false
	}
	seat := Seat{Name: name, Word: "idle", Tally: "no runs yet", Orchestrator: record.Str("orchestrator"), Workers: workers,
		Created: created, restart: restart, repo: record.Get("repo"), infer: !record.Has("repo"),
		unowned: restart == "" && record.Str("conversation") == ""}
	if complaint != "" {
		seat.Orchestrator, seat.Workers = "?", "?"
		seat.Warning = filepath.Join(state, "session-"+name+".json") + ": " + complaint
	}
	return seat, true
}

// working is the reason and the since of a seat its runs keep working, as watch.session_state
// gives them: how many run, the first gone quiet for an hour by name, and the title of that one
// or else of the last started.
func working(going []ran) (string, any) {
	var since any
	newest := going[0]
	for _, each := range going {
		started := each.record.Get("started_at")
		if started != nil && (since == nil || at(started) < at(since)) {
			since = started
		}
		if a, b := at(started), at(newest.record.Get("started_at")); a > b || a == b && each.name > newest.name {
			newest = each
		}
	}
	parts := []string{fmt.Sprintf("%d running", len(going))}
	for _, each := range going { // by name, as runs/ reads
		if each.quiet > 3600 {
			newest = each
			parts = append(parts, "silent "+terminal.FormatAge(each.quiet))
			break
		}
	}
	title := newest.record.Str("title")
	if title == "" {
		title = newest.name
	}
	if title = config.Fold(title); title != "" {
		parts = append(parts, title)
	}
	return strings.Join(parts, " · "), since
}

// readRuns is each seat's runs as Python's menu.run_records reads them, a smoke run's aside, or
// false where runs/ holds anything else.
func readRuns(names []string, now time.Time) (map[string][]ran, bool) {
	entries, err := os.ReadDir(run.Runs())
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return nil, false
	}
	mine := map[string][]ran{}
	running := map[string]bool{} // whether each seat a run names has one running
	for _, entry := range entries {
		dir := filepath.Join(run.Runs(), entry.Name())
		inside, err := os.ReadDir(dir)
		if err != nil || len(inside) != 1 || inside[0].Name() != "run.json" {
			return nil, false
		}
		info, err := os.Stat(filepath.Join(dir, "run.json"))
		record, readErr := run.Read(dir)
		if err != nil || readErr != nil || record == nil || !only(record, runFields) {
			return nil, false
		}
		state, seat := record.Str("state"), record.Str("launched_session")
		_, started := number(record.Get("started_at"))
		_, finished := number(record.Get("finished_at"))
		if !slices.Contains(names, seat) || !text(record.Get("title")) || !text(record.Get("repo")) || !started || !finished ||
			state != "running" && !(state == "pass" && record.Get("merged") == true) {
			return nil, false
		}
		running[seat] = running[seat] || state == "running"
		if !run.SmokeRun(record) {
			mine[seat] = append(mine[seat], ran{entry.Name(), record, now.Sub(info.ModTime()).Seconds()})
		}
	}
	for _, going := range running {
		// a merge with nothing running awaits its live check (watch.awaiting_live), unknown here
		if !going {
			return nil, false
		}
	}
	return mine, true
}

// Announce writes what Python's listing writes before it draws: into each record what it
// infers (orch.records, orch.session_projects), then each seat's word into its seat file
// (watch.announce_state), under the locks Python takes for each.
func (home Home) Announce(now time.Time) error {
	state := filepath.Join(config.Home(), "state")
	if err := reconcile(state, home.records, true); err != nil {
		return err
	}
	for _, seat := range home.Seats {
		if err := seat.announce(state, now, home.models); err != nil {
			return err
		}
	}
	return nil
}

// reconcile writes into each seat's record what Python's orch.records reconciles before anything
// claims it resumable, and with `infer` the project orch.session_projects infers for one that
// names none.
func reconcile(state string, records []Seat, infer bool) error {
	for _, seat := range records {
		var fields []field
		if seat.restart != "" {
			fields = append(fields, field{"resumable", false})
		}
		if infer && seat.infer {
			fields = append(fields, field{"repo", seat.repo})
		}
		if len(fields) == 0 {
			continue
		}
		if err := update(state, seat.Name, set(fields)); err != nil {
			return err
		}
	}
	return nil
}

// announce is watch.announce_state for a seat nobody is in: under its announce lock, what its
// last answer moved, then its word, begun where the seat file says it began by then, or now
// where it said another.
func (seat Seat) announce(state string, now time.Time, models map[string]config.Model) error {
	if err := config.EnsureDirs(); err != nil {
		return err
	}
	held, err := lock.Wait(context.Background(), filepath.Join(state, "seat-"+seat.Name+".announce"))
	if err != nil {
		return err
	}
	defer held.Close()
	if err := seat.moved(state, models); err != nil {
		return err
	}
	path := filepath.Join(state, "seat-"+seat.Name+".json")
	previous, _ := run.ReadJSON(path)
	if previous == nil {
		previous = run.NewObject()
	}
	since := seat.since
	if run.Equal(previous.Get("word"), seat.Word) {
		if previous.Has("word_since") {
			since = previous.Get("word_since")
		}
	} else if previous.Get("word") != nil {
		since = run.Float(seconds(now))
	}
	fields := []field{{"word", seat.Word}, {"reason", seat.reason}, {"unsent", ""}, {"word_since", since}, {"word_from", []any{nil, nil, ""}}}
	if !slices.ContainsFunc(fields, func(f field) bool {
		if f.key == "unsent" { // `or ""`: any false value is no draft
			return previous.Truthy("unsent")
		}
		return !run.Equal(previous.Get(f.key), f.value)
	}) {
		return nil
	}
	return writeSeat(state, seat.Name, fields)
}

type field struct {
	key   string
	value any
}

// put changes the JSON object a file holds under its lock, through a temporary file beside it,
// only where `change` says it changed it; a file holding none starts from an empty one where
// `start` says so, as watch.seat_write starts a seat file, and is left as it is otherwise.  One
// Python reads and Go cannot keep is ErrLoneSurrogate, never written over.
func put(path, held string, encode func(any) string, start bool, change func(data *run.Object) bool) error {
	file, err := lock.Wait(context.Background(), held)
	if err != nil {
		return err
	}
	defer file.Close()
	data, err := run.ReadJSON(path)
	if errors.Is(err, run.ErrLoneSurrogate) {
		return err
	}
	if data == nil && start {
		data = run.NewObject()
	}
	if data == nil || !change(data) {
		return nil
	}
	tmp := strings.TrimSuffix(path, ".json") + ".tmp"
	if err := os.WriteFile(tmp, []byte(encode(data)+"\n"), 0o666); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// update changes a seat's record as config.update_session and change_efforts do: only one still
// there under its lock, never one removed or left a rename pointer while the listing waited.
func update(state, name string, change func(data *run.Object) bool) error {
	return put(filepath.Join(state, "session-"+name+".json"), filepath.Join(state, ".session-"+name+".lock"), run.Encode, false,
		func(data *run.Object) bool { return !data.Has(config.Renamed) && change(data) })
}

// set is the change that sets fields, and the stamps beside them, only where a field changes
// what the object holds. A repo it lacks is a change though the field is null, as
// update_session records a deliberate lack of project.
func set(fields []field, stamps ...field) func(*run.Object) bool {
	return func(data *run.Object) bool {
		if !slices.ContainsFunc(fields, func(f field) bool {
			return !run.Equal(data.Get(f.key), f.value) || f.key == "repo" && !data.Has("repo")
		}) {
			return false
		}
		for _, f := range append(fields, stamps...) {
			data.Set(f.key, f.value)
		}
		return true
	}
}

// OnNoServer is whether tmux holds no seat at all: no session on ak's server but its control
// one, and none ak opened on the default server.
func OnNoServer() bool {
	return len(tmux.Sessions(tmux.Own())) == 0 && !marked(tmux.Default)
}

// seatless is milestone 6b's no seat: no record, on ak's own server only sessions it did not
// open running no agent, and no marked session on the default server.
func seatless() bool {
	var strangers []string
	for _, session := range tmux.Sessions(tmux.Own()) {
		if session.Mark == "1" {
			return false
		}
		strangers = append(strangers, session.Name)
	}
	return !marked(tmux.Default) && agent.Agentless(tmux.Own(), strangers)
}

func marked(server string) bool {
	return slices.ContainsFunc(tmux.Sessions(server), func(session tmux.Session) bool { return session.Mark == "1" })
}

// vote is the repo most of a seat's runs name, ties to the one whose project sorts first, as
// orch.session_projects infers one; null where none names one.
func vote(mine []ran) any {
	counts := map[string]int{}
	best := ""
	for _, each := range mine {
		if repo := each.record.Str("repo"); repo != "" {
			counts[repo]++
		}
	}
	for repo, count := range counts {
		if best == "" || count > counts[best] || count == counts[best] && (base(repo) < base(best) || base(repo) == base(best) && repo < best) {
			best = repo
		}
	}
	if best == "" {
		return nil
	}
	return best
}

// crew is a record's workers joined by commas, or why config._validate_session refuses them
// though each is a model; false where one is no model on a harness this reading follows.
func crew(workers any, models map[string]config.Model) (string, string, bool) {
	listed, isList := workers.([]any)
	if !isList && workers != nil {
		return "", "", false
	}
	if len(listed) == 0 {
		return "", "workers must be a non-empty list of model names", true
	}
	var names []string
	complaint := ""
	for _, each := range listed {
		name, ok := each.(string)
		if _, known := harness.Reopens(models[name].Harness); !ok || !known {
			return "", "", false
		}
		if slices.Contains(names, name) {
			complaint = "workers contains duplicates"
		}
		names = append(names, name)
	}
	return strings.Join(names, ","), complaint, true
}

// base is a path's last part as Python's Path.name reads it.
func base(path string) string {
	parts := slices.DeleteFunc(strings.Split(path, "/"), func(part string) bool { return part == "" || part == "." })
	if len(parts) == 0 {
		return ""
	}
	return parts[len(parts)-1]
}

func only(object *run.Object, fields []string) bool {
	return !slices.ContainsFunc(object.Keys(), func(key string) bool { return !slices.Contains(fields, key) })
}

// text is whether a value is null or a string.
func text(value any) bool {
	_, ok := value.(string)
	return ok || value == nil
}

// number is a finite number's value, 0 for null.
func number(value any) (float64, bool) {
	if value == nil {
		return 0, true
	}
	parsed, ok := run.Num(value)
	return parsed, ok && !math.IsNaN(parsed) && !math.IsInf(parsed, 0)
}

func at(value any) float64 {
	parsed, _ := number(value)
	return parsed
}

func seconds(now time.Time) float64 {
	return float64(now.UnixNano()) / 1e9
}
