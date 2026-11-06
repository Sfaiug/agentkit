package install

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	"agentkit/internal/config"
)

// cronTag marks the tick's line as ak's; `ak move` reads it to see a tick on the machine it
// would copy to.
const cronTag = "# agentkit watch"

// cronTagged is the tag with its `#`s and spacing loose, so a pause retyped or commented out
// again by hand is still ak's.
var cronTagged = regexp.MustCompile(`#+[[:space:]]*agentkit[[:space:]]+watch([[:space:]]|$)`)

// cron keeps a server's tick, which moves every run, landing and stalled seat: one crontab line
// running this program's `watch` every three minutes, as install.sh's step (g) does.  Every
// line carrying the tag goes first, the live one or a copy the owner commented out to pause the
// tick, and the owner's other lines stay.  A table already so is not written again.
func cron(sandboxed bool, out, errOut io.Writer) error {
	if sandboxed {
		fmt.Fprintln(out, "server: sandbox HOME, so the ak watch cron is not installed")
		return nil
	}
	executable, err := os.Executable()
	if err != nil {
		return err
	}
	// cron's own PATH holds neither ak nor a harness
	home := config.UserHome()
	line := fmt.Sprintf("*/3 * * * * PATH=%s:%s:/usr/local/bin:/usr/bin:/bin %s watch >>%s 2>&1 %s",
		filepath.Join(home, ".local", "bin"), filepath.Join(home, ".npm-global", "bin"),
		config.Resolve(executable), filepath.Join(config.Home(), "tmp", "watch.log"), cronTag)
	// what a failing `crontab -l` printed counts too: an account with no table yet has none
	listed, err := exec.Command("crontab", "-l").Output()
	if errors.Is(err, exec.ErrNotFound) {
		fmt.Fprintln(errOut, "note: no crontab here; run `ak watch` every three minutes some other way")
		return nil
	}
	current := strings.TrimRight(string(listed), "\n")
	var wanted []string
	for _, kept := range strings.Split(current, "\n") {
		if current != "" && !cronTagged.MatchString(kept) {
			wanted = append(wanted, kept)
		}
	}
	table := strings.Join(append(wanted, line), "\n")
	if table == current {
		fmt.Fprintln(out, "server: the ak watch cron is already installed")
		return nil
	}
	write := exec.Command("crontab", "-")
	write.Stdin, write.Stdout, write.Stderr = strings.NewReader(table+"\n"), out, errOut
	// a table crontab refuses is its own words, and the install goes on, as install.sh's does
	if write.Run() == nil {
		fmt.Fprintln(out, "server: ak watch runs every three minutes from cron")
	}
	return nil
}
