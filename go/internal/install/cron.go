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
	path := filepath.Join(home, ".local", "bin") + ":" + filepath.Join(home, ".npm-global", "bin") +
		":/usr/local/bin:/usr/bin:/bin"
	line := fmt.Sprintf("*/3 * * * * PATH=%s %s watch >>%s 2>&1 %s", cronWord(path),
		cronWord(config.Resolve(executable)), cronWord(config.TickLog()),
		cronTag)
	listed, err := exec.Command("crontab", "-l").Output()
	if errors.Is(err, exec.ErrNotFound) {
		fmt.Fprintln(errOut, "note: no crontab here; run `ak watch` every three minutes some other way")
		return nil
	}
	// every crontab exits 1 for an account with no table yet; any other failure is a table it
	// could not read, and writing would replace the owner's jobs with ak's line alone
	var exit *exec.ExitError
	if err != nil && !(errors.As(err, &exit) && exit.ExitCode() == 1) {
		fmt.Fprintln(errOut, "note: the crontab could not be read, so the ak watch cron is not installed; `crontab -l` says why")
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

// cronWord is text as one single-quoted word to the sh cron hands the line to, each % stepping
// out of the quotes as \%: cron reads a backslash and the next character as a pair, makes \% a %
// and ends the command at any other %, so no backslash of the text's comes right before it.
func cronWord(text string) string {
	return "'" + strings.NewReplacer("'", `'\''`, "%", `'\%'`).Replace(text) + "'"
}
