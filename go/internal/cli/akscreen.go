package cli

import (
	"io"
	"os"
	"runtime"
	"sync/atomic"
	"time"

	"agentkit/internal/menu"
	"agentkit/internal/motion"
	"agentkit/internal/plan"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
	"agentkit/internal/usage"
)

// rereadEvery is the longest the frame goes unread (menu.TICK).
const rereadEvery = 10 * time.Second

// A reading is what a frame is drawn from, apart from the terminal and the clock.
type reading struct {
	seats    []menu.Seat
	cells    []menu.Cell
	standing string
	past     []menu.PastSeat
	handoff  bool
}

// readFrame is the records as they stand and a live seat its look, the grid as usage.json holds it;
// false where Go does not read that home, or where opening it would do more than draw.
func readFrame(now time.Time) (reading, bool) {
	home, known := seat.Menu(now)
	if !known || !home.Settled(now) {
		return reading{}, false
	}
	var found reading
	for i, each := range home.Seats {
		if each.Past() {
			row, known := pastRow(each, now)
			if !known {
				return reading{handoff: true}, true
			}
			found.past = append(found.past, row)
			continue
		}
		done, total := plan.Progress(each.Name)
		builds, reviews := home.Crew(each)
		found.seats = append(found.seats, menu.Seat{Number: i + 1, Name: each.Name, Checkout: each.Checkout(), Model: home.ModelName(each),
			Word: each.Word, Unsent: each.Unsent(), Said: each.Said(), Done: done, Total: total, Builds: builds, Reviews: reviews, Tasks: each.Tasks()})
	}
	sortPast(found.past)
	var err error
	if found.cells, err = menu.Cells(now); err != nil {
		return reading{}, false
	}
	if found.standing, err = menu.Standing(now); err != nil {
		return reading{}, false
	}
	return found, true
}

// akScreen is bare `ak` on a server: it takes the terminal, draws the frame and gives the terminal
// back. A refused read keeps that frame; an unsupported past seat hands it over to Python.
func akScreen(args []string, errOut io.Writer) int {
	// a Mac's menu starts its bridge first, and Windows leaves the terminal to a later slice
	drawable := runtime.GOOS == "linux" && terminal.Attachable() && os.Getenv("TERM") != "" && os.Getenv("TERM") != "dumb" && !onLiveCheckout()
	if !drawable {
		return notImplemented(errOut, "attach")
	}
	first, known := readFrame(time.Now())
	if !known || first.handoff {
		return notImplemented(errOut, "attach")
	}
	keyboard := terminal.NewKeyboard()
	keyboard.Take()
	defer func() { // nothing that breaks here leaves the terminal taken
		if broke := recover(); broke != nil {
			keyboard.Give()
			panic(broke)
		}
	}()
	keyboard.Sense()
	var latest atomic.Pointer[reading]
	latest.Store(&first)
	reread := func() {
		if found, known := readFrame(time.Now()); known {
			latest.Store(&found)
			keyboard.Wake()
		}
	}
	go func() {
		for {
			time.Sleep(rereadEvery)
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
	painter := terminal.NewPainter(os.Stdout)
	clock, model := &motion.Clock{}, menu.Model{}
	dry, overlay := contains(args, "--dry-run"), contains(args, "--overlay")
	if overlay {
		model.Highlight.Cursor = os.Getenv("AGENTKIT_SESSION")
	}
	frame := time.AfterFunc(time.Hour, keyboard.Wake) // each draw sets it to its next frame, or stops it
	for {
		screen, shown := keyboard.Screen(), latest.Load()
		if shown.handoff {
			keyboard.Give()
			return notImplemented(errOut, "attach")
		}
		clock.Draw(time.Now())
		drawn := menu.Draw(menu.View{Screen: screen, Seats: shown.seats, Cells: shown.cells, Standing: shown.standing,
			Clock: time.Now().Format("15:04"), Keys: menuKeys(screen, len(shown.past) > 0, overlay), Highlight: model.Highlight, New: model.New, Motion: clock}, screen.Width(), screen.Height())
		if model.New != nil && model.New.Picker {
			drawn.Lines = model.New.PickerLines(screen, time.Now().Format("15:04"))
		}
		painter.Write(drawn.Lines, screen)
		if next, due := clock.Next(); due {
			frame.Reset(next)
		} else {
			frame.Stop()
		}
		key := keyboard.ReadKey()
		if key.Name != "wake" && key.Name != "again" {
			clock.Finish()
		}
		if model.New != nil {
			switch model.New.Key(key) {
			case "esc":
				model.New = nil
			case "eof":
				keyboard.Give()
				return 0
			case "start":
				if leave, code := startMenuRow(&model, dry, overlay, keyboard, painter, errOut); leave {
					return code
				}
				if model.New == nil {
					reread()
				}
			}
			continue
		}
		choice := menuChoice(key, drawn, shown.seats, keyboard)
		switch {
		case choice != "":
			if leave, code := openMenuSeat(choice, dry, overlay, keyboard, painter, errOut); leave {
				return code
			}
			model.Highlight, clock = menu.Highlight{Cursor: choice}, &motion.Clock{}
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
			if leave, code := menuPast(&returned.past, dry, overlay, keyboard, painter, errOut); leave {
				return code
			}
			latest.Store(&returned)
			go reread()
		case key.Name == "char" && (key.Char == "c" || key.Char == "C"):
			session := ""
			if overlay {
				session = os.Getenv("AGENTKIT_SESSION")
			}
			frame.Stop()
			if !menuConfig(session, shown.cells, keyboard, painter) {
				keyboard.Give()
				return notImplemented(errOut, "attach")
			}
		case key.Name == "char" && (key.Char == "x" || key.Char == "X") && overlay:
			if leave, code := menuStop(shown, dry, keyboard, painter, &model.Highlight, errOut); leave {
				return code
			}
		}
	}
}
