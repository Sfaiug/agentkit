package browser

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/harness"
)

// Register prints `ak browser mcp-register` as Python's browser.mcp_register does: the
// registration and only the registration, in each harness's own config, so it stays an offline,
// local edit on any machine; `install` sets the shared server up.  A line printed before a config
// left to Python stays true: that harness is registered, and Python's run says so again.
func Register(out io.Writer) (int, error) {
	desktop := filepath.Join(config.Repo(), "tools", "desktop-mcp.py")
	if _, err := os.Stat(desktop); err != nil {
		return 0, fmt.Errorf("%s is missing; this checkout is incomplete", desktop)
	}
	names, err := config.ManifestNames()
	if err != nil {
		return 0, err
	}
	servers := []harness.Server{{Name: "browser", URL: mcpURL}, {Name: "desktop", Command: python(), Args: []string{desktop},
		Env: map[string]string{"DISPLAY": display, "XAUTHORITY": filepath.Join(config.UserHome(), ".local", "share", "browser-bridge", "Xauthority")}}}
	var unregistered []string
	for _, name := range names {
		done, err := harness.RegisterMCP(name, servers)
		if errors.Is(err, harness.ErrPython) {
			return 0, ErrPython
		}
		if err != nil {
			return 0, err
		}
		if done == "" {
			unregistered = append(unregistered, name)
		} else if !show(out, fmt.Sprintf("%-11s %s", name, done)) {
			return 0, nil
		}
	}
	if unregistered != nil && !show(out, "not registered, their plugins write no MCP entry: "+strings.Join(unregistered, ", ")+"; browser/bridge.py and tools/desktop-mcp.py --cli need none") {
		return 0, nil
	}
	show(out, fmt.Sprintf("%-11s one shared server at %s (%s); `ak browser install` sets it up", "browser", mcpURL, mcpUnit))
	return 0, nil
}

// python is the interpreter the desktop server, a Python tool, runs on, what Python's
// sys.executable is under bin/ak's `env python3`: the first on PATH, absolute, its links kept.  On
// a machine with none yet the entry names it bare, to work once there is one.
func python() string {
	found, err := exec.LookPath("python3")
	if err != nil && !errors.Is(err, exec.ErrDot) {
		return "python3"
	}
	if absolute, err := filepath.Abs(found); err == nil {
		return absolute
	}
	return found
}
