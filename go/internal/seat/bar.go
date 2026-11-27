package seat

import (
	"context"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/motion"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
	"agentkit/internal/tmux"
)

// The seat's status bar, as agentkit/statusbar.py writes it: its text is data in the session's own
// options, and two fixed formats draw them, so each client picks what fits its own width.
const (
	barHit     = "@ak_hit"
	barNeed    = "@ak_need"
	barFold    = "@ak_fold"
	barNeedLit = "@ak_need_lit"
	barFoldLit = "@ak_fold_lit"
	barNews    = "@ak_news"
	barKey     = "@ak_key"
	barTop     = "@ak_top"
	barWhy     = "@ak_why"
	// where the pointer is: its cells counted from the client's right edge, the right end's own edge
	barAt = "#{e|-:#{client_width},#{mouse_x}}"
)

var (
	barCells = []int{36, 24, 12} // a progress line and its count, at each width of line one
	barTops  = []string{barTop, barTop + "1", barTop + "2"}
	// line two: every task's squares and who builds and reviews, then those squares alone; again with
	// them cut to six, then to one (Seat.whys)
	barWhys = []string{barWhy, barWhy + "1", barWhy + "2", barWhy + "3", barWhy + "4", barWhy + "5"}
	// the one key ak binds on the bar: a click on its right end switches to the seat it names
	barClick = []string{"bind-key", "-n", "MouseDown1StatusRight", "if-shell", "-F", "#{E:" + barHit + "}",
		"run-shell -C \"switch-client -t '#{E:" + barHit + "}'\""}
)

// barCut is that option cut to room cells and the `…` tmux adds past them, the cell every caller's
// room leaves it; nothing where not one cell is left, since tmux reads a limit of 0 as none and a
// negative one as the line's tail, and one forced would push into what is beside it; its styles end
// with it, as tmux drops those after its last cell, the chip's end among them (statusbar._cut).
func barCut(option, room string) string {
	return "#{?#{e|>:" + room + ",0},#{=/" + room + "/…:" + option + "}#[default],}"
}

// barEndFormat is that right end, lit while barNews is set on the server (statusbar._end).
func barEndFormat(option string) string {
	lit := map[string]string{barNeed: barNeedLit, barFold: barFoldLit}[option]
	return "#{?#{" + barNews + "},#{" + lit + "},#{" + option + "}}"
}

// barLineOne is the widest progress line beside who else needs you that fits the client, drawn
// whole, then beside its short count; else the narrowest cut a space short of that.
func barLineOne() string {
	room := "#{e|-:#{client_width},#{e|+:#{w:" + barFold + "},2}}"
	found := "#[align=left]" + barCut(barTops[len(barTops)-1], room) + " #[align=right]" + barEndFormat(barFold)
	for _, right := range []string{barFold, barNeed} {
		for _, left := range slices.Backward(barTops) {
			fits := "#{e|<=:#{e|+:#{w:" + left + "},#{e|+:#{w:" + right + "},2}},#{client_width}}"
			whole := "#[align=left]#{" + left + "} #[align=right]" + barEndFormat(right)
			found = "#{?" + fits + "," + whole + "," + found + "}"
		}
	}
	return found
}

// barLineTwo is line two a space short of the key, so the key stays whole on every client: the most
// squares that fit, then the crew -- whole where it fits, else cut where the three cells after the
// squares and one of its own fit, so its `…` never reads as a cut square, else not drawn; the
// fewest squares cut where not even they fit (statusbar._line_two).
func barLineTwo() string {
	room := "#{e|-:#{client_width},#{e|+:#{w:" + barKey + "},2}}"
	found := barCut(barWhys[len(barWhys)-1], room)
	for i := len(barWhys) - 2; i >= 0; i -= 2 {
		crewed, alone := barWhys[i], barWhys[i+1]
		found = "#{?#{e|<=:#{w:" + crewed + "}," + room + "},#{" + crewed + "}," +
			"#{?#{e|<:#{e|+:#{w:" + alone + "},3}," + room + "}," + barCut(crewed, room) + "," +
			"#{?#{e|<=:#{w:" + alone + "}," + room + "},#{" + alone + "}," + found + "}}}"
	}
	return "#[align=left]" + found + " #[align=right]#{" + barKey + "}"
}

func tmuxText(text string) string { return strings.ReplaceAll(text, "#", "##") }

func barPaint(text, word string) string {
	if text == "" {
		return ""
	}
	return "#[fg=#" + terminal.RGB(word) + "]" + tmuxText(text) + "#[default]"
}

// barChip is the state as the bar opens with it: its glyph and word on its colour in the theme's
// on-accent, bold for `! needs you`, the one loud thing on the bar.
func barChip(screen terminal.Screen, word string) string {
	bold := ""
	if word == "needs you" {
		bold = ",bold"
	}
	return "#[fg=#" + terminal.RGB("on-accent") + ",bg=#" + terminal.RGB(word) + bold + "] " +
		tmuxText(screen.StateText(word)) + " #[default]"
}

// barProgress is the seat's plan as line one's last part in room cells (menu.last_column): a smooth
// line and its count, the same line with nothing done for one working with no plan, none for a seat
// at rest or any other with no plan, and in its place for one out of usage when it comes back,
// `back 19:20`; then what the owner left unsent, whose mark alone stays where both do not fit.
func barProgress(screen terminal.Screen, word, back string, unsent bool, done, total, room int) string {
	mark, left := "", room
	if unsent {
		mark = screen.Unsent("unsent")
		left -= terminal.Cells(mark) + 2
	}
	bar, cells := "", 0
	switch {
	case word == "out of usage" && back != "":
		bar, cells = barPaint("back "+back, word), terminal.Cells("back "+back)
	case word != "idle" && word != "out of usage" && (total > 0 || word == "working"):
		bar, cells = barLine(screen, word, done, total, left)
	}
	if mark == "" {
		return bar
	}
	mark = barPaint(mark, "needs you")
	if bar == "" || cells > left {
		return mark
	}
	return bar + "  " + mark
}

// barLine is that line in those cells, the count alone where no cell of line fits, and the cells
// it takes.
func barLine(screen terminal.Screen, word string, done, total, room int) (string, int) {
	count := "no plan yet"
	if total > 0 {
		count = fmt.Sprintf("%d of %d", done, total)
	}
	size := room - len(count) - 1
	if size < 1 {
		return barPaint(count, "muted"), len(count)
	}
	full, half, empty := "━", "╸", "─"
	share := float64(done) / float64(max(total, 1))
	halves := int(math.RoundToEven(2 * float64(size) * share))
	if screen.ASCII() {
		full, half, empty = "=", "-", "-"
		halves = 2 * int(math.RoundToEven(float64(size)*share))
	}
	ends := (halves + 1) / 2
	line := strings.Repeat(full, halves/2) + strings.Repeat(half, halves%2)
	if line != "" {
		line = "#[fg=#" + terminal.RGB(word) + "]" + line
	}
	if ends < size {
		line += "#[fg=#" + terminal.RGB("border") + "]" + strings.Repeat(empty, size-ends)
	}
	return line + "#[default] " + barPaint(count, "muted"), size + 1 + len(count)
}

// barSelection is the seat's model and crew, each named at the effort it runs that role at
// (config.ModelAt), none where its record does not read as a seat's (config.load_session).
func barSelection(state, name string, models map[string]config.Model) (model string, builds, reviews []string) {
	record, _ := run.Shared(filepath.Join(state, "session-"+name+".json"))
	if record == nil {
		return "", nil, nil
	}
	at := atEfforts(models, record)
	if selected, err := configSelection(record, models); err == nil {
		record = selected
	}
	if _, complaint, crewed := recordCrew(record, models); !crewed || complaint != "" {
		return "", nil, nil
	}
	named := func(key, effort string) (found []string) {
		for _, each := range record.List(key) {
			if each, ok := each.(string); ok {
				found = append(found, config.ModelAt(each, effort, at))
			}
		}
		return found
	}
	builds, reviews = named("workers", "exec_effort"), named("workers", "review_effort")
	if record.Has("reviewers") {
		reviews = named("reviewers", "review_effort")
	}
	return config.ModelAt(record.Str("orchestrator"), "effort", at), builds, reviews
}

// publish writes the seat's bar and window title from its row's own values, and with a changed word
// has every seat's bar count it again (statusbar.redress, retell); it never fails what it dresses.
// A legacy seat lives on the person's own server, where nothing is written, and a dry look tells
// nothing.
func (seat Seat) publish(state string, models map[string]config.Model, changed bool) {
	if seat.legacy || drying != nil {
		return
	}
	model, builds, reviews := barSelection(state, seat.Name, models)
	done, total := seat.Progress()
	barTell(state, seat.Name, seat.barOptions(terminal.For(os.Stderr), model, builds, reviews, done, total), seat.bars)
	if changed {
		barTell(state, "", nil, seat.bars)
	}
}

// barOptions is what the seat's bar is told: its layout, line one at each width, line two, its key
// and its window title, the title last so whoever sees it has the whole bar to read.
func (seat Seat) barOptions(screen terminal.Screen, model string, builds, reviews []string, done, total int) [][3]string {
	head := " " + barChip(screen, seat.Word) + "   #[bold]" + tmuxText(seat.Name) + "#[nobold]"
	if model != "" {
		head += "   " + barPaint(model, "muted")
	}
	target := "=" + seat.Name + ":"
	// the bar, its message line and its command prompt on the terminal's own colours, as the pane where
	// the harness draws is, and tmux's selection while scrolling back in the shades kept
	// (statusbar.layout)
	own := [][3]string{{target, "set-titles", "on"}, {target, "status", "2"}, {target, "status-style", "default"},
		{target, "mode-style", "fg=#" + terminal.RGB("text") + ",bg=#" + terminal.RGB("selection")},
		{target, "message-style", "default"}, {target, "message-command-style", "default"},
		{target, "status-format[0]", barLineOne()}, {target, "status-format[1]", barLineTwo()}}
	for i, option := range barTops {
		top := head
		if last := barProgress(screen, seat.Word, seat.Back(time.Now()), seat.unsent != "", done, total, barCells[i]); last != "" {
			top += "   " + last
		}
		own = append(own, [3]string{target, option, top})
	}
	for i, why := range seat.whys(screen, barPaint(terminal.Crew(builds, reviews), "muted")) {
		if why != "" {
			why = "  " + why
		}
		own = append(own, [3]string{target, barWhys[i], why})
	}
	// tmux reads a title as a time too, unlike the bar's options: its `%` doubles as well
	title := strings.ReplaceAll(tmuxText(seat.Name+" · "+seat.Word), "%", "%%")
	return append(own, [3]string{target, barKey, "#[fg=#" + terminal.RGB("dim") + "]Ctrl-b m#[fg=#" + terminal.RGB("muted") + "]  menu #[default]"},
		[3]string{target, "set-titles-string", title})
}

// whys is line two at each of barWhys (statusbar.whys): every task's squares, then the crew -- or in
// its place a needs-you reason no chat shows, alone where no task is in flight -- then those squares
// alone; and again with them cut to six, then to one and the count of the rest, so a narrow client
// still sees its tasks (barLineTwo).  The owner picked the squares first, 17 Nov 2026.
func (seat Seat) whys(screen terminal.Screen, crew string) []string {
	tasks := seat.Tasks()
	if seat.Word == "needs you" && !seat.question {
		crew = tmuxText(terminal.Plain(seat.reason))
		if len(tasks) == 0 { // no squares to keep over it: cut, never dropped, on the narrowest client
			return slices.Repeat([]string{crew}, len(barWhys))
		}
	}
	var whys []string
	for _, most := range []int{len(tasks), 6, 1} {
		squares := barSquares(screen, tasks, most)
		crewed := squares + "   " + crew
		if squares == "" || crew == "" {
			crewed = squares + crew
		}
		whys = append(whys, crewed, squares)
	}
	return whys
}

// barSquares is the first most of those tasks as menu.squares draws them: three squares each, two
// cells apart, the stages it has reached filled, in working's colour while a model works on it and
// dim while it waits, the rest dim and empty; those not drawn counted, `+3`.
func barSquares(screen terminal.Screen, tasks []Task, most int) string {
	full, empty := "■", "□"
	if screen.ASCII() {
		full, empty = "#", "-"
	}
	var drawn []string
	for _, task := range tasks[:min(most, len(tasks))] {
		kind := "dim"
		if task.Moving {
			kind = "working"
		}
		drawn = append(drawn, barPaint(strings.Repeat(full, task.Stage+1), kind)+barPaint(strings.Repeat(empty, 2-task.Stage), "dim"))
	}
	if rest := len(tasks) - most; rest > 0 {
		drawn = append(drawn, barPaint(fmt.Sprintf("+%d", rest), "dim"))
	}
	return strings.Join(drawn, "  ")
}

func barSet(option [3]string) []string {
	return []string{"set-option", "-t", option[0], option[1], tmux.Literal(option[2])}
}

// barTell writes line one's right end on that seat's bar, or every seat's for none, then the
// caller's own options on a session tmux lists, each only where it would change what the bar
// shows (bartold.go), and binds its click with any write, under one lock across every bar's
// reading and writing, so whoever writes last has read last (statusbar._tell).  The sessions are
// those `listing` lists, a reading's once until it writes: the digests read before are that bar's
// no longer, and would leave out telling it back what it showed then; else listed here.  A listing
// older than another program's write can only cost a write not needed, or leave a bar wrong until
// the next look.
func barTell(state, only string, own [][3]string, listing *func() ([]barRow, bool)) {
	if config.EnsureDirs() != nil {
		return
	}
	held, err := lock.Wait(context.Background(), filepath.Join(state, "statusbar.lock"))
	if err != nil {
		return
	}
	defer held.Close()
	if !config.Publishes() {
		return
	}
	list := barSessions
	if listing != nil {
		list = *listing
	}
	listed, known := list()
	if !known {
		return
	}
	found := barSeats(state, listed)
	var lists [][]string
	for _, each := range found {
		if only != "" && only != each.name {
			continue
		}
		if list := barEnd(found, each); list != nil {
			lists = append(lists, list)
		}
	}
	lists = append(lists, barOwn(own, listed)...)
	if len(lists) > 0 {
		tmux.Lists(tmux.Own(), append(lists, barClick))
		if listing != nil {
			*listing = sync.OnceValues(barSessions)
		}
	}
}

// A barRow is one session a bar may count: its tmux id, its name, its mark, the digests of what it
// was told, and once read its word.
type barRow struct{ id, name, mark, told, toldEnd, word string }

// barSessions are the sessions this HOME started on ak's own server (statusbar.sessions); false
// where tmux does not answer or none of them is this HOME's: the socket is the user's, and a scratch
// HOME's ak would write its records over real bars.
func barSessions() ([]barRow, bool) {
	out, err := tmux.Ask(tmux.Own(), "-u", "list-sessions", "-F", "#{session_id}:#{session_name}:#{"+tmux.Mark+"}:#{"+barTold+"}:#{"+barToldEnd+"}:#{HOME}")
	if err != nil {
		return nil, false
	}
	home := resolved(config.UserHome())
	var rows []barRow
	answered := false
	for _, line := range strings.Split(out, "\n") {
		parts := strings.SplitN(line, ":", 6)
		if len(parts) < 5 {
			continue
		}
		answered = true
		if (len(parts) == 5 || parts[5] == "" || resolved(parts[5]) == home) && parts[1] != config.Control {
			rows = append(rows, barRow{id: parts[0], name: parts[1], mark: parts[2], told: parts[3], toldEnd: parts[4]})
		}
	}
	return rows, !answered || len(rows) > 0
}

func resolved(path string) string {
	if real, err := filepath.EvalSymlinks(path); err == nil {
		return real
	}
	return path
}

// barSeats are those sessions that are seats, each with the word it last announced: what each
// bar's right end counts (statusbar.seats).  A session without ak's mark that no seat has a record
// of may be no seat (noSeat), and neither is one under a name no seat can have.
func barSeats(state string, listed []barRow) (found []barRow) {
	for _, row := range listed {
		_, unrecorded := os.Stat(filepath.Join(state, "session-"+row.name+".json"))
		if !strings.HasPrefix(row.id, "$") || config.SessionName(row.name) != row.name ||
			row.mark != "1" && unrecorded != nil && noSeat(row.name) {
			continue
		}
		if file, _ := run.Shared(filepath.Join(state, "seat-"+row.name+".json")); file != nil {
			row.word = file.Str("word")
		}
		found = append(found, row)
	}
	return found
}

// barOthers is the right end of that seat's line one: how many other seats need you, the same
// short for a client too narrow for both it and the name, each again in the lit tone, and the
// format that turns the pointer on it into the first such seat's session id; or nothing.
func barOthers(found []barRow, name string) (string, string, string, string, string) {
	var needs []string
	for _, row := range found {
		if row.name != name && row.word == "needs you" {
			needs = append(needs, row.id)
		}
	}
	if len(needs) == 0 {
		return "", "", "", "", ""
	}
	said, short := fmt.Sprintf("! %d other seats need you", len(needs)), fmt.Sprintf("! %d need you", len(needs))
	if len(needs) == 1 {
		said, short = "! 1 other seat needs you", "! 1 needs you"
	}
	own, lit := terminal.RGBFaded("needs you", -motion.Brighter)
	end := func(text, rgb string) string {
		return "#[range=right]#[fg=" + rgb + ",bold]" + tmuxText(text) + "#[default]#[norange] "
	}
	hit := fmt.Sprintf("#{?#{&&:#{e|>:%s,1},#{e|<=:%s,%d}},%s,}", barAt, barAt, terminal.Cells(said)+1, needs[0])
	return end(said, own), end(short, own), end(said, lit), end(short, lit), hit
}
