package host

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/tmux"
)

// Where a run's driver and a lander go, as Python's orch.start_in_slice places them: each in a
// unit of its own in the runs slice under the user manager, capped, and started plainly where the
// manager will not take it.

const (
	RunWeight    = 40               // a run's CPU weight, above the seats'
	LanderWeight = cpuWeightMax     // every passed run waits behind a lander's check
	placeWait    = 30 * time.Second // how long the manager has to say whether it took a unit
	noSuchUnit   = 5                // what systemctl answers about a unit it was never given
)

// placedEnv names where placed work says it started (Placed).
const placedEnv = "AK_PLACED"

var leadingNumber = regexp.MustCompile(`^\s*(\d+)`)

// Limits are the `systemd-run -p` properties of a unit in the runs slice whose work holds capMB of
// memory at most, 0 for no cap, as Python's run.run_scope_limits: its CPU weight, and an I/O
// weight above the seats'.  Swap is capped at a quarter of the memory cap, room for the cold pages
// an idle process parks there and never for a runaway: with swap as large as the cap, a lander and
// several runs sat at both caps for hours, paging their test pieces, until the host's load reached
// 290 (24 Oct 2026), and a piece that overruns its memory should end quickly and be rerun.  Where
// the manager takes it, OOMPolicy=continue has the kernel end only the process that grew, not the
// whole unit.
func Limits(capMB, cpuWeight int) []string {
	limits := []string{"-p", fmt.Sprintf("CPUWeight=%d", cpuWeight)}
	if capMB <= 0 {
		return limits
	}
	limits = append(limits, "-p", "IOWeight=40", "-p", fmt.Sprintf("MemoryMax=%dM", capMB),
		"-p", fmt.Sprintf("MemorySwapMax=%dM", capMB/4))
	if oomPolicy() {
		limits = append(limits, "-p", "OOMPolicy=continue")
	}
	return limits
}

// oomPolicy is whether a unit here takes OOMPolicy=continue, Python's scope_oom_policy: a user
// manager of systemd 253 or later, by the manager's own answer, as an older systemd-run refuses
// the whole scope over it.  Asked once per process; no answer counts as older.
var oomPolicy = sync.OnceValue(func() bool {
	if !UserManager() {
		return false
	}
	ctx, cancel := context.WithTimeout(context.Background(), placeWait)
	defer cancel()
	show := exec.CommandContext(ctx, "systemctl", "--user", "show", "-p", "Version", "--value")
	show.Env = busEnv(os.Environ())
	said, _ := show.Output()
	found := leadingNumber.FindSubmatch(said)
	number := 0
	if found != nil {
		number, _ = strconv.Atoi(string(found[1]))
	}
	return number >= 253
})

// Placed is this program's word, first of all, that it started where Place put it: its pid,
// where AK_PLACED names, which only the placement's start hands it.  What it starts does not
// inherit the name.
func Placed() {
	if marker, set := os.LookupEnv(placedEnv); set {
		os.Unsetenv(placedEnv)
		os.WriteFile(marker, []byte(strconv.Itoa(os.Getpid())), 0o666)
	}
}

// FreeUnit is name, or where an earlier attempt's unit may hold it yet, as a run's is kept past
// its work's death for the reaper and a leftover may keep it, the first of name, name-2, … the
// manager has as neither a scope nor a service, Python's run_placement and next_scope_unit.  An
// attempt that left its claim keeps the name, Place asking about that one itself, and so does a
// manager that cannot be asked, Place's plain start following.
func FreeUnit(name string) (string, error) {
	if !UserManager() {
		return name, nil
	}
	if _, err := os.Stat(claimOf(name)); err == nil {
		return name, nil
	}
	for suffix := 1; suffix < 100; suffix++ {
		candidate := name
		if suffix > 1 {
			candidate = fmt.Sprintf("%s-%d", name, suffix)
		}
		held := false
		for _, kind := range []string{"scope", "service"} {
			loaded, answered := unitLoaded(candidate + "." + kind)
			if !answered {
				return name, nil
			}
			held = held || loaded
		}
		if !held {
			return candidate, nil
		}
	}
	return "", fmt.Errorf("no free systemd scope name for %s", name)
}

// SliceMemoryMax is the MemoryMax ak's slice's drop-ins set, in MiB, 0 for none.
func SliceMemoryMax() int {
	ceiling, _ := dropInMemoryMax(tmux.Own() + ".slice")
	return ceiling
}

// Place starts cmd, this program, its output appended to log and in a session of its own where
// detached, in unit, a unit of the runs slice under the user manager with those `systemd-run -p`
// properties: a scope where this process is in the manager's own subtree, since the kernel lets an
// unprivileged manager move only what it was delegated, else a service the manager starts there
// itself.  A foreground cmd goes only into a scope, which keeps its terminal: a service is the
// manager's.  pid is the work's; scope is its unit, or "none" and reason why.
//
// The work says for itself whether it started (Placed): its mark means it ran, however briefly,
// and no mark means nothing ran, so only then is it started plainly, as where no manager listens,
// with a WARN in its log.  Neither timing nor a status tells a task that ended at once from one
// that never began.  Where the mark goes is in the work's environment, never its command, which
// systemd expands, a scope's from 258 and a service's always.  An attempt leaves a claim until it
// is resolved: while the unit an earlier attempt claims is loaded, or the manager cannot say,
// nothing starts, and where a placement can be neither confirmed nor ended neither does the plain
// start, as a second start of the work is worse than none.
func Place(cmd *exec.Cmd, log, unit string, properties []string, detached bool) (pid int, scope, reason string, err error) {
	out, err := os.OpenFile(log, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666)
	if err != nil {
		return 0, "", "", err
	}
	defer out.Close()
	cmd.Stdout, cmd.Stderr = out, out
	if detached {
		cmd.SysProcAttr = Detached()
	}
	tmp := filepath.Join(config.Home(), "tmp")
	claim, marker := claimOf(unit), filepath.Join(tmp, unit+".launched")
	// read before the host is even asked for a manager: a unit that may still come up is the reason
	// not to start, and a manager that cannot be asked no reason to believe it gone
	data, _ := os.ReadFile(claim)
	if held := strings.TrimSpace(string(data)); held != "" {
		// no answer counts as there: anything under it may yet run
		if loaded, answered := unitLoaded(held); loaded || !answered {
			return 0, "", "", fmt.Errorf("%s from an earlier start is still in %s.slice; the work is not started again beside it (its claim is %s)",
				held, tmux.Own(), claim)
		}
	}
	os.Remove(claim)
	scoped := cgroupContains(fmt.Sprintf("user@%d.service", os.Getuid()))
	switch {
	case !UserManager():
		return plain(cmd, "no user systemd manager")
	case !scoped && !detached:
		return plain(cmd, "started outside the user manager, which cannot move it")
	}
	if err := os.MkdirAll(tmp, 0o700); err != nil {
		return 0, "", "", err
	}
	os.Remove(marker)
	runs := filepath.Base(RunsCgroup())
	env := cmd.Environ()
	work := append([]string{cmd.Path}, cmd.Args[1:]...)
	words, kind := []string{"--user", "--slice=" + runs, "--quiet", "--unit=" + unit}, "scope"
	if scoped {
		words = append(append(append(words, "--scope"), properties...), "--")
		words = append(words, work...)
	} else {
		// a service starts with the manager's environment and output, so this process's go by name,
		// and a unit's command line reads a dollar as a variable's and `$$` as one dollar
		kind = "service"
		words = append(append(words, "--collect", "--property=StandardOutput=append:"+log), properties...)
		for _, pair := range append(env, placedEnv+"="+marker) {
			words = append(words, "--setenv="+pair)
		}
		words = append(words, "--")
		for _, word := range work {
			words = append(words, strings.ReplaceAll(word, "$", "$$"))
		}
	}
	client := exec.Command("systemd-run", words...)
	client.Env = append(busEnv(env), placedEnv+"="+marker) // a scope's client becomes its work
	client.Stdout, client.Stderr, client.SysProcAttr = out, out, cmd.SysProcAttr
	// written before the launch: a start this process does not live to finish is still an attempt
	if err := os.WriteFile(claim, []byte(unit+"."+kind), 0o666); err != nil {
		return 0, "", "", err
	}
	note := "nothing started in it"
	if err := client.Start(); err != nil {
		note = err.Error()
	} else {
		gone := make(chan struct{})
		go func() { client.Wait(); close(gone) }() // a scope's client becomes the work, reaped here
		// a scope's client waits on the manager before the work exists and goes with a scope the
		// manager never made; a service's is gone either way, so none (nil) ends the wait early
		var parent <-chan struct{}
		refused := false
		if scoped {
			parent = gone
		} else {
			// gone once the manager has the unit, so its status says whether there is anything to
			// wait for, and the mark whether the work was forked
			select {
			case <-gone:
				if code := client.ProcessState.ExitCode(); code != 0 {
					refused, note = true, fmt.Sprintf("systemd-run exited %d", code)
				}
			case <-time.After(placeWait):
			}
		}
		if !refused {
			if pid := marked(marker, parent); pid > 0 {
				os.Remove(claim)
				return pid, unit, "", nil
			}
			select {
			case <-parent: // gone without a mark: nothing of it is left to come up
			default:
				if !stopPlaced(unit, scoped, client) {
					// never said it ran, never refused, and not ended either: the manager may yet
					// bring it up, so the claim stays for whoever tries next
					return 0, "", "", fmt.Errorf("%s is neither running in %s.slice nor stopped", unit, tmux.Own())
				}
			}
		}
	}
	os.Remove(claim)
	fmt.Fprintf(out, "%sWARN %s did not go into %s (%s); started plainly\n", time.Now().Format("[15:04:05] "), unit, runs, note)
	return plain(cmd, "systemd-run failed ("+note+")")
}

// claimOf is where an attempt to place work in unit says so until it is resolved.
func claimOf(unit string) string { return filepath.Join(config.Home(), "tmp", unit+".placed") }

// plain starts cmd as it is, and reaps it: a zombie still answers as alive.
func plain(cmd *exec.Cmd, reason string) (int, string, string, error) {
	if err := cmd.Start(); err != nil {
		return 0, "", "", err
	}
	go cmd.Wait()
	return cmd.Process.Pid, "none", reason, nil
}

// marked is the pid the placed work wrote for itself as it started, 0 where none came
// within placeWait or before gone closed: a scope the manager never made takes its client with it.
func marked(marker string, gone <-chan struct{}) int {
	defer os.Remove(marker)
	for deadline := time.Now().Add(placeWait); ; time.Sleep(20 * time.Millisecond) {
		// read before the mark, so a client gone between the two is not believed over its mark
		ended := false
		select {
		case <-gone:
			ended = true
		default:
		}
		data, _ := os.ReadFile(marker)
		if text := strings.TrimSpace(string(data)); text != "" && config.Digits(text) {
			pid, _ := strconv.Atoi(text)
			return pid
		}
		if ended || time.Now().After(deadline) {
			return 0
		}
	}
}

// stopPlaced ends a placement still on its way, true where nothing of it can come up.  A scope's
// is its client alone, which becomes the work and starts nothing before the mark.  A service is
// the manager's, and only its word counts: stopped, or a unit it does not have.
func stopPlaced(unit string, scoped bool, client *exec.Cmd) bool {
	client.Process.Kill()
	if scoped {
		return true
	}
	ctx, cancel := context.WithTimeout(context.Background(), placeWait)
	defer cancel()
	stop := exec.CommandContext(ctx, "systemctl", "--user", "stop", unit+".service")
	stop.Env = busEnv(os.Environ())
	err := stop.Run()
	var exited *exec.ExitError
	return ctx.Err() == nil && (err == nil || errors.As(err, &exited) && exited.ExitCode() == noSuchUnit)
}

// unitLoaded is whether the manager still has that unit, Python's unit_loaded: a transient unit
// that ended is collected, `not-found`.  answered is false where the manager could not be asked.
func unitLoaded(unit string) (loaded, answered bool) {
	ctx, cancel := context.WithTimeout(context.Background(), placeWait)
	defer cancel()
	show := exec.CommandContext(ctx, "systemctl", "--user", "show", unit, "-p", "LoadState", "--value")
	show.Env = busEnv(os.Environ())
	said, err := show.Output()
	if err != nil {
		return false, false
	}
	return strings.TrimSpace(string(said)) != "not-found", true
}
