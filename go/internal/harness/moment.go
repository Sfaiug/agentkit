package harness

import (
	"time"

	"agentkit/internal/run"
)

// Moment is a time in Unix seconds as a harness records one, a number or an RFC 3339 time with its
// zone (harness.moment); 0 for anything else.  A time is its whole microseconds over a million,
// as Python's timestamp() divides them, so each is Python's very float: a done check's
// fingerprint holds it.
func Moment(value any) float64 {
	if text, ok := value.(string); ok {
		stamp, err := time.Parse(time.RFC3339Nano, text)
		if err != nil {
			return 0
		}
		return float64(stamp.UnixMicro()) / 1e6
	}
	seconds, _ := run.Num(value)
	return seconds
}
