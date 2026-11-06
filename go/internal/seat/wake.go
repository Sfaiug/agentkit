package seat

import (
	"io"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Asleep is whether ak put that seat to sleep since its harness launched, and the owner has not
// closed it since (sleep.asleep).
func Asleep(name string) bool {
	name, _, err := config.ResolveSession(name)
	if err != nil {
		return false
	}
	record, _ := run.ReadJSON(filepath.Join(config.Home(), "state", "session-"+name+".json"))
	file, _ := run.ReadJSON(seatFile(name))
	return record != nil && putToSleep(record, file)
}

// Wake brings a sleeping seat back on its conversation, through the reopen the tick's revival
// makes (sleep.wake): whether it is awake, one that did not come back staying asleep for what
// next wakes it.  Not carried where Go does not reopen that seat, before anything is done.
func Wake(name string, log func(string)) (awake, carried bool) {
	if !Asleep(name) {
		return true, true
	}
	opened, err := Reopen(name, How{Detached: true}, io.Discard, io.Discard)
	if err != nil {
		log("WARN could not wake " + name + ": " + err.Error())
		return false, true
	}
	if opened {
		log("woke " + name)
	}
	return opened, opened
}
