package terminal

// Write puts nothing on a terminal: no tmux client on Windows has a tty path to write to.
func Write(string, []byte) bool { return false }
