package cli

import (
	"io"
	"os"
	"runtime"
	"sync/atomic"
	"time"

	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
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
	home, known := seat.Looking(now)
	if !known || !home.Settled(now) {
		return reading{}, false
	}
	var found reading
	for i, each := range home.Seats {
		if each.Past() {
			found.past = true
			continue
		}
		looked, err := each.Looked()
		if err != nil {
			return reading{}, false
		}
		found.seats = append(found.seats, menu.Seat{Number: i + 1, Name: looked.Name, Checkout: looked.Checkout(), Model: home.ModelName(looked),
			Word: looked.Word, Unsent: looked.Unsent(), Said: looked.Said()})
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
func akScreen(errOut io.Writer) int {
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
	go func() {
		for {
			time.Sleep(rereadEvery)
			if found, known := readFrame(time.Now()); known {
				latest.Store(&found)
				keyboard.Wake()
			}
		}
	}()
	painter := terminal.NewPainter(os.Stdout)
	for {
		screen, shown := keyboard.Screen(), latest.Load()
		painter.Write(menu.Lines(menu.View{Screen: screen, Seats: shown.seats, Cells: shown.cells, Standing: shown.standing,
			Clock: time.Now().Format("15:04"), Keys: menu.Keys(screen, shown.past)}, screen.Width(), screen.Height()), screen)
		key := keyboard.ReadKey()
		switch {
		case key.Name == "esc" || key.Name == "eof":
			keyboard.Give()
			return 0
		case key.Name == "again":
			painter.Forget()
		case opensSomething(key, len(shown.seats) > 0, shown.past):
			keyboard.Give()
			return notImplemented(errOut, "attach")
		}
	}
}

// opensSomething is whether a key leads where Go has no road yet, every other being let go.
func opensSomething(key terminal.Key, rows, past bool) bool {
	switch key.Name {
	case "enter":
		return true
	case "up", "down", "left", "right":
		return rows
	case "char":
		switch key.Char {
		case "n", "N", "c", "C":
			return true
		case "j", "J", "k", "K":
			return rows
		case "p", "P":
			return past
		}
		return len(key.Char) == 1 && '0' <= key.Char[0] && key.Char[0] <= '9'
	}
	return false
}
