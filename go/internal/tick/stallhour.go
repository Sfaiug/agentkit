package tick

import (
	"agentkit/internal/notify"
	"agentkit/internal/seat"
)

// asked is whether the health row's look at a seat whose owner it asked about its stall is all
// the row does there (watch.health): nothing is typed or asked again while its own login is fine,
// its pane named, its title its own and its account the one it stays on, and the notice standing,
// if any, is a watcher's nobody opened, which no output answers (notify.progress).
func asked(live seat.Live) bool {
	notice := notify.Last(live.Name)
	return live.Login == nil && quietLogin(live) && live.Bound && titleKept(live) && live.Refused == "" && stays(live) &&
		(notice == nil || notice.Get("watcher") == true && notice.Get("opened_at") == nil)
}
