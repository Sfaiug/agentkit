package config

import "path/filepath"

// TickLog is the tick's own log (watch.log_path): cron redirects the tick into it, and tmux's hooks
// the verbs they run, whose output tmux would otherwise draw over a seat's pane.
func TickLog() string { return filepath.Join(Home(), "tmp", "watch.log") }
