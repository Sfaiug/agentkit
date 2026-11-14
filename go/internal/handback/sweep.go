package handback

import "agentkit/internal/run"

// Sweep is the sweep of Python's reap of the Sweepable run at dir before its recovery is offered,
// as the tick's endings row makes it: held under its recovery lock and read again, what its dead
// loop left behind ended and its record stamped, once per loop.  False where it is no longer
// Sweepable.
func Sweep(dir string) (bool, error) {
	release, err := run.Hold(dir)
	if err != nil {
		return false, err
	}
	defer release()
	record, _ := run.Read(dir)
	if record == nil || !Sweepable(record) {
		return false, nil
	}
	return true, sweep(dir, record)
}
