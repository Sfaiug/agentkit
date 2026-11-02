package seat

import (
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Keep keeps that question back for its turn's end, after those the seat kept already: a turn
// that asks twice asks both once it ends (watch.keep).  The seat's newer word ends its `ak wait`.
func Keep(name, text string) error {
	if err := config.EnsureDirs(); err != nil {
		return err
	}
	question := run.NewObject()
	question.Set("text", text)
	question.Set("at", run.Float(seconds(time.Now())))
	question.Set("id", nil)
	path := seatFile(name)
	return put(path, strings.TrimSuffix(path, ".json")+".lock", run.Line, true, func(data *run.Object) bool {
		kept := append(questionsKept(data.Dict("unasked"), nil), question)
		return set([]field{{"unasked", keptRecord(kept)}, {"wait", nil}}, field{"session", name})(data)
	})
}
