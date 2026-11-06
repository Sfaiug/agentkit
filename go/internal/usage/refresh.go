package usage

import (
	"time"

	"agentkit/internal/config"
)

// RefreshEvery is how often an open ak screen refreshes (usage.PROBE_EVERY): every screen on the
// host shares the probe locks' cadence, so a second one asks no adapter.
const RefreshEvery = probeEvery * time.Second

// Refresh writes state/usage.json from every provider asked, no snapshot answering, each adapter
// still at most once in its harness's cadence (usage.collect(refresh=True)), the checkout's own
// where no $AGENTKIT_ADAPTER_DIR is named: what an ak screen asks behind the frame it draws from
// the cache.  ErrPython before anything is asked.
func Refresh() error {
	sources, err := listed(true)
	if err != nil {
		return err
	}
	models, err := config.Entries()
	if err != nil {
		return err
	}
	_, err = collect(sources, models, true)
	return err
}
