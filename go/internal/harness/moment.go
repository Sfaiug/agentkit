package harness

import (
	"math"
	"time"

	"agentkit/internal/run"
)

// Moment is a time in Unix seconds as a harness records one, a number or an RFC 3339 time with
// its zone (harness.moment), read to the microsecond as Python reads one; 0 for anything else.
func Moment(value any) float64 {
	if text, ok := value.(string); ok {
		stamp, err := time.Parse(time.RFC3339Nano, text)
		if err != nil {
			return 0
		}
		return float64(stamp.UnixMicro()) / 1e6
	}
	if seconds, _ := run.Num(value); !math.IsNaN(seconds) && !math.IsInf(seconds, 0) {
		return seconds
	}
	return 0
}
