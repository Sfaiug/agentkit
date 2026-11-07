package browser

import "agentkit/internal/run"

// Owns is whether an entry of ak's state folder is the browser's alone, saying nothing of any seat:
// the tab records, while no tab in them names a run or seat that opened it, and the file they are
// written through.  Only an opener ties a tab to a seat (browser._owned); the idle rule alone closes
// the rest, as the tick's tidy records every tab the host's browser shows.
func Owns(name string) bool {
	switch name {
	case "browser-tabs.tmp":
		return true
	case "browser-tabs.json":
		tabs, err := run.ReadJSON(records())
		if err != nil || tabs == nil {
			return false
		}
		for _, id := range tabs.Keys() {
			if tab, _ := tabs.Get(id).(*run.Object); tab == nil || tab.Get("opener") != nil {
				return false
			}
		}
		return true
	}
	return false
}
