package loop

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Drivable is supplied by launch, which decides what Go drives to its end (launch.drivable): nil
// where Go can drive a run bound to these lists and numbers.
var Drivable func(config.Binding, config.Numbers) error

// LaunchForSeat is a run the tick starts on a seat (as night_review._start around
// run.launch_for_seat): text, whole, at the task file path, and a run directory of this minute and
// name holding it, launched for the seat with origin's keys and started; a start that fails keeps
// its queued receipt for the tick to carry on. Its run id; ErrLeft, with nothing written, where Go
// does not carry the seat's lists, the project's numbers or the host's admission, or does not
// drive the run they bind.
func LaunchForSeat(session, name, path, text string, origin *run.Object) (string, error) {
	state := run.Fields("launched_session", session)
	if os.Getenv("AK_MAX_RUNS") != "0" {
		return "", fmt.Errorf("%w: host admission is Python's", ErrLeft)
	}
	_, bound, numbers, err := bindSeat(state, origin)
	if err == nil {
		err = Drivable(bound, numbers)
	}
	if err != nil {
		return "", fmt.Errorf("%w: %v", ErrLeft, err)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		return "", err
	}
	tmp := fmt.Sprintf("%s.%d.tmp", path, os.Getpid())
	if err := os.WriteFile(tmp, []byte(text), 0o666); err != nil {
		return "", err
	}
	if err := os.Rename(tmp, path); err != nil {
		return "", err
	}
	if err := os.MkdirAll(run.Runs(), 0o777); err != nil {
		return "", err
	}
	id := time.Now().Format("20060102-1504-") + name
	dir := filepath.Join(run.Runs(), id)
	for n := 2; ; n++ {
		err := os.Mkdir(dir, 0o777)
		if err == nil {
			break
		}
		if !os.IsExist(err) {
			return "", err
		}
		dir = filepath.Join(run.Runs(), fmt.Sprintf("%s-%d", id, n))
	}
	if err := os.WriteFile(filepath.Join(dir, "task.md"), []byte(text), 0o666); err != nil {
		return "", err
	}
	if err := os.WriteFile(filepath.Join(dir, "log.txt"), nil, 0o666); err != nil {
		return "", err
	}
	keys := run.Fields("task_file", path)
	for _, key := range origin.Keys() {
		keys.Set(key, origin.Get(key))
	}
	start, err := launchForSeat(dir, state, keys)
	if err != nil {
		return "", err
	}
	return filepath.Base(dir), start()
}
