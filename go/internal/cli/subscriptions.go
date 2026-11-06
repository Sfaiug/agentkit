package cli

import (
	"slices"
	"strings"
	"time"

	"agentkit/internal/menu"
	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

// menuSubscriptions is `Subscriptions` on `c` read with the keys until Esc (menu.config_subscriptions):
// true back on `c`, false where a key is Python's, nothing written: `+ add a subscription`, a reset
// spent, a removal.  ↑/↓ and the pointer move the highlight, ←/→ and the pointer the act lit on the
// line its row opens, and Enter or a click runs that act.  The line a row the keys come to opens lit
// on `log in again` where offered, and an act going from under the light lights nothing in its place.
// The usage it shows is read again every draw, at least every rereadEvery, so a reading that lands
// shows without a key.
func menuSubscriptions(keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	view, clock := menu.Subscriptions{}, &motion.Clock{}
	// whose line the keys last opened: none yet, so the first lights its first act
	opened := "\x00"
	frame := time.AfterFunc(time.Hour, keyboard.Wake) // each draw sets it to its next frame
	defer frame.Stop()
	defer painter.Forget()
	for {
		cells, err := menu.Cells(time.Now())
		if err != nil {
			return false
		}
		view.Cells, view.At = cells, min(view.At, len(cells))
		whose := ""
		if view.At < len(cells) {
			whose = cells[view.At].Provider + " " + cells[view.At].Account
		}
		if whose != opened {
			opened, view.On = whose, menu.LogInAgain
		}
		screen := keyboard.Screen()
		clock.Draw(time.Now())
		view.Motion, view.Clock = clock, time.Now().Format("15:04")
		if !screen.Moves() {
			view.Motion = nil
		}
		drawn := menu.SubscriptionsPage(screen, view)
		view.Top, view.On = drawn.Top, drawn.On
		painter.Write(drawn.Lines, screen, drawn.Over...)
		next, due := clock.Next()
		if !due {
			next = rereadEvery
		}
		frame.Reset(next)
		key := keyboard.ReadKey()
		if key.Name != "wake" && key.Name != "again" && key.Name != "pointer" {
			clock.Finish() // a key, not the pointer, ends what moves on its last frame
			view.Note, view.Away = "", false
		}
		switch {
		case key.Name == "esc" || key.Name == "eof":
			return true
		case key.Name == "again":
			painter.Forget()
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			view.At = max(0, view.At-1)
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			view.At = min(len(cells), view.At+1)
		case (key.Name == "left" || key.Name == "right") && len(drawn.Acts) > 0:
			at := slices.Index(drawn.Acts, view.On)
			if at < 0 {
				at = 0
			} else if key.Name == "right" {
				at = min(len(drawn.Acts)-1, at+1)
			} else {
				at = max(0, at-1)
			}
			view.On = drawn.Acts[at]
		case key.Name == "pointer":
			mouse := key.Mouse
			if mouse.Button&64 != 0 {
				view.At, view.Away = max(0, min(len(cells), view.At+mouse.Notches)), false
			} else if row, act, hit := drawn.Hit(mouse); hit {
				view.At, view.Away = row, false
				if act >= 0 {
					view.On = drawn.Acts[act]
				}
				if mouse.Released && mouse.Button&3 == 0 && (act >= 0 || row == len(cells)) {
					key.Name = "enter"
				}
			} else {
				view.Away = true
			}
		}
		switch {
		case key.Name != "enter" || view.At < len(cells) && !slices.Contains(drawn.Acts, view.On):
		case view.On != menu.LogInAgain || view.At == len(cells):
			return false // `+ add a subscription`, a reset spent and a removal are Python's
		default:
			view.Note = signIn(cells[view.At], keyboard, painter)
			clock = &motion.Clock{} // back from a sign-in, the page is drawn as it is
			clock.Finish()
			painter.Forget()
		}
	}
}
