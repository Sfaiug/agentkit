package host

import "os/exec"

// Detach leaves cmd as it is: no seat's pane runs on Windows, where nothing asks for one.
func Detach(*exec.Cmd) {}
