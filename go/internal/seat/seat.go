// Package seat is what Go knows of the seats, and hides what a seat is: its record, written as
// Python writes it under Python's locks, its session on ak's tmux server, and ak's shims first
// on its harness's PATH; opening, reopening, stopping, renaming and reading one all go through here. Read
// takes the home in once, into the seats it knows or a no wherever Python's answer hangs on
// anything that reading leaves out, and decides each word from that reading alone; each later
// piece widens what Read knows, here.
package seat

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"maps"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/lock"
	"agentkit/internal/machines"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
	"agentkit/internal/tmux"
	usages "agentkit/internal/usage"
)

// A Seat is one as Python's orch.listing offers it, whether only its record holds it or tmux does,
// with the word and tally its runs give it, or its screen where its panes run on
// (watch.session_state, handback.seat_tallies).
type Seat struct {
	Name, Project, Word, Tally, Orchestrator, Workers string
	Warning                                           string // why its record's models read as `?`
	Created                                           float64
	reason, restart                                   string
	since, repo                                       any
	infer                                             bool     // the record holds no repo
	unowned                                           bool     // its harness owns no conversation: only the owner's close can keep its row
	closed                                            bool     // its seat file holds the owner's stop mark
	held                                              bool     // tmux still holds its session, all its panes dead
	live                                              bool     // a pane of its session still runs: its screen says what it is
	legacy                                            bool     // tmux holds it on the person's default server, from before ak had its own
	own                                               string   // the harness its screen is read as
	question                                          bool     // its reason is the question its screen shows, not for the bar to repeat
	back                                              any      // when it comes back, out of usage
	unsent                                            string   // what nobody sent, left in its composer
	wordFrom                                          []any    // what its word was decided from (watch.word_from), none for one nobody is in
	asleep                                            bool     // put to sleep since its harness launched (sleep.asleep)
	handBacks                                         int      // its runs' hand-backs waiting on the owner's reopening it
	home                                              []string // where the menu files it (orch.home_key)
	follow                                            move     // what its last answer moves in its record
	mine                                              []ran    // its own runs, which its ladder reads

	reader harness.Reader
	path   string
	seen   sight
}

// A Home is what Read knows: the seats with rows, in Python's order, and the seat of every
// record, row or not, for what the listing writes into it.
type Home struct {
	Seats   []Seat
	records []Seat
	models  map[string]config.Model
	readers recordReaders
}

type recordReaders map[string]harness.Reader

// Seatless is whether the home holds no record at all.
func (home Home) Seatless() bool { return len(home.records) == 0 }

// kinds are the files state/ may hold for a seat, by kind: its record and its lock, its seat
// file's, its typing lock, and the plan of a seat the owner stopped, whose word no plan decides.
var kinds = map[string][]string{"session": {"json"}, ".session": {"lock"}, "seat": {"json", "lock", "announce"}, "notify": {"lock"},
	"plan": {"md"}, "handover": {"md"}, "verify": {"lock"}}

var (
	// a record's keys: those a word or a row reads, what its looks read beside them (`account`, whose
	// login its conversation is under; `asleep` since `launched`), and those no reading of it hangs on
	recordFields = []string{"orchestrator", "workers", "reviewers", "efforts", "cwd", "created", "conversation", "id_source", "resumable", "session_title", "repo",
		"account", "home_account", "launched", "asleep", "seen", "exited_since", "unnamed", "filed", "owner_words_cursor",
		"rulebook_sha", "rulebook_read", "rulebook_told", "title_sync", "title_superseded"}
	seatFields = slices.Concat([]string{"word", "reason", "unsent", "word_since", "word_from", "session", "stopped_at", "closed_by_owner", "unasked"}, waits, screenFields)
	// what Python's look at a seat's screen keeps beside its word, which no seat nobody is in reads
	screenFields = []string{"state", "rule", "since", "began", "hooks", "hooked", "hooked_at", "hooked_event", "interrupted", "authority", "evidence",
		"stall", "login", "turn_began", "stop_said", "stop_said_at", "opened_at"}
	runFields = []string{"run_id", "title", "repo", "started_at", "finished_at", "state", "merged", "launched_session"}
)

// A ran is one of a seat's runs: its directory's name, its record, and how long since run.json
// was written.
type ran struct {
	name   string
	record *run.Object
	quiet  float64
	view   *runView
}

// Read is the home, and whether Go knows it: no record where milestone 6b found none, else
// only seats on no tmux server or whose panes have all died there, with records, seat files and
// runs it follows.  Looking also takes seats whose panes run on.
func Read(now time.Time) (Home, bool) { return reading(now, false, readRuns, nil) }

// Looking is Read with seats whose panes still run among them, where Go reads their screens.
func Looking(now time.Time) (Home, bool) { return reading(now, true, lookRuns, nil) }

func reading(now time.Time, looking bool, readRuns func([]string, time.Time) (map[string][]ran, bool), readers recordReaders, pending ...bool) (Home, bool) {
	began := time.Now()
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
	held, live, bare, gone := onServer(state, names)
	if len(names) == 0 && len(bare) == 0 {
		return Home{}, gone
	}
	for _, name := range slices.Sorted(maps.Keys(bare)) {
		names = append(names, name)
	}
	for _, entry := range entries {
		// Python's cache of runs/, which Go reads itself, the cards on their way, the template every
		// home is given, the usage the screen's grid shows and what reading it keeps, the tick's
		// lock, its log's, its page that ticks stopped ending and the hourly stamps of its reads, the
		// outages of the seats' products, what the collection keeps, what each machine is and ak's tmux
		// config say nothing a word hangs on: a seat's own wait on its usage is in its seat file
		if harness.KeptInState(entry.Name()) || menuNewsState(entry.Name()) || entry.Name() == "watch.lock" || entry.Name() == "statusbar.lock" || strings.HasPrefix(entry.Name(), "run-records.db") ||
			slices.Contains([]string{"watch.tick.lock", "watch.log.lock", "watch.tick.page.json", "watch.tick.page.lock", "retire.json", "alive.json", "nightly.json", "runs-moved", "setup", "logins.json", "logins.tmp", ".logins.lock", "tmux.conf"}, entry.Name()) ||
			strings.HasPrefix(entry.Name(), "gc.") || strings.HasPrefix(entry.Name(), "gc-") ||
			entry.Name() == "notification-outbox" || entry.Name() == "installed-at" || entry.Name() == "task-template.md" || entry.Name() == "audit" || entry.Name() == "audit.json" || usages.Owns(entry.Name()) || machines.Owns(entry.Name()) || recommendationState(entry.Name()) ||
			entry.Name() == "watch.json" && quiet(filepath.Join(state, "watch.json")) {
			continue
		}
		kind, rest, _ := strings.Cut(entry.Name(), "-")
		name, suffix, _ := strings.Cut(rest, ".")
		// a seat removed leaves its locks, which writers hold or wait on, and its stop mark, which
		// no listing reads (forget); one tmux no longer holds leaves its announce lock, its word and
		// its card, which the tick closes (notify.tick_cards), and what it asked the owner last, an
		// orphan ending's question among them (handback.announce)
		if !slices.Contains(names, name) && entry.Type().IsRegular() &&
			(suffix == "lock" || kind == "seat" && (suffix == "json" || suffix == "announce") || (kind == "card" || kind == "notify") && suffix == "json") {
			continue
		}
		if entry.IsDir() || !slices.Contains(names, name) || name == "" || config.SessionName(name) != name ||
			!slices.Contains(kinds[kind], suffix) && !launchKind(kind, suffix) && !goneKind(kind, suffix) && !goneQuestionKind(kind, name, suffix) && !revivalKind(kind, suffix) &&
				!pastKind(state, name, kind, suffix) && !(slices.Contains(live, name) && looksKind(kind, suffix)) {
			return Home{}, false
		}
	}
	models, err := config.Models()
	offered, unread := config.Offered()
	// the runs are judged as they are read: one that ended while this reading asked tmux would
	// otherwise have ended in its clock's future, which no admission takes
	runs, known := readRuns(names, now.Add(time.Since(began)))
	if err != nil || unread != nil || !known || !gone || !looking && len(live)+len(bare) > 0 {
		return Home{}, false
	}
	home := Home{models: models, readers: recordReaders{}}
	stands := sync.OnceValue(listed)
	for _, name := range names {
		if server, ok := bare[name]; ok {
			seat, ok := bareSeat(state, name, server, runs[name], now)
			if !ok {
				return Home{}, false
			}
			seat.home = homeKey("", stands)
			home.Seats = append(home.Seats, seat)
			continue
		}
		isLive := slices.Contains(live, name)
		deferred := isLive && len(pending) > 0 && pending[0]
		seat, ok := read(state, name, models, offered, runs[name], now, isLive, readers, deferred)
		if !ok {
			return Home{}, false
		}
		seat.held, seat.live = slices.Contains(held, name), isLive
		if seat.live {
			facts := climbingOf(state, seat, sight{}, seconds(now))
			if deferred {
				facts = accountClimbing(facts)
			}
			if !seat.looksOn(seat.own) || !facts.readable() {
				return Home{}, false
			}
		}
		if seat.held || seat.live {
			// tmux offers its row whatever its record owns, dates it by its own start where the
			// record does not, and its bar shows the squares of any run going
			record, _ := run.ReadJSON(filepath.Join(state, "session-"+name+".json"))
			if at(record.Get("created")) == 0 {
				return Home{}, false
			}
			seat.unowned = false
		}
		home.records = append(home.records, seat)
		home.readers[name] = seat.reader
		if !seat.unowned || seat.closed || seat.waitingQuestion() {
			repo, _ := seat.repo.(string)
			seat.home = homeKey(repo, stands)
			home.Seats = append(home.Seats, seat)
		}
	}
	order(home.Seats)
	for i := range home.Seats {
		if !home.Seats[i].live {
			if err := home.Seats[i].goneAt(state, i+1, now); err != nil {
				return Home{}, false
			}
		}
	}
	return home, true
}

// order puts seats in their menu order (orch.numbered): the ones the owner stopped last, for the
// past screen, one whose session tmux still holds being no past seat.
func order(seats []Seat) {
	past := func(seat Seat) int {
		if seat.closed && !seat.held {
			return 1
		}
		return 0
	}
	slices.SortFunc(seats, func(a, b Seat) int {
		return cmp.Or(cmp.Compare(past(a), past(b)), slices.Compare(a.home, b.home), cmp.Compare(a.Created, b.Created), cmp.Compare(a.Name, b.Name))
	})
}

// onServer is the seats of those names tmux holds, the ones whose panes have all died and the rest,
// the bare seats it holds under names no record keeps, each by its server, and whether Go knows
// them all: a record's seat on the default server, whose screen Go does not read there, and a
// bare one whose panes have all died or under a name no seat can have are Python's.
func onServer(state string, names []string) (held, live []string, bare map[string]string, known bool) {
	_, seats := holdings(state)
	bare = map[string]string{}
	dead := map[string][]string{}
	for name, server := range seats {
		if _, asked := dead[server]; !asked {
			dead[server] = tmux.Dead(server)
		}
		exited := slices.Contains(dead[server], name)
		switch {
		case !slices.Contains(names, name):
			if exited || config.SessionName(name) != name {
				return nil, nil, nil, false
			}
			bare[name] = server
		case server == tmux.Default:
			return nil, nil, nil, false
		case exited:
			held = append(held, name)
		default:
			live = append(live, name)
		}
	}
	return held, live, bare, true
}

// read is the seat one record holds, from it, its seat file and its runs.  `live` is whether its
// panes run on, whose look reads more of its seat file.
func read(state, name string, models map[string]config.Model, offered []string, mine []ran, now time.Time, live bool, readers recordReaders, deferred bool) (Seat, bool) {
	record, err := run.ReadJSON(filepath.Join(state, "session-"+name+".json"))
	if err != nil || record == nil {
		return Seat{}, false
	}
	seat, known := recorded(state, name, record, models, readers)
	if !known || !only(record, slices.Concat(recordFields, launchKeys, harness.RecordKeys(models[record.Str("orchestrator")].Harness))) {
		return Seat{}, false
	}
	previous, err := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	fields := slices.Concat(seatFields, lookFields)
	if err != nil && !errors.Is(err, fs.ErrNotExist) || err == nil && (previous == nil || !only(previous, fields)) ||
		!live && previous != nil && previous.Get("unasked") != nil {
		return Seat{}, false
	}
	if seat.Warning == "" && !seat.unowned { // only an owned conversation can move its record
		if seat.follow, known = follows(record, previous, models, offered, seat.reader); !known {
			return Seat{}, false
		}
	}
	stopped := revivalStopped
	if deferred {
		stopped = liveStopped
	} else if live {
		stopped = waitingStopped
	}
	if seat.closed, known = stopped(previous); !known {
		return Seat{}, false
	}
	if seat.closed && seat.unowned {
		seat.restart = "starts fresh"
	}
	seat.asleep, seat.mine = putToSleep(record, previous), mine
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
	seat.Tally = tally(mine, now)
	return seat, true
}

// recorded reads a record and freezes its harness's evidence at the listing's reconciliation
// boundary; later reads reuse that evidence. False leaves the listing to Python.
func recorded(state, name string, record *run.Object, models map[string]config.Model, readers recordReaders) (Seat, bool) {
	if selected, err := configSelection(record, models); err == nil {
		record = selected
	}
	own := models[record.Str("orchestrator")].Harness
	restart, known := harness.Reopens(own)
	workers, complaint, crewed := recordCrew(record, models)
	created, dated := number(record.Get("created"))
	if !known || !crewed || !dated || !text(record.Get("cwd")) || !text(record.Get("repo")) ||
		!text(record.Get("conversation")) {
		return Seat{}, false
	}
	reader, cached := readers[name]
	if readers == nil {
		// This is Go's orch.records boundary: all evidence is frozen before Announce or
		// Explain writes any record. Reads under announce locks reuse it, never reconcile again.
		reader, known = harness.For(own).Reconciled(name, record)
	} else {
		known = cached && reader.Name == own
	}
	if !known {
		return Seat{}, false
	}
	if owned, _ := reader.Owns(record, record.Str("conversation")); owned {
		restart = ""
	}
	// what a record naming reviewers may hold otherwise is config._validate_session's to judge
	if record.Has("reviewers") {
		if _, problem, named := crew(record.Get("reviewers"), models); !named || problem != "" || complaint != "" {
			return Seat{}, false
		}
	}
	seat := Seat{Name: name, Word: "idle", Tally: "no runs yet", Orchestrator: record.Str("orchestrator"), Workers: workers,
		Created: created, restart: restart, repo: record.Get("repo"), infer: !record.Has("repo"),
		own: own, reader: reader, path: record.Str("cwd"), unowned: restart == "" && !conversationOwned(reader, record)}
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
		record, err := run.Read(dir)
		if err != nil || record == nil || !only(record, runFields) {
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
			mine[seat] = append(mine[seat], ran{name: entry.Name(), record: record, quiet: silence(dir, record, now)})
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

// Announce publishes the listing using the evidence frozen by reading, under Python's locks.
func (home Home) Announce(now time.Time) error {
	state := filepath.Join(config.Home(), "state")
	for at, seat := range home.Seats {
		if seat.live { // its look decides its word, which every reader of this home reads
			looked, err := lookedLive(state, seat.Name, home.readers)
			if err != nil {
				return err
			}
			home.Seats[at] = looked
		}
	}
	if err := reconcile(state, home.records, true); err != nil {
		return err
	}
	for _, seat := range home.Seats {
		if !seat.live {
			if err := seat.announce(state, now, home.models); err != nil {
				return err
			}
		}
	}
	return nil
}

// reconcile writes into each seat's record what Python's orch.records reconciles before anything
// claims it resumable, and with `infer` the project orch.session_projects infers for one that
// names none.
func reconcile(state string, records []Seat, infer bool) error {
	for _, seat := range records {
		if harness.RecordReadOnly(seat.own) {
			continue
		}
		var fields []field
		if seat.restart != "" && !seat.unowned {
			fields = append(fields, field{"resumable", false})
		}
		if infer && seat.infer {
			fields = append(fields, field{"repo", seat.repo})
		}
		if len(fields) == 0 && !seat.unowned {
			continue
		}
		if err := update(state, seat.Name, seat.reconciled(fields)); err != nil {
			return err
		}
	}
	return nil
}

// announcing is one decision and publication of that seat at a time (watch.announcing).
func announcing(state, name string, tell func() error) error {
	if err := config.EnsureDirs(); err != nil {
		return err
	}
	held, err := lock.Wait(context.Background(), filepath.Join(state, "seat-"+name+".announce"))
	if err != nil {
		return err
	}
	defer held.Close()
	return tell()
}

// announce publishes what a reading found under the seat's announce lock. One tmux holds is looked
// at again there, as a look's other announcers may have moved it since the reading.
func (seat Seat) announce(state string, now time.Time, models map[string]config.Model) error {
	if seat.held {
		return lookAgain(state, seat.Name)
	}
	return announcing(state, seat.Name, func() error { return seat.announced(state, now, models) })
}

// announced is watch.announce_state for a seat nobody is in, under its announce lock: what its
// last answer moved (watch.follow_model), then its word, begun where the seat file says it began by then, or now
// where it said another, and for one tmux still holds its bar.
func (seat *Seat) announced(state string, now time.Time, models map[string]config.Model) error {
	if err := seat.moved(state, models); err != nil {
		return err
	}
	return seat.published(state, now, models)
}

// published is announced's word and bar, what its last answer moved left as it is.
func (seat *Seat) published(state string, now time.Time, models map[string]config.Model) error {
	path := filepath.Join(state, "seat-"+seat.Name+".json")
	previous, _ := run.ReadJSON(path)
	if previous == nil {
		previous = run.NewObject()
	}
	since := begun(previous, seat.Word, seat.since, now)
	seat.since = since
	wordFrom := seat.wordFrom
	if wordFrom == nil {
		wordFrom = []any{nil, nil, ""}
	}
	fields := []field{{"word", seat.Word}, {"reason", seat.reason}, {"unsent", seat.unsent}, {"word_since", since}, {"word_from", wordFrom}}
	if slices.ContainsFunc(fields, func(f field) bool {
		if f.key == "unsent" && !previous.Truthy("unsent") { // `or ""`: any false value is no draft
			return seat.unsent != ""
		}
		return !run.Equal(previous.Get(f.key), f.value)
	}) {
		if err := writeSeat(state, seat.Name, fields); err != nil {
			return err
		}
	}
	if seat.held || seat.live {
		seat.publish(state, models, !run.Equal(previous.Get("word"), seat.Word))
	}
	return nil
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
	return under(held, func() error { return rewrite(path, encode, start, change) })
}

// rewrite is put's change, under a lock its caller holds.
func rewrite(path string, encode func(any) string, start bool, change func(data *run.Object) bool) error {
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
	return replace(path, []byte(encode(data)+"\n"))
}

// replace lands a whole file over path, through a temporary file beside it.
func replace(path string, data []byte) error {
	tmp := strings.TrimSuffix(path, ".json") + ".tmp"
	if err := os.WriteFile(tmp, data, 0o666); err != nil {
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
// though each is a model; false where one is no configured model. Only the orchestrator needs a
// harness whose seat this reading can follow: a worker's full name is all a row reads.
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
		if _, known := models[name]; !ok || !known {
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
