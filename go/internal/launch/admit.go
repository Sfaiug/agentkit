package launch

import (
	"cmp"
	"errors"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strconv"

	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/host"
	"agentkit/internal/run"
	"agentkit/internal/worker"
)

// gated is whether Python's gate decides the launch of a run at that depth: its claim_slot lets a
// run's own run in outright, and every run under the tests' `AK_MAX_RUNS=0`.
func gated(depth int) bool {
	_, capped := config.MaxRuns()
	return capped == nil && os.Getenv("AK_MAX_RUNS") != "0" && depth == 0
}

// An admission is one poll for a run's slot, decided under the slots lock as Python's
// gate.claim_slot decides it: whether the run goes in, else why it waits, and the line the poll
// leaves in runs/.slots.queue.  A launch's first poll holds the lock from its decision until its
// receipt records it; each later poll is its driver's (waitSlot).
type admission struct {
	slots        *os.File
	id           string
	in, outright bool          // let in, and by no gate
	reason, kind string        // why it waits and the gate that holds it, no kind for a wait none counts
	running      int           // the other runs holding a slot
	waiting      []*run.Object // the runs waiting for one, this one among them, first in line first
	turns        []turn        // the seats' turns in that line
	room         *room         // the host's gates, where decide left them to ask (ask)
	stall        string        // the gate a run stalled first in line went past, Python's slot_stall
}

// A room is what the host's gates judge the run first in line by, asked where it reads history.db
// last of a poll: that reading writes beside it, so a launch asks once nothing can hand it over to
// Python, as its receipt records the poll (claim), past the base, whose finding may.
type room struct {
	readings         host.Readings
	holders          []*run.Object
	first            bool
	minimum, maximum float64
	saved            line
	poll             float64
	stalled          bool // its wait first in line a stall, judged as the poll saves the line
}

// admit is a launch's first poll for its slot, none for a launch no gate decides, ErrPython where
// Go leaves that poll to Python (decide), or, for a launch its own process follows, the wait that
// poll leaves (leftToPython): its driver would hand that wait over at once.
func admit(id string, first bool, seat string, depth int, followed bool) (*admission, error) {
	if !gated(depth) {
		return nil, nil
	}
	if err := os.MkdirAll(run.Runs(), 0o777); err != nil {
		return nil, err
	}
	slots, err := holdSlots()
	if err != nil {
		return nil, err
	}
	launching := run.Fields("run_id", id, "queued_at", now(), "notify_sink", sink())
	if first {
		launching.Set("first", true)
	}
	if seat != "" {
		launching.Set("launched_session", seat)
	}
	admitted, err := decide(launching)
	if err == nil && followed && admitted.leftToPython(launching) {
		err = ErrPython
	}
	if err != nil {
		slots.Close()
		return nil, err
	}
	admitted.slots = slots
	return admitted, nil
}

// decide is a poll for the run's slot as Python's gate.claim_slot decides it, under the slots lock:
// a run of a run, and every run under the tests' `AK_MAX_RUNS=0`, goes in outright; any other waits
// for those ahead of it in line and, unless it goes first, for the count, then for the host's room
// (ask), on the host's readings, read only where it is asked, as Python's gate._host_admits reads
// them.  ErrPython wherever Go would judge it otherwise, before anything is read that writes: a
// seat's run in line once a seat was told to go first (run.FirstPlaceTold); a queue, a poll, a
// config or a run Go reads otherwise than Python.
func decide(record *run.Object) (*admission, error) {
	if os.Getenv("AK_MAX_RUNS") == "0" || record.Truthy("run_depth") {
		return &admission{in: true, outright: true}, nil
	}
	at := now()
	poll, polled := slotPoll()
	limit, unread := config.MaxRuns()
	saved, read := queued()
	holders, others, alone := places(record)
	if !polled || unread != nil || !read || !alone {
		return nil, ErrPython
	}
	waiting, turns := inTurns(append([]*run.Object{record}, others...), saved.turns)
	if slices.ContainsFunc(waiting, func(other *run.Object) bool { return other.Truthy("launched_session") }) && run.FirstPlaceTold() {
		return nil, ErrPython
	}
	a := &admission{id: record.Str("run_id"), running: len(holders), waiting: waiting, turns: turns}
	ahead := slices.Index(waiting, record)
	first, green := !order(record)[0], greenDelivery(record)
	switch {
	case ahead > 0 && !green || limit > 0 && len(holders) >= limit && !first:
		a.reason, a.kind = slotLine(len(holders), ahead, limit, first), "count"
	case green:
		// it merges a tree its line checked already, spending no room a gate guards
		a.in = true
	default:
		readings := host.Read()
		minimum, maximum, err := readings.Limits(first)
		if err != nil {
			return nil, ErrPython
		}
		a.room = &room{readings, holders, first, minimum, maximum, saved, poll, saved.stalled(a.id, at, poll)}
	}
	if run.Historyless() {
		a.ask() // the room is asked now where it reads no history.db, whose reading writes beside it
	}
	return a, nil
}

// ask decides the run first in line by the host's room where decide left it, as Python's
// gate._host_admits: by its gates, or as stalled there (pastStall).
func (a *admission) ask() {
	r := a.room
	if r == nil {
		return
	}
	a.room = nil
	if r.stalled {
		a.pastStall(r)
		return
	}
	a.gates(r)
}

// gates decides the run first in line by the host's room, as Python's gate._gates_admit: a recent
// run's peak against memory, less what the runs let in that show nothing yet may still take, the
// load where pinned, and, with no peak measured, a poll since the last run let in, for steady
// readings.
func (a *admission) gates(r *room) {
	at := now()
	db := history.Look()
	defer db.Close()
	peak, measured := db.RecentPeak(at)
	var starting host.Starting
	if measured {
		starting = growth(r.holders, peak, r.poll, at, db)
	}
	reason, kind := r.readings.Hold(r.minimum, r.maximum, peak, measured, starting, func() int {
		return len(slices.DeleteFunc(slices.Clone(r.holders), func(holder *run.Object) bool {
			pid, _ := holder.Int("pid")
			return !host.Frozen(pid)
		}))
	})
	switch since := at - r.saved.lastIn; {
	case reason != "":
		a.reason, a.kind = reason, kind
	case !measured && 0 <= since && since < r.poll:
		a.reason = r.readings.Unsteady()
	default:
		a.in = true
	}
}

// growth is what the runs holding a slot that show nothing yet may still grow by, and how many
// may, Python's gate._starting: a recent run's median peak less each one's own peak so far.
func growth(holders []*run.Object, peak, poll, at float64, db *history.DB) host.Starting {
	var showing []string
	for _, holder := range holders {
		if showsNothingYet(holder, poll, at) {
			showing = append(showing, holder.Str("run_id"))
		}
	}
	soFar := db.SoFar(showing)
	var starting host.Starting
	for _, id := range showing {
		if mb := peak - soFar[id]; mb > 0 {
			starting.MB += mb
			starting.Runs++
		}
	}
	return starting
}

// showsNothingYet is whether a run holding a slot has launched no worker since it went in, or its
// last under six polls ago, Python's gate._shows_nothing_yet: till then the readings lag what it holds.
func showsNothingYet(holder *run.Object, poll, at float64) bool {
	info, err := os.Stat(filepath.Join(run.Runs(), holder.Str("run_id"), worker.Launched))
	if err != nil {
		return true
	}
	launched := float64(info.ModTime().UnixNano()) / 1e9
	started, _ := holder.Num("slot_started_at")
	return launched < started || at-launched < 6*poll
}

// places is the other top-level runs holding a slot and those waiting for one, a dead waiter
// among them, as Python's gate.slot_place reads them; false where the runs cannot be read.
func places(record *run.Object) (holders, waiting []*run.Object, read bool) {
	read = run.Every(func(_ string, other *run.Object) bool {
		switch {
		case run.Equal(other.Get("run_id"), record.Get("run_id")) || other.Truthy("run_depth"):
		case other.Str("state") == "running" && run.ProcessActive(other):
			holders = append(holders, other)
		case other.Str("state") == "queued" && other.Truthy("slot_waiting"):
			waiting = append(waiting, other)
		}
		return true
	})
	return holders, waiting, read
}

// order is the head of Python's gate.slot_order for a run Go carries, update.first_place aside,
// which only a seat's run holds (run.FirstPlaceTold): whether it waits behind the runs going first
// (`--first`, a member's landing or fix), behind green deliveries, and behind finished work (a
// later round, or an orchestrator's own pull request).
func order(record *run.Object) [3]bool {
	return [3]bool{!(record.Truthy("first") || waitsOn(record, "land") || waitsOn(record, "fix")),
		!greenDelivery(record), !(record.Truthy("round_summaries") || record.Truthy("own_pr"))}
}

// inLine is Python's gate.slot_order between two waiters: by order, then by when each entered the
// line, then by name.
func inLine(a, b *run.Object) int {
	return cmp.Or(heads(a, b), cmp.Compare(firstQueued(a), firstQueued(b)), cmp.Compare(a.Str("run_id"), b.Str("run_id")))
}

// heads is two waiters by order alone.
func heads(a, b *run.Object) int {
	x, y := order(a), order(b)
	for i := range x {
		if c := cmp.Compare(behind(x[i]), behind(y[i])); c != 0 {
			return c
		}
	}
	return 0
}

func behind(waits bool) int {
	if waits {
		return 1
	}
	return 0
}

// firstQueued is when the run entered the line, its start for an older record, Python's
// transitions.first_queued.
func firstQueued(record *run.Object) float64 {
	for _, key := range []string{"queued_at", "started_at"} {
		if at, ok := record.Num(key); ok && at != 0 {
			return at
		}
	}
	return 0
}

// waitsOn is whether the run's waits name that one.
func waitsOn(record *run.Object, wait string) bool {
	waits := record.Dict("waiting_on")
	return waits != nil && waits.Has(wait)
}

// greenDelivery is Python's land.green_delivery: a member whose line found it green, which only
// needs delivering before its target moves.
func greenDelivery(record *run.Object) bool {
	return waitsOn(record, "land") && !waitsOn(record, "fix")
}

// slotLine is the count wait's sentence, Python's gate.slot_line: a full count says so, beside how
// many wait ahead in line; a run going first waits on the line alone.
func slotLine(running, ahead, limit int, first bool) string {
	if limit > 0 && running >= limit && !first {
		return "waiting for a slot · limit full (" + strconv.Itoa(running) + " running) · " + strconv.Itoa(ahead) + " ahead"
	}
	return "waiting for a slot · " + strconv.Itoa(ahead) + " ahead"
}

// settle writes the poll's decision on the run's record as Python's claim_slot leaves it, the
// host's room asked first where the decision waits on it: let in, the run holds its slot from now;
// held, it says why, and that it waited where a gate held it; let in on a stall past one, both,
// and the gate it went past.
func (a *admission) settle(record *run.Object) {
	a.ask()
	if !a.outright && a.kind != "count" {
		record.Delete("slot_stall") // each poll past the count judges the stall anew
	}
	switch {
	case a.kind != "":
		run.SetAll(record, "slot_waited", true, "slot_wait_reason", a.reason, "slot_wait_kind", a.kind)
	case a.reason != "":
		record.Set("slot_wait_reason", a.reason)
	}
	if !a.in {
		return
	}
	if a.stall != "" {
		record.Set("slot_stall", a.stall)
	}
	run.SetAll(record, "state", "running", "slot_waiting", false, "slot_started_at", now())
	record.Delete("resume_from")
	if !a.outright {
		for _, key := range []string{"reservation_pending", "slot_wait_reason", "slot_wait_kind"} {
			record.Delete(key)
		}
	}
}

// save leaves runs/.slots.queue as the poll's gate.slot_counts leaves it, the run in line, and
// where the run went in, as its gate._save_queue then does, the run let in.
func (a *admission) save() error {
	if a.outright {
		return nil
	}
	if err := saveLine(a.running, a.waiting, a.turns, nil); err != nil || !a.in {
		return err
	}
	let := slices.IndexFunc(a.waiting, func(other *run.Object) bool { return other.Str("run_id") == a.id })
	return saveLine(a.running+1, slices.Delete(slices.Clone(a.waiting), let, let+1), a.turns, a.waiting[let])
}

// release lets the slots lock go, where the admission still holds it.
func (a *admission) release() {
	if a != nil && a.slots != nil {
		a.slots.Close()
		a.slots = nil
	}
}

// A line is runs/.slots.queue as Python's gate.slot_queue reads it: when the last poll saved it,
// the runs then holding a slot, the waiters first in line first, since when that first has waited
// there, the waits there of the last firsts let in, each seat's turns, and when the last run went in.
type line struct {
	at, since, lastIn float64
	running           int
	queue             []string
	took              []float64
	turns             map[seatKey]turn
}

// queued is the line runs/.slots.queue holds, none where it holds no queue; false where it holds
// one in a shape Python's gate never writes, which Go might read otherwise.
func queued() (line, bool) {
	saved, err := run.ReadJSON(filepath.Join(run.Runs(), ".slots.queue"))
	if saved == nil {
		return line{}, !errors.Is(err, run.ErrLoneSurrogate)
	}
	queue, listed := saved.Get("queue").([]any)
	waits, timed := saved.Get("took").([]any)
	turns, kept := saved.Get("turns").([]any)
	since, sinceRead := optional(saved.Get("since"))
	lastIn, last := optional(saved.Get("last_in"))
	at, dated := run.Num(saved.Get("at"))
	if !dated || !whole(saved.Get("running")) || !listed || !sinceRead || !last ||
		!timed && saved.Get("took") != nil || !kept && saved.Has("turns") ||
		slices.ContainsFunc(queue, func(id any) bool { _, text := id.(string); return !text }) ||
		slices.ContainsFunc(waits, func(wait any) bool { _, number := wait.(run.Number); return !number }) ||
		slices.ContainsFunc(turns, malformedTurn) {
		return line{}, false
	}
	running, _ := saved.Int("running")
	read := line{at: at, since: since, lastIn: lastIn, running: running, turns: map[seatKey]turn{}}
	for _, listed := range turns {
		parts := listed.([]any)
		if len(parts) != 7 {
			continue // which Python reads past
		}
		each := turn{seat: seatKey{[3]bool{parts[0].(bool), parts[1].(bool), parts[2].(bool)}, parts[3].(string), parts[4].(string)}}
		each.count, _ = strconv.Atoi(string(parts[5].(run.Number)))
		for _, id := range parts[6].([]any) {
			if text, ok := id.(string); ok {
				each.pending = append(each.pending, text)
			}
		}
		read.turns[each.seat] = each // the last of a seat's, as Python's dict keeps it
	}
	for _, id := range queue {
		read.queue = append(read.queue, id.(string))
	}
	for _, wait := range waits {
		took, _ := run.Num(wait)
		read.took = append(read.took, took)
	}
	return read, true
}

// SlotQueue is the runs waiting for a slot, first in line first, as the last poll left them
// (queued); false where Go reads the queue otherwise than Python.
func SlotQueue() ([]string, bool) {
	saved, read := queued()
	return saved.queue, read
}

// firstInLine is the run first in line and since when it has waited there, Python's
// gate.first_in_line: false after a gap in the polling, three polls past the last in line counting
// it again (waiter.stale_after), which begins a new wait.
func (l line) firstInLine(now, poll float64) (string, float64, bool) {
	if len(l.queue) == 0 || l.since == 0 || now-l.at >= float64(len(l.queue))*poll+3*poll {
		return "", 0, false
	}
	return l.queue[0], l.since, true
}

// stalled is whether the run has waited first in line so long its wait is a stall, Python's
// stuck.slot_stall: three times the usual wait of the last firsts let in, and half an hour at least.
func (l line) stalled(id string, now, poll float64) bool {
	first, since, waits := l.firstInLine(now, poll)
	if !waits || first != id {
		return false
	}
	usual := 30 * 60.0
	if len(l.took) >= 3 {
		took := slices.Sorted(slices.Values(l.took))
		middle := float64(len(took)-1) / 2
		usual = math.Max(usual, 3*(took[int(math.Floor(middle))]+took[int(math.Ceil(middle))])/2)
	}
	return now-since > usual
}

// saveLine writes runs/.slots.queue as Python's gate._save_queue does under the slots lock: the
// runs holding a slot, those waiting first in line first, the seats' turns, the one let in counting
// a turn of its seat's, since when the first has waited there, the waits there of the last 20
// firsts let in, none let in on a stall, and when the last went in.
func saveLine(running int, waiting []*run.Object, turns []turn, let *run.Object) error {
	letIn := ""
	if let != nil {
		letIn = let.Str("run_id")
	}
	at := now()
	poll, _ := slotPoll()
	saved, _ := queued()
	first, since, waits := saved.firstInLine(at, poll)
	took := saved.took
	// a stall's wait is no pace: counted, each one let in would raise the next one's bar
	if waits && letIn != "" && letIn == first && !let.Truthy("slot_stall") {
		took = append(took, at-since)
		took = took[max(0, len(took)-20):]
	}
	if !waits || len(waiting) == 0 || waiting[0].Str("run_id") != first {
		since = at
	}
	lastIn := saved.lastIn
	if letIn != "" {
		lastIn = at
	}
	queue, kept, waited := []any{}, []any{}, []any{}
	for _, other := range waiting {
		queue = append(queue, other.Str("run_id"))
	}
	for _, each := range turns {
		pending := []any{}
		for _, id := range each.pending {
			if slices.Contains(queue, any(id)) {
				pending = append(pending, id)
			}
		}
		if let != nil && keyOf(let) == each.seat {
			each.count++
		}
		if len(pending) > 0 {
			head := each.seat.head
			kept = append(kept, []any{head[0], head[1], head[2], each.seat.seat, each.seat.own, run.Number(strconv.Itoa(each.count)), pending})
		}
	}
	for _, wait := range took {
		waited = append(waited, run.Float(wait))
	}
	text := run.Line(run.Fields("at", at, "running", running, "queue", queue, "since", since,
		"took", waited, "last_in", lastIn, "turns", kept))
	temp := filepath.Join(run.Runs(), ".slots.queue.tmp")
	if err := os.WriteFile(temp, []byte(text), 0o666); err != nil {
		return err
	}
	return os.Rename(temp, filepath.Join(run.Runs(), ".slots.queue"))
}

// optional is a number the queue may leave out, 0 for none.
func optional(value any) (float64, bool) {
	if value == nil {
		return 0, true
	}
	return run.Num(value)
}

// whole is whether the value is a JSON integer, as Python's gate writes a count.
func whole(value any) bool {
	number, ok := value.(run.Number)
	_, err := strconv.Atoi(string(number))
	return ok && err == nil
}

// malformedTurn is whether a seat's turns in the queue are other than Python writes them: a list,
// whose seven-long ones key a seat by its head's three switches, its seat and its own name, then
// count its turns and list its waiters.
func malformedTurn(turn any) bool {
	parts, ok := turn.([]any)
	if !ok {
		return true
	}
	if len(parts) != 7 {
		return false
	}
	_, waiters := parts[6].([]any)
	_, seat := parts[3].(string)
	_, own := parts[4].(string)
	return !whole(parts[5]) || !waiters || !seat || !own || slices.ContainsFunc(parts[:3], func(part any) bool {
		_, switched := part.(bool)
		return !switched
	})
}

// claim records the launch's first poll on its receipt, as Python's capture_launch writes a receipt,
// queued, and its first poll then leaves it: let in, it holds its slot; held, it waits for its
// driver to poll again.  Then the line that poll leaves, and the receipt, and the slots lock goes.
func (a *admission) claim(dir string, record *run.Object) error {
	defer a.release()
	run.SetAll(record, "state", "queued", "slot_waiting", true)
	record.Delete("slot_started_at")
	a.settle(record)
	if err := a.save(); err != nil {
		return err
	}
	return run.Create(dir, record)
}
