package seat

import (
	"io"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Asleep is whether an older ak put that seat to sleep and it is not back yet (watch.slept): until
// ReopenSlept brings it back it is an open seat away from its prompt, kept, and owed what any is.
func Asleep(name string) bool {
	name, _, err := config.ResolveSession(name)
	if err != nil {
		return false
	}
	record, _ := run.ReadJSON(filepath.Join(config.Home(), "state", "session-"+name+".json"))
	file, _ := run.ReadJSON(seatFile(name))
	return record != nil && putToSleep(record, file)
}

// ReopenSlept is the tick's slept seats row (watch.reopen_slept): each seat an older ak put to
// sleep back on its own conversation, as after a reboot, its record's mark dropped once it is back
// or the owner closed it; one that does not come back keeps it, and is tried again at the next
// tick.  False, before anything of it is done, at the first seat whose reopen Go does not carry.
func ReopenSlept(log func(string)) (bool, error) {
	for _, path := range config.SeatFiles() {
		name, _ := sessionFile(filepath.Base(path))
		if record, _ := run.ReadJSON(path); record == nil || !record.Has("asleep") {
			continue
		}
		if Asleep(name) {
			carried, err := Reopen(name, How{Detached: true}, io.Discard, io.Discard)
			if !carried {
				return false, nil
			}
			if err != nil {
				log("WARN could not reopen " + name + ", which an older ak had put to sleep: " + config.PyError(err))
				continue
			}
			log("reopened " + name + ", which an older ak had put to sleep")
		}
		if err := Update(name, func(record *run.Object) bool { had := record.Has("asleep"); record.Delete("asleep"); return had }); err != nil {
			return true, err
		}
	}
	return true, nil
}
