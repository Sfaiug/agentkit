package googlecloud

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/host"
)

const (
	user, setUp = "ak", "/run/ak-ready" // a machine's user for ak, and what says it is set up
	// A machine that held nothing this long goes back. A new machine's first suite pays about a
	// minute to boot and 4.5 to receive a whole history and build its image (measured 30 Oct
	// 2026), and the tick looks only every pass; ten idle minutes of the machines ak rents cost
	// about €0.10.
	idleFor = 600
)

// idle is how long each of listed with an address has held nothing, in seconds by id, -1 while it
// is still setting up, asked side by side over ssh by tools/helper's `idle`, whose line it is given
// (google_cloud._idle); none of one that did not answer, nor of any where ssh cannot run here.
// ak's ssh key is made where missing, and the address of one with no route yet forgotten first, as
// Google hands addresses out again and ssh refuses an old host key there. Past that, a key ssh
// learned stays: Google's agent writes it before sshd first starts.
func idle(listed []Machine, line string) map[string]int {
	known := secret("google-cloud-known-hosts")
	if _, err := os.Stat(secret("google-cloud-ssh")); err != nil && keygen("-q", "-t", "ed25519", "-N", "", "-C", user, "-f", secret("google-cloud-ssh")) != nil {
		return nil
	}
	routes := routes()
	var reached [][]string
	var ids []string
	for _, one := range listed {
		if one.Address == "" {
			continue
		}
		if !strings.Contains(routes, "Host "+one.Name+"\n") && !ran(keygen("-R", one.Address, "-f", known)) {
			return nil
		}
		var options []string
		for _, option := range reach(one) {
			options = append(options, "-o", fmt.Sprintf(`%s="%s"`, option[0], option[1]))
		}
		reached = append(reached, host.SSH(one.Name, "if test -e "+setUp+"; then "+line+"; else echo -1; fi", options...))
		ids = append(ids, one.ID)
	}
	if err := os.Remove(known + ".old"); err != nil && !errors.Is(err, fs.ErrNotExist) { // ssh-keygen's copy
		return nil
	}
	held := map[string]int{}
	for i, said := range host.Ask(reached) {
		if said == nil {
			continue
		}
		answer := strings.TrimSpace(*said)
		digits := strings.TrimPrefix(answer, "-")
		seconds, _ := strconv.Atoi(answer) // past an int, its most, as Python's int is no less
		if digits == "" || strings.Trim(digits, "0123456789") != "" {
			seconds = 0 // an answer of no number holds nothing
		}
		held[ids[i]] = seconds
	}
	return held
}

// reach is how ssh reaches machine: at its address as ak's user by ak's key alone, its host key
// learned (google_cloud._reach).
func reach(machine Machine) [][2]string {
	return [][2]string{{"HostName", machine.Address}, {"User", user},
		{"IdentityFile", secret("google-cloud-ssh")}, {"IdentitiesOnly", "yes"},
		{"UserKnownHostsFile", secret("google-cloud-known-hosts")}, {"StrictHostKeyChecking", "accept-new"}}
}

// serve writes the ssh config whole: each of machines as ssh reaches it, with its end where it
// answered set up, which Serving reads, then every other as ever (google_cloud._serve). One that
// missed an answer keeps its route, as the work it holds still calls it, and gets no new work.
func serve(machines []Machine, held map[string]int) error {
	var text strings.Builder
	for _, one := range machines {
		text.WriteString("Host " + one.Name + "\n")
		if seconds, answered := held[one.ID]; answered && seconds >= 0 {
			fmt.Fprintf(&text, "  # until %d\n", int64(one.Until))
		}
		for _, option := range reach(one) {
			fmt.Fprintf(&text, "  %s \"%s\"\n", option[0], option[1])
		}
	}
	return save(routesPath(), text.String()+"Host *\n  Include ~/.ssh/config\n")
}

// keygen is ssh-keygen run to its end, its output dropped.
func keygen(args ...string) error { return exec.Command("ssh-keygen", args...).Run() }

// ran is whether a program started, whatever it exited with.
func ran(err error) bool {
	var exited *exec.ExitError
	return err == nil || errors.As(err, &exited)
}

func secret(name string) string { return filepath.Join(config.Home(), "secrets", name) }
