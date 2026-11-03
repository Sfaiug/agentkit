package seat

import (
	"testing"
	"time"
)

func TestARecordSeenAWeekAgoIsOneMaintenanceRetires(t *testing.T) {
	now := time.Now()
	for name, days := range map[string]int{"settled": 6, "retired": 8} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", map[string]any{"seen": seconds(now.AddDate(0, 0, -days))})
			read, known := Looking(now)
			if !known {
				t.Fatal("Go did not read the seat")
			}
			if read.Settled(now) != (name == "settled") {
				t.Fatalf("seen %d days ago: settled %v", days, read.Settled(now))
			}
		})
	}
}
