package host

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/tmux"
)

// Where a run's driver and a lander go, as Python's orch.start_in_slice places them: each in a
// unit of its own in the runs slice under the user manager, capped, and started plainly where the
// manager will not take it.  agentkit's live check goes in ak's own slice (PlaceIn).

const (
	RunWeight    = 40           // a run's CPU weight, above the seats'
	LanderWeight = cpuWeightMax // every passed run waits behind a lander's check
	noSuchUnit   = 5            // what systemctl answers about a unit it was never given
)

// placeWait is how long the manager has to say whether it took a unit.
var placeWait = 30 * time.Second

// placedEnv names where placed work says it started (Placed).
const placedEnv = "AK_PLACED"

// versionNumber is the major version in what systemd says of itself: `257.13-1~deb13u1` from a
// manager, `systemd 257 (257.13-1~deb13u1)` from a client.
var versionNumber = regexp.MustCompile(`^\s*(?:systemd )?(\d+)`)

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
	return UserManager() && version("systemctl", "--user", "show", "-p", "Version", "--value") >= 253
})

// literal is the switch that keeps a scope's command word for word where a word holds a dollar,
// Python's seat_scope_run: from systemd 258 a scope's client expands `${NAME}` and `$$` there, as
// a service's manager does, unless told not to, which a client from 254 takes and an older one
// refuses with the scope.  A command with no dollar reads the same either way, so only one with
// a dollar has the client asked.
func literal(work []string) []string {
	if slices.ContainsFunc(work, func(word string) bool { return strings.Contains(word, "$") }) && clientVersion() >= 254 {
		return []string{"--expand-environment=no"}
	}
	return nil
}

// clientVersion is systemd-run's own: the client expands a scope's command, and an upgrade leaves
// the manager running the version it started with.  Asked once per process.
var clientVersion = sync.OnceValue(func() int { return version("systemd-run", "--version") })

// version is the major version a systemd program says it is, 0 where it says none.
func version(name string, args ...string) int {
	ctx, cancel := context.WithTimeout(context.Background(), placeWait)
	defer cancel()
	ask := exec.CommandContext(ctx, name, args...)
	ask.Env = busEnv(os.Environ())
	said, _ := ask.Output()
	number := 0
	if found := versionNumber.FindSubmatch(said); found != nil {
		number, _ = strconv.Atoi(string(found[1]))
	}
	return number
}

// Placed is this program's word, first of all, that it started where Place put it: its pid,
// where AK_PLACED names, which only the placement's start hands it.  What it starts does not
// inherit the name.  A program that cannot give its word does nothing, as no mark says nothing
// ran and Place starts the work again.
func Placed() {
	if marker, set := os.LookupEnv(placedEnv); set {
		os.Unsetenv(placedEnv)
		if err := os.WriteFile(marker, []byte(strconv.Itoa(os.Getpid())), 0o666); err != nil {
			fmt.Fprintln(os.Stderr, "ak: cannot say it started where it was placed:", err)
			os.Exit(1)
		}
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

// Place is PlaceIn the runs slice, where a run's driver and a lander go.
func Place(cmd *exec.Cmd, log, unit string, properties []string, detached bool) (pid int, scope, reason string, err error) {
	return PlaceIn(filepath.Base(RunsCgroup()), cmd, log, unit, properties, detached)
}

// PlaceIn starts cmd, this program, its output appended to log and in a session of its own where
// detached, in unit, a unit of slice under the user manager with those `systemd-run -p`
// properties: a scope where this process is in the manager's own subtree, since the kernel lets an
// unprivileged manager move only what it was delegated, else a service the manager starts there
// itself.  A foreground cmd goes only into a scope, which keeps its terminal: a service is the
// manager's.  pid is the work's; scope is its unit, or "none" and reason why.
//
// Each start is decided in Python's order (_start_in_slice).  The work says for itself whether it
// started (Placed): its mark means it ran, however briefly.  A scope's client gone without one,
// or a service's that exits non-zero, is the manager's refusal, and the work starts plainly, as
// where no manager listens, with a WARN in its log.  Where no mark comes in time otherwise, the
// placement is stopped first, and a mark there once it is stopped is a start too: neither timing
// nor a status tells a task that ended at once from one that never began.  Where the mark goes is
// in the work's environment: its command reaches it word for word, a scope's kept literal and a
// service's dollars doubled.  An attempt leaves a claim until it is resolved: while the unit an
// earlier attempt claims is loaded, or the manager cannot say, nothing starts, and where a
// placement can be neither confirmed nor ended neither does the plain start, as a second start of
// the work is worse than none.
func PlaceIn(slice string, cmd *exec.Cmd, log, unit string, properties []string, detached bool) (pid int, scope, reason string, err error) {
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
	defer os.Remove(marker)
	env := cmd.Environ()
	command := append([]string{cmd.Path}, cmd.Args[1:]...)
	words, kind := []string{"--user", "--slice=" + slice, "--quiet", "--unit=" + unit}, "scope"
	if scoped {
		words = append(append(words, "--scope"), literal(command)...)
		words = append(append(append(words, properties...), "--"), command...)
	} else {
		// a service starts with the manager's environment and output, so this process's go by name,
		// and a unit's command line reads a dollar as a variable's and `$$` as one dollar
		kind = "service"
		words = append(append(words, "--collect", "--property=StandardOutput=append:"+log), properties...)
		for _, pair := range append(env, placedEnv+"="+marker) {
			words = append(words, "--setenv="+pair)
		}
		words = append(words, "--")
		for _, word := range command {
			words = append(words, strings.ReplaceAll(word, "$", "$$"))
		}
	}
	client := exec.CommandContext(context.Background(), "systemd-run", words...) // Group's stop is its Cancel
	client.Env = append(busEnv(env), placedEnv+"="+marker)                       // a scope's client becomes its work
	client.Stdout, client.Stderr, client.SysProcAttr = out, out, cmd.SysProcAttr
	// what a stop ends: a detached client's session, with whatever it forked, as a foreground one
	// shares its caller's and is the work alone
	end := func() { client.Process.Kill() }
	if detached {
		end = Group(client)
	}
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
		// manager never made, and a service's is gone once the manager has the unit or refused it,
		// which its status says: either refusal ends the wait for the mark, read even then, as a
		// client can fail after its manager ran the work.  A taken service's work is the manager's
		// to start, so nothing ends that wait early.
		until := gone
		if !scoped {
			select {
			case <-gone:
				if code := client.ProcessState.ExitCode(); code != 0 {
					note = fmt.Sprintf("systemd-run exited %d", code)
				} else {
					until = nil
				}
			case <-time.After(placeWait):
				until = nil
			}
		}
		pid, refused := marked(marker, until)
		if pid == 0 && !refused {
			if !stopPlaced(unit, scoped, end, gone) {
				// never said it ran, and not ended either: the manager may yet bring it up, so
				// the claim stays for whoever tries next
				return 0, "", "", fmt.Errorf("%s is neither running in %s.slice nor stopped", unit, tmux.Own())
			}
			if mark(marker) > 0 {
				os.Remove(claim)
				return 0, "", "", fmt.Errorf("%s said it ran as it was stopped in %s.slice; the work is not started again", unit, tmux.Own())
			}
		}
		if pid > 0 {
			os.Remove(claim)
			return pid, unit, "", nil
		}
	}
	os.Remove(claim)
	fmt.Fprintf(out, "%sWARN %s did not go into %s (%s); started plainly\n", time.Now().Format("[15:04:05] "), unit, slice, note)
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

// marked is the pid the placed work wrote for itself as it started, 0 where none came within
// placeWait or before gone closed, which ended says: no mark comes after.
func marked(marker string, gone <-chan struct{}) (pid int, ended bool) {
	for deadline := time.Now().Add(placeWait); ; time.Sleep(20 * time.Millisecond) {
		// read before the mark, so a client gone between the two is not believed over its mark
		select {
		case <-gone:
			ended = true
		default:
		}
		if pid = mark(marker); pid > 0 || ended || time.Now().After(deadline) {
			return pid, ended
		}
	}
}

// mark is the pid the placed work wrote for itself, 0 where it wrote none.
func mark(marker string) int {
	data, _ := os.ReadFile(marker)
	if text := strings.TrimSpace(string(data)); text != "" && config.Digits(text) {
		pid, _ := strconv.Atoi(text)
		return pid
	}
	return 0
}

// stopPlaced ends a placement still on its way, true where nothing of it can come up, nor write
// its mark.  A scope's is what end ends, done once its client is gone.  A service is the
// manager's, and only its word counts: stopped, or a unit it does not have.
func stopPlaced(unit string, scoped bool, end func(), gone <-chan struct{}) bool {
	end()
	if scoped {
		<-gone
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
