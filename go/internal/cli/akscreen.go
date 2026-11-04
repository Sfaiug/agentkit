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
	past     bool
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
			found.past = true
			continue
		}
		done, total := plan.Progress(each.Name)
		builds, reviews := home.Crew(each)
		found.seats = append(found.seats, menu.Seat{Number: i + 1, Name: each.Name, Checkout: each.Checkout(), Model: home.ModelName(each),
			Word: each.Word, Unsent: each.Unsent(), Said: each.Said(), Done: done, Total: total, Builds: builds, Reviews: reviews, Tasks: each.Tasks()})
	}
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
// back.  A read refused once the frame is up keeps that frame.
func akScreen(args []string, errOut io.Writer) int {
	// a Mac's menu starts its bridge first, and Windows leaves the terminal to a later slice
	drawable := runtime.GOOS == "linux" && terminal.Attachable() && os.Getenv("TERM") != "" && os.Getenv("TERM") != "dumb" && !onLiveCheckout()
	if !drawable {
		return notImplemented(errOut, "attach")
	}
	first, known := readFrame(time.Now())
	if !known {
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
	clock, highlight := &motion.Clock{}, menu.Highlight{}
	dry, overlay := contains(args, "--dry-run"), contains(args, "--overlay")
	if overlay {
		highlight.Cursor = os.Getenv("AGENTKIT_SESSION")
	}
	frame := time.AfterFunc(time.Hour, keyboard.Wake) // each draw sets it to its next frame, or stops it
	for {
		screen, shown := keyboard.Screen(), latest.Load()
		clock.Draw(time.Now())
		drawn := menu.Draw(menu.View{Screen: screen, Seats: shown.seats, Cells: shown.cells, Standing: shown.standing,
			Clock: time.Now().Format("15:04"), Keys: menuKeys(screen, shown.past, overlay), Highlight: highlight, Motion: clock}, screen.Width(), screen.Height())
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
		choice := menuChoice(key, drawn, shown.seats, keyboard)
		switch {
		case choice != "":
			if leave, code := openMenuSeat(choice, dry, overlay, keyboard, painter, errOut); leave {
				return code
			}
			highlight, clock = menu.Highlight{Cursor: choice}, &motion.Clock{}
		case highlight.Move(key, drawn):
		case key.Name == "esc" || key.Name == "eof":
			keyboard.Give()
			return 0
		case key.Name == "again":
			painter.Forget()
		case opensSomething(key, shown.past, overlay):
			keyboard.Give()
			return notImplemented(errOut, "attach")
		}
	}
}

// opensSomething is whether a key leads where Go has no road yet, every other being let go.
func opensSomething(key terminal.Key, past, overlay bool) bool {
	switch key.Name {
	case "char":
		switch key.Char {
		case "n", "N", "c", "C":
			return true
		case "p", "P":
			return past
		case "x", "X":
			return overlay
		}
	}
	return false
}
