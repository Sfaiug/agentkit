package cli

import (
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/features"
	"agentkit/internal/menu"
	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

// fetchShown is how long a list goes unanswered before the rule says so (motion.WAIT): a shorter
// wait shows nothing.
const fetchShown = 150 * time.Millisecond

// hiddenFeatures is each project with a seat shown that names its feature switches, by checkout,
// and how many its `list` last answered hidden from everyone, none before any (menu.v5o_groups).
func hiddenFeatures(seats []menu.Seat) map[string]int {
	hidden := map[string]int{}
	for _, each := range seats {
		if _, seen := hidden[each.Checkout]; !seen && each.Checkout != "" && features.Named(each.Checkout) {
			hidden[each.Checkout] = features.Read(each.Checkout, features.Every).Hidden()
		}
	}
	return hidden
}

// menuFeatures is `agentkit · <project>`, the switches of the project at checkout, until Esc
// (menu.show_features): its `list` as last answered, asked again every rereadEvery while the
// screen is up, and drawn again once it lands, as akScreen's reread wakes the keyboard; the rule
// glides while one is awaited.  ↑/↓ move between features and ←/→ between `you` and
// `everyone`.  False leaves a flip, Space or a click on a mark, to the shadow build, before
// anything is written.
func menuFeatures(checkout string, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	view, clock := menu.FeaturesView{Title: filepath.Base(checkout)}, &motion.Clock{}
	frame := time.AfterFunc(time.Hour, keyboard.Wake)
	defer frame.Stop()
	for {
		now := time.Now()
		view.Reading, view.Waiting = features.Read(checkout, rereadEvery), nil
		clock.Draw(now)
		next := time.Second // a list come due is asked within a second (menu.STIR)
		if !view.Asking.IsZero() {
			if next = fetchShown - now.Sub(view.Asking); next <= 0 {
				view.Waiting, next = clock, motion.Frame
			}
		}
		view.Clock = now.Format("15:04")
		screen := keyboard.Screen()
		drawn := menu.FeaturesFrame(screen, view)
		view.Top = drawn.Top
		painter.Write(drawn.Lines, screen)
		frame.Reset(next)
		key, step := keyboard.ReadKey(), 0
		switch {
		case key.Name == "esc" || key.Name == "eof":
			return true
		case key.Name == "again":
			painter.Forget()
		case key.Name == "space":
			return false
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			step = -1
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			step = 1
		case key.Name == "left":
			view.Column = 0
		case key.Name == "right":
			view.Column = 1
		case key.Name == "pointer" && key.Mouse.Button&64 != 0: // the wheel: up, down, or sideways
			if key.Mouse.Button&3 <= 1 {
				step = 2*(key.Mouse.Button&1) - 1
			}
		case key.Name == "pointer":
			if row, column, hit := drawn.Hit(key.Mouse); hit {
				view.At = view.Rows[row].ID
				if column >= 0 {
					view.Column = column
					if key.Mouse.Released && key.Mouse.Button&3 == 0 {
						return false
					}
				}
			}
		}
		if here := view.Here(); step != 0 && here >= 0 {
			view.At = view.Rows[max(0, min(len(view.Rows)-1, here+step))].ID
		}
	}
}
