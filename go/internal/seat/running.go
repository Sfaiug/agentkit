package seat

import (
	"agentkit/internal/harness"
	"agentkit/internal/run"
	script "agentkit/internal/transcript"
)

// running is what a record's conversation last says it runs on, as Python's plugin `running`
// reads it: the newer of its last answer and its status line's report, and that one's moment.
// The error is the report's where its model cannot be read as its harness's answers name it.
func running(record *run.Object, reader harness.Reader) (model, effort any, at float64, found bool, err error) {
	model, effort, answered, found := reader.LastAnswer(record)
	at = script.Moment(answered)
	reported, said, saidAt, err := reader.Reported(record)
	if reported != "" && (!found || saidAt > at) {
		return reported, said, saidAt, true, err
	}
	return model, effort, at, found, err
}
