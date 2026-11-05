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

func restartMenu(cursor string, errOut io.Writer) int {
	err := menuProgramError
	if err == nil {
		err = execMenu(menuProgram, os.Args, append(os.Environ(), "AK_MENU_CURSOR="+cursor))
	}
	fmt.Fprintf(errOut, "ak attach: cannot restart: %s\n", err)
	return 2
}
