package harness

import (
	"math"
	"strconv"
	"strings"

	"agentkit/internal/config/adapters"
	"agentkit/internal/run"
)

// claudeWindows is the login's two windows as Claude Code names them and the meters ak reads them
// as: the session window is usage's sessionSecs, the week seven days, as adapters/claude.sh names
// them off the endpoint's groups.
var claudeWindows = []struct {
	key, name string
	secs      int
}{{"five_hour", "session", 18000}, {"seven_day", "weekly_all", 604800}}

// claudeWindowMeters is endpoint meters of each of claudeWindows that windows holds as an object:
// its used share of whole and its resets epoch second, each a finite number in range; none for none.
func claudeWindowMeters(windows *run.Object, used, resets string, whole float64) []any {
	if windows == nil {
		return nil
	}
	var meters []any
	for _, window := range claudeWindows {
		reading := windows.Dict(window.key)
		if reading == nil {
			continue
		}
		share, measured := run.Num(reading.Get(used))
		at, dated := run.Num(reading.Get(resets))
		if !measured || math.IsNaN(share) || share < 0 || share > whole || !dated || math.IsInf(at, 0) || math.IsNaN(at) || at <= 0 {
			continue
		}
		meters = append(meters, run.Fields("name", window.name, "used", share*(100/whole), "resets_at", reading.Get(resets), "window_secs", window.secs))
	}
	return meters
}

// claudeLimits is each window of its login's limits a status render carries (adapters.ClaudeLimits),
// as hooks/claude-status.sh's jq reads them: one holding a number for both its used share and its
// reset, as `<window> <used_percentage> <resets_at>` in arithmetic's one spelling of a number, so
// 20.0 is no change from 20.
func claudeLimits(render *run.Object) []string {
	limits := render.Dict(adapters.ClaudeLimits.Render)
	if limits == nil {
		return nil
	}
	var windows []string
	for _, window := range claudeWindows {
		reading := limits.Dict(window.key)
		if reading == nil {
			continue
		}
		used, measured := run.Num(reading.Get("used_percentage"))
		resets, dated := run.Num(reading.Get("resets_at"))
		if measured && dated {
			windows = append(windows, window.key+" "+strconv.FormatFloat(used, 'f', -1, 64)+" "+strconv.FormatFloat(resets, 'f', -1, 64))
		}
	}
	return windows
}

// claudeStatusMeters is the windows claudeLimits read off a render as endpoint meters, claude.py
// `status_meters`: there only while the API reports them and they have not reset.
func claudeStatusMeters(windows []string) []any {
	limits := run.NewObject()
	for _, line := range windows {
		window, words, _ := strings.Cut(line, " ")
		used, resets, _ := strings.Cut(words, " ")
		share, err := strconv.ParseFloat(used, 64)
		at, unread := strconv.ParseFloat(resets, 64)
		if err == nil && unread == nil {
			limits.Set(window, run.Fields("used_percentage", share, "resets_at", at))
		}
	}
	return claudeWindowMeters(limits, "used_percentage", "resets_at", 100)
}
