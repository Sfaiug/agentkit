//go:build go1.25

package host

import (
	"context"
	"testing"
	"testing/synctest"
	"time"
)

func TestABoundLiveAsTheSilenceReachesItsLimitHoldsItOff(t *testing.T) {
	// synctest's clock, go1.25's, moves under no host load: each look comes when it is due
	synctest.Test(t, func(t *testing.T) {
		const silence = 2050 * time.Millisecond // reached just after a look, a second before the next
		end := time.Now().Add(2900 * time.Millisecond)
		reads := 0
		var stopped time.Time
		ctx, ended := Watch{Silence: silence,
			Heard: func() any {
				if reads++; reads == 2 {
					time.Sleep(950 * time.Millisecond) // the look before the limit's, slow as on a busy host
				}
				return nil
			},
			Declared: func(now float64) bool { return now < float64(end.UnixNano())/1e9 },
			Before:   func() { stopped = time.Now() }}.Stop(context.Background())
		<-ctx.Done()
		if why := ended(); why != "silence" || stopped.Sub(end) < silence {
			t.Fatalf("got %q %v after the bound's end", why, stopped.Sub(end))
		}
	})
}
