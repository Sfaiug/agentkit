package cli

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
)

// Remember the path before an install replaces the running image.
var menuProgram, menuProgramError = os.Executable()
var menuStarted = time.Now()

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
