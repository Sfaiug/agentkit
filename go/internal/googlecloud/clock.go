package googlecloud

import (
	"os"
	"strconv"
	"strings"
	"time"
)

// now is the time this package reads, in Unix seconds (google_cloud._now). An answer key names its
// clock in AK_GOOGLE_CLOCK, a file of Unix seconds read anew each time, so it reaches whatever
// program the key runs and moves between commands; unset, the real clock. Only readings move:
// the rest of ak keeps the real clock.
func now() (float64, error) {
	clock := os.Getenv("AK_GOOGLE_CLOCK")
	if clock == "" {
		return float64(time.Now().UnixMicro()) / 1e6, nil
	}
	data, err := os.ReadFile(clock)
	if err != nil {
		return 0, err
	}
	return strconv.ParseFloat(strings.TrimSpace(string(data)), 64)
}
