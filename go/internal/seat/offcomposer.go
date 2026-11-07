package seat

import (
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/tmux"
)

// offComposer is watch.off_composer: whether the terminal cursor of a harness keeping it in its
// composer's box while keys go there (`[screen] cursor`) is outside that box, read off the pane
// a line goes into.  One opening a dialog moves it into the dialog, and a key sent then goes into
// the dialog's search, Enter picking one of its rows.  A cursor or pane that cannot be read is
// outside.
func (at seatAt) offComposer() bool {
	chrome, err := config.Section(at.own, "screen")
	if composer, _ := chrome["composer"].(string); err != nil || chrome["cursor"] != true || composer == "" {
		return false
	}
	said, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", at.pane, "#{cursor_y}")
	row, unread := strconv.Atoi(said)
	shown, uncaptured := tmux.Capture(15*time.Second, tmux.Own(), at.pane)
	return err != nil || unread != nil || uncaptured != nil ||
		!eyeOf(at.own).rules.InComposer(strings.TrimRightFunc(shown, config.Space), row)
}
