package cli

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"

	"agentkit/internal/config"
)

func init() { commands["attach"] = attach }

// attach is the hop a client's `ak` makes to its server, Python's menu.client, or with none named
// and nothing asked the ak screen itself.  A hop that starts something first stays Python's: the
// update on the live checkout, the bridge on a Mac.  The hop is decided before the config is read,
// as Python's menu.main decides it before config.load: a client's own config never stops it.
func attach(args []string, out, errOut io.Writer) int {
	dry := contains(args, "--dry-run")
	alias := serverAlias()
	if onLiveCheckout() || alias == "" || contains(args, "--client") || contains(args, "--overlay") || !dry && runtime.GOOS == "darwin" {
		if err := config.Check(); err != nil {
			fmt.Fprintf(errOut, "ak attach: %s\n", err)
			return 2
		}
		if alias == "" || contains(args, "--overlay") {
			return akScreen(args, out, errOut)
		}
		return notImplemented(errOut, "attach")
	}
	if dry {
		fmt.Fprintf(out, "would run ssh -t %s ak --client\n", alias)
		return 0
	}
	ssh := exec.Command("ssh", "-t", alias, "ak", "--client")
	ssh.Stdin, ssh.Stdout, ssh.Stderr = os.Stdin, out, errOut
	var exited *exec.ExitError
	if err := ssh.Run(); err != nil && !errors.As(err, &exited) {
		fmt.Fprintf(errOut, "ak attach: cannot run ssh: %s\n", config.PyError(err))
		return 2
	}
	if status, ok := ssh.ProcessState.Sys().(syscall.WaitStatus); ok && status.Signaled() {
		return -int(status.Signal())
	}
	return ssh.ProcessState.ExitCode()
}

// serverAlias is the ssh alias install.sh records on a client, Python's config.server_alias.
func serverAlias() string {
	data, err := os.ReadFile(filepath.Join(config.Home(), "state", "server"))
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}

// onLiveCheckout is whether this program is ~/agentkit's own build (config.Running).  A program it
// cannot locate counts as on it, which leaves the hop to Python.
func onLiveCheckout() bool {
	self, live, err := config.Running()
	return err != nil || self == live
}
