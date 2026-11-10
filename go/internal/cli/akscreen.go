package cli

import (
	"io"
	"os"
	"runtime"
	"sync/atomic"
	"time"

	"agentkit/internal/features"
	"agentkit/internal/menu"
	"agentkit/internal/motion"
	"agentkit/internal/plan"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
	"agentkit/internal/tick"
	"agentkit/internal/usage"
)

// rereadEvery is the longest the frame goes unread (menu.TICK).
const rereadEvery = terminal.Tick

// A reading is what a frame is drawn from, apart from the terminal and the clock.
type reading struct {
	seats    []menu.Seat
	cells    []menu.Cell
	standing string
	past     []menu.PastSeat
	handoff  bool
	switches map[string]int // hiddenFeatures
	began    time.Time      // when its read began (show)
}

// show makes found the frame's reading unless the one there began later: a read that began before
// the menu's own change, a past seat it removed, would draw what the change undid, or hand the
// frame to Python for a seat it met half removed.
func show(latest *atomic.Pointer[reading], found *reading) {
	for shown := latest.Load(); !found.began.Before(shown.began); shown = latest.Load() {
		if latest.CompareAndSwap(shown, found) {
			return
		}
	}
}

// readFrame is the records as they stand and a live seat its look, the grid as usage.json holds it,
// and with announce each seat's word written down as `ak orch list` writes it (menu.v5o_seat_info's
// look) once all of the frame is Go's to draw; false where Go does not read that home, or where
// opening it would do more than draw.
func readFrame(now time.Time, announce bool) (reading, bool) {
	read := seat.Menu
	if announce { // its live seats are looked at once, under their announce locks, as Announce writes them down
		read = seat.MenuRead
	}
	home, known := read(now)
	if !known || !home.Settled() {
		return reading{}, false
	}
	found := reading{began: now}
	for _, each := range home.Seats {
		if each.Past() {
			row, known := pastRow(each, now)
			if !known {
				return reading{handoff: true, began: now}, true
			}
			found.past = append(found.past, row)
		}
	}
	sortPast(found.past)
	var err error
	if found.cells, err = menu.Cells(now); err != nil {
		return reading{}, false
	}
	if found.standing, err = menu.Standing(now); err != nil {
		return reading{}, false
	}
	if announce && home.Announce(now) != nil {
		return reading{}, false
	}
	for i, each := range home.Seats {
		if each.Past() {
			continue
		}
		done, total := plan.Progress(each.Name)
		builds, reviews := home.Crew(each)
		model, alone := home.ModelName(each)
		found.seats = append(found.seats, menu.Seat{Number: i + 1, Name: each.Name, Checkout: each.Checkout(), Model: model, Alone: alone,
			Word: each.Word, Unsent: each.Unsent(), Said: each.Said(), Done: done, Total: total, Builds: builds, Reviews: reviews, Tasks: each.Tasks()})
	}
	found.switches = hiddenFeatures(found.seats)
	return found, true
}

// akScreen is bare `ak` on a server: it takes the terminal, draws the frame and gives the terminal
// back. A refused read keeps that frame; an unsupported past seat hands it over to Python.
func akScreen(args []string, out, errOut io.Writer) int {
	dry, overlay := contains(args, "--dry-run"), contains(args, "--overlay")
	if !terminal.Attachable() && !onLiveCheckout() {
		return pipeMenu(dry, overlay, out, errOut)
	}
	// a Mac's menu starts its bridge first, and Windows leaves the terminal to a later slice
	drawable := runtime.GOOS == "linux" && terminal.Attachable() && os.Getenv("TERM") != "" && os.Getenv("TERM") != "dumb" && !onLiveCheckout()
	if !drawable {
		return notImplemented(errOut, "attach")
	}
	if !dry && tick.ResumeAfterBoot() != nil {
		return notImplemented(errOut, "attach")
	}
	keyboard, painter := terminal.NewKeyboard(), terminal.NewPainter(os.Stdout)
	defer func() { // nothing that breaks here leaves the terminal taken
		if broke := recover(); broke != nil {
			keyboard.Give()
			panic(broke)
		}
	}()
	if left := crossed(menuFrame); left != nil { // the frame the program before this exec left up
		keyboard.Take() // stays up however long a read takes
		painter.Restore(left, keyboard.Screen())
	}
	// a restart's first frame waits on no read, and none waits on writing every seat's word down,
	// a look at each that the read behind it makes, as Python's menu looks behind its first frame
	first, handed := handedRead()
	known := handed
	if !handed {
		keyboard.While(func() { first, known = readFrame(time.Now(), false) })
	}
	if !known || first.handoff {
		keyboard.Give()
		return notImplemented(errOut, "attach")
	}
	keyboard.Take()
	keyboard.Sense()
	var latest atomic.Pointer[reading]
	latest.Store(&first)
	// a restart leaves its sweep to the tick; an act waiting for one answers a kill as a key's wait does
	swept, heard := sweepBehind(handed || dry || overlay, &latest, keyboard.Wake)
	settle := func() { keyboard.While(func() { <-swept }) }
	reread := func() {
		<-swept
		if found, known := readFrame(time.Now(), true); known {
			show(&latest, &found)
		}
		keyboard.Wake()
	}
	go func() {
		for {
			time.Sleep(rereadEvery)
			reread()
		}
	}()
	go func() { // a project's switches landed: its heading counts them, and their screen draws them
		for range features.Landed() {
			reread()
		}
	}()
	go func() { // behind the frame, which draws from the cache and waits on no adapter
		for {
			if usage.Refresh() == nil {
				reread()
			}
			time.Sleep(usage.RefreshEvery)
		}
	}()
	go reread()
	clock, model, own := &motion.Clock{}, menu.Model{}, popupSeat(overlay)
	model.Highlight.Cursor = own
	if cursor, restarted := os.LookupEnv("AK_MENU_CURSOR"); restarted {
		clock.Finish() // the same screen on new code: no line grows in again
		if cursor != "" {
			model.Highlight.Cursor = cursor
		}
	}
	os.Unsetenv("AK_MENU_CURSOR")
	// each draw sets it to its next frame, or to the longest a wait goes whatever a read is doing
	frame := time.AfterFunc(time.Hour, keyboard.Wake)
	framed := false // the last wait read no key: its frame is still up
	for {
		if model.New == nil {
			if messages := append(heard(), menuNotices()...); len(messages) > 0 {
				frame.Stop()
				if !showMenuNotices(messages, keyboard, painter) {
					return 0
				}
				clock = &motion.Clock{}
			} else if framed && menuOutdated() {
				frame.Stop()
				return restartMenu(model.Highlight.Cursor, *latest.Load(), keyboard, painter, errOut)
			}
		}
		screen, shown := keyboard.Screen(), latest.Load()
		if shown.handoff {
			keyboard.Give()
			return notImplemented(errOut, "attach")
		}
		model.Highlight.Cursor = menu.Step(shown.seats, shown.switches, model.Highlight.Cursor, 0)
		clock.Draw(time.Now())
		drawn := menu.Draw(menu.View{Screen: screen, Seats: shown.seats, Cells: shown.cells, Standing: shown.standing,
			Clock: time.Now().Format("15:04"), Keys: menuKeys(screen, shown, own), Highlight: model.Highlight, New: model.New, Motion: clock,
			Switches: shown.switches}, screen.Width(), screen.Height())
		if model.New != nil && model.New.Picker {
			drawn.Lines = model.New.PickerLines(screen, time.Now().Format("15:04"))
		}
		painter.Write(drawn.Lines, screen)
		if next, due := clock.Next(); due {
			frame.Reset(next)
		} else {
			frame.Reset(rereadEvery)
		}
		key := keyboard.ReadKey()
		framed = key.Name == "wake" || key.Name == "again"
		if !framed {
			clock.Finish()
		}
		if model.New != nil {
			switch model.New.Key(key) {
			case "esc":
				model.New = nil
			case "eof":
				keyboard.Give()
				return 0
			case "models":
				frame.Stop()
				if !draftModels(model.New, shown.cells, keyboard, painter) {
					keyboard.Give()
					return notImplemented(errOut, "attach")
				}
			case "start":
				settle()
				if leave, code := startMenuRow(&model, dry, overlay, keyboard, painter, errOut); leave {
					return code
				}
				if model.New == nil {
					// back from the seat it made, the frame lists it as a restart's first frame does and
					// writing every seat's word down follows behind it: that waits on each seat's
					// announce lock, which another `ak` holds as long as its own look takes
					keyboard.While(func() {
						if found, known := readFrame(time.Now(), false); known {
							show(&latest, &found)
						}
					})
					go reread()
				}
			}
			continue
		}
		choice, meter := menuChoice(key, drawn, shown.seats, keyboard), drawn.Meter(key)
		_, heading := shown.switches[choice]
		switch {
		case heading:
			frame.Stop()
			if dry { // Python's dry run draws them once
				keyboard.Give()
				return notImplemented(errOut, "attach")
			}
			menuFeatures(choice, keyboard, painter)
			model.Highlight = menu.Highlight{Cursor: choice}
		case choice != "":
			settle()
			if leave, code := openMenuSeat(choice, dry, overlay, keyboard, painter, errOut); leave {
				return code
			}
			model.Highlight, clock = menu.Highlight{Cursor: choice}, &motion.Clock{}
		case meter >= 0:
			frame.Stop()
			if !menuMeter(shown.cells[meter], &model.Highlight, keyboard, painter) {
				keyboard.Give()
				return notImplemented(errOut, "attach")
			}
			go reread() // a login made again greys its meter
		case key.Name == "char" && (key.Char == "n" || key.Char == "N"):
			var known bool
			if model.New, known = newMenuRow(); !known {
				keyboard.Give()
				return notImplemented(errOut, "attach")
			}
		case model.Highlight.Move(key, drawn):
		case key.Name == "esc" || key.Name == "eof":
			keyboard.Give()
			return 0
		case key.Name == "again":
			painter.Forget()
		case key.Name == "char" && (key.Char == "p" || key.Char == "P") && len(shown.past) > 0:
			frame.Stop()
			returned := *shown
			if leave, code := menuPast(&returned.past, settle, dry, overlay, keyboard, painter, errOut); leave {
				return code
			}
			returned.began = time.Now() // past any read that met a seat it removed
			latest.Store(&returned)
			go reread()
		case key.Name == "char" && (key.Char == "c" || key.Char == "C"):
			session := ""
			if overlay {
				session = os.Getenv("AGENTKIT_SESSION")
			}
			frame.Stop()
			if !menuConfig(session, shown.cells, latest.Load, keyboard, painter) {
				keyboard.Give()
				return notImplemented(errOut, "attach")
			}
		case key.Name == "char" && (key.Char == "x" || key.Char == "X") && overlay:
			if leave, code := menuStop(shown, own, dry, keyboard, painter, &model.Highlight, errOut); leave {
				return code
			}
		}
	}
}
