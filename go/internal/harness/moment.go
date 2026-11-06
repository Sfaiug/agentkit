package harness

import (
	"time"

	"agentkit/internal/run"
)

// Moment is a time in Unix seconds as a harness records one, a number or an RFC 3339 time with its
// zone (harness.moment); 0 for anything else.
func Moment(value any) float64 {
	if text, ok := value.(string); ok {
		stamp, err := time.Parse(time.RFC3339Nano, text)
		if err != nil {
			return 0
		}
		return float64(stamp.UnixNano()) / 1e9
	}
	seconds, _ := run.Num(value)
	return seconds
}
