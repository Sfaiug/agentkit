package task

// FixTheCommand is the task for a given failing command, Python's FIX_THE_COMMAND.
const FixTheCommand = "Your checkout starts on the target branch's tip, fetched when this run " +
	"started: run the command below there first. If it " +
	"passes there now, run `ak hand-in not-needed \"<why>\"`, with no edits or PR. " +
	"Otherwise fix the root cause so it passes, and show it failing before the " +
	"fix and passing afterwards in your summary. If only the owner can decide, " +
	"run `ak hand-in blocked \"<question>\"`."
