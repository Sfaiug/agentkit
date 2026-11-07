package task

// FixTheCommand is the task for a given failing command, Python's FIX_THE_COMMAND: the run checks
// the command on the target's tip before its first turn (loop's tipcheck.go).
const FixTheCommand = "Your checkout starts on the target branch's tip, fetched when this run " +
	"started. ak checked the command below there before your first turn. " +
	"Fix the root cause so it passes, and show it failing before the " +
	"fix and passing afterwards in your summary. If only the owner can decide, " +
	"run `ak hand-in blocked \"<question>\"`."
