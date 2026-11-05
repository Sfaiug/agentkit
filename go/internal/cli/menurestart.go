package cli

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/terminal"
)

// Keep the launch path, including its symlink, before the menu can change directories.
var menuProgram, menuProgramError = menuLaunchPath()
var menuStarted = time.Now()

func menuLaunchPath() (string, error) {
	program, err := exec.LookPath(os.Args[0])
	if err != nil && !errors.Is(err, exec.ErrDot) {
		return "", err
	}
	return filepath.Abs(program)
}

func menuOutdated() bool {
	data, err := os.ReadFile(filepath.Join(config.Home(), "state", "installed-at"))
	if err != nil {
		return false
	}
	stamp, err := strconv.ParseFloat(strings.TrimSpace(string(data)), 64)
	return err == nil && stamp > float64(menuStarted.UnixNano())/1e9
}

// restartMenu starts the menu again on new code, handing on its last read and the frame up, which
// the terminal goes on showing until the new program writes it again.
func restartMenu(cursor string, last reading, keyboard *terminal.Keyboard, painter *terminal.Painter, errOut io.Writer) int {
	err := menuProgramError
	if err == nil {
		env := append(os.Environ(), "AK_MENU_CURSOR="+cursor)
		env = append(append(env, cross(menuRead, handOn(last))...), cross(menuFrame, painter.Up())...)
		err = keyboard.GiveHeld(func() error { return execMenu(menuProgram, os.Args, env) })
	}
	keyboard.Give() // where the program was never found, so nothing gave it
	fmt.Fprintf(errOut, "ak attach: cannot restart: %s\n", err)
	return 2
}
