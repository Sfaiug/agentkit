package loop

import "agentkit/internal/run"

// endWord is the line bin/ak ends Python's run process on when it ended in error, whose stderr is
// the run's log, which a terminal following it reads; a foreground --no-merge launch is that
// process itself (Follow).
func endWord(dir string) {
	record, _ := run.Read(dir)
	if record == nil || record.Str("state") != "error" || !record.Truthy("error") {
		return
	}
	if opts := launchOpts(record); opts == nil || !opts.Truthy("--no-merge") || opts.Truthy("--bg") {
		appendLog(dir, "ak run: "+record.Str("error")+"\n")
	}
}
