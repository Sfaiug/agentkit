package update

import (
	"bytes"
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// KeepVerb is the unlisted command the tick starts a harness's background upgrade with, `ak
// harness-update <harness>`, where Python's starts `python3 -m agentkit.update <harness>`.
const KeepVerb = "harness-update"

const (
	askEvery   = 60 * 60      // Python's ASK_EVERY: seconds between two asks of a harness's latest release, at least
	retryAfter = 24 * 60 * 60 // Python's RETRY_AFTER: a gate can fail for what the release did not cause, so try it daily
)

// KeepCurrent is the tick's harness upgrade pass from the checkout at repo, Python's
// update.keep_current.  Only ~/agentkit's own tick does it, so a tick from a worktree, a test's
// above all, never upgrades this host's harnesses: it says what the last background upgrade said,
// then, while no upgrade runs, asks each harness this host has its `[update] latest` at most once
// an hour and starts the first one behind it in the background (Background).  A red release starts
// again once retryAfter has passed since its last start, a newer one at once.  A checkout that is
// somebody's work holds the upgrade unstarted, saying so, and a login its gates would not outlast
// holds it with no ask until the first tick that one lasts.  ErrPython, before anything is
// written, while a red's hand-back is owed to a seat, and before the ask of an installed harness
// Go could not start: one movable says Go moves none of, or any with no live gate.
func KeepCurrent(repo string, say func(string)) error {
	if !liveHere(repo) {
		return nil
	}
	if owed() {
		return ErrPython // Go types no line into a seat yet
	}
	base, err := config.ChildEnv()
	if err != nil {
		return ErrPython
	}
	env := append(slices.Clip(base), pins...)
	plans, err := harnesses()
	if err != nil {
		return err
	}
	if data, err := os.ReadFile(saidPath()); err == nil {
		if value, err := run.Decode(data); err == nil {
			os.Remove(saidPath())
			if said, ok := value.(*run.Object); ok {
				head := "the background upgrade of " + said.Str("harness") + ":"
				if said.Truthy("code") {
					head = "WARN the background upgrade of " + said.Str("harness") + " failed:"
				}
				say(head)
				for _, line := range said.List("lines") {
					text, _ := line.(string)
					say("  " + text)
				}
			}
		}
	}
	held, err := lock.Try(filepath.Join(config.Home(), "tmp", upgrades))
	if errors.Is(err, lock.ErrHeld) {
		return nil
	}
	if err != nil {
		return err
	}
	held.Close()
	record := filepath.Join(config.Home(), "state", "harness-latest.json")
	asked := run.NewObject()
	if data, err := os.ReadFile(record); err == nil {
		if value, err := run.Decode(data); err == nil {
			if object, ok := value.(*run.Object); ok {
				asked = object
			}
		}
	}
	checkout, at := filepath.Join(config.UserHome(), "agentkit"), now()
	for _, each := range plans {
		entry := cmp.Or(asked.Dict(each.name), run.NewObject())
		last, _ := entry.Num("asked")
		if each.latest == nil || harness.Binary(each.version[0]) == "" || !entry.Truthy("waits") && at-last < askEvery {
			continue
		}
		installed, err := version(each, env)
		if err != nil {
			return err
		}
		// one installed that Go could not start is Python's to ask: an ask handed over unrecorded
		// is asked twice
		if _, gone := liveGate(repo); installed != "" && (gone != nil || !movable([]plan{each})) {
			return ErrPython
		}
		newest := entry.Str("waits")
		if newest == "" {
			newest = latest(each, env)
		}
		tried, _ := entry.Get("tried").(string)
		started, _ := entry.Num("started")
		behind := installed != "" && downgrade(newest, installed) && (tried != newest || at-started >= retryAfter)
		left := ""
		if behind {
			left = leftAsIs(env, checkout)
		}
		begins := behind && left == ""
		waits := begins && waitsForLogin("upgrade", each.name+"'s upgrade",
			margin("live", liveCap)+margin("fresh", freshCap.Seconds()), at, say)
		entry.Set("asked", at)
		entry.Set("waits", "")
		if waits {
			entry.Set("waits", newest)
		} else if begins {
			entry.Set("tried", newest)
			entry.Set("started", at)
		}
		asked.Set(each.name, entry)
		if err := os.WriteFile(record, []byte(run.Line(asked)), 0o666); err != nil {
			return err
		}
		switch {
		case waits:
			return nil
		case left != "":
			say(fmt.Sprintf("%s %s is behind %s: upgraded once %s is main as origin left it, not %s: its gates test it",
				each.name, releaseOf(installed), newest, checkout, left))
		case begins:
			say(fmt.Sprintf("%s %s is behind %s: upgrading it in the background", each.name, releaseOf(installed), newest))
			return start(repo, base, each.name)
		}
	}
	return nil
}

// owed is whether a red's hand-back waits to be told, as Python's keep_current tells it: a
// harness's second red in a row, or the fresh-install gate's standing faults.
func owed() bool {
	state := filepath.Join(config.Home(), "state")
	checks, _ := filepath.Glob(filepath.Join(state, "harness-gates", "*", "handed"))
	for _, check := range checks {
		record := handed(check)
		if reds, _ := record["reds"].(float64); reds >= 2 && record["told"] != true {
			return true
		}
	}
	record := handed(filepath.Join(state, "fresh-gate-faults", "handed"))
	return len(record) > 0 && record["told"] != true
}

// latest is the release a harness's `[update] latest` names, as Python's update.latest: "" where
// it names none, fails, or is not back within a minute, as an ask of the network offline is.
func latest(each plan, env []string) string {
	if each.latest == nil {
		return ""
	}
	program := cmp.Or(harness.Binary(each.latest[0]), each.latest[0])
	stdout, _, code, err := output(env, gitCap, append([]string{program}, each.latest[1:]...)...)
	if err != nil || code != 0 {
		return ""
	}
	return releaseOf(string(stdout))
}

// saidPath is what the last background upgrade said: Background writes it, the tick reads it.
func saidPath() string {
	return filepath.Join(config.Home(), "state", "harness-update-said.json")
}

// start is Background for that harness, detached and unmarked: it outlives the tick that
// starts it, gates and all.
func start(repo string, env []string, name string) error {
	self, err := os.Executable()
	if err != nil {
		return err
	}
	child := exec.Command(self, KeepVerb, name)
	child.Dir, child.Env, child.SysProcAttr = repo, host.Unmarked(env), host.Detached()
	if err := child.Start(); err != nil {
		return err
	}
	return child.Process.Release()
}

// Background is `ak harness-update <harness>` from the checkout at repo, the tick's upgrade of
// one harness, Python's update.background: the upgrade `ak update` makes, of that harness alone,
// whether sessions work or not, as it replaces files and never a process; the exit code.  What it
// said is left in saidPath for the next tick to say, once.  With another upgrade running, or the
// harness no longer saying how it moves, it does nothing.
func Background(repo, name string) int {
	host.Mark("harness update")
	if config.EnsureDirs() != nil {
		return 1
	}
	held, err := lock.Try(filepath.Join(config.Home(), "tmp", upgrades))
	if errors.Is(err, lock.ErrHeld) {
		return 0
	}
	if err != nil {
		return 1
	}
	defer held.Close()
	plans, err := harnesses()
	at := slices.IndexFunc(plans, func(each plan) bool { return each.name == name })
	if err == nil && at < 0 {
		return 0 // no longer configured, or no longer says how it moves
	}
	var out bytes.Buffer
	code := 1
	if err == nil {
		code, err = upgradeAlone(repo, plans[at], &out)
	}
	if err != nil { // detached, it is heard only through what it said
		fmt.Fprintf(&out, "update: %s\n", config.PyError(err))
	}
	lines := []any{}
	for _, line := range config.SplitLines(out.String()) {
		lines = append(lines, line)
	}
	put(saidPath(), []byte(run.Line(run.Fields("harness", name, "code", code, "lines", lines))))
	return code
}

// upgradeAlone is the upgrade of that harness from the release it is on, its output and its
// errors both to out: the exit code.
func upgradeAlone(repo string, each plan, out io.Writer) (int, error) {
	env, err := config.ChildEnv()
	if err != nil {
		return 1, err
	}
	env = append(env, pins...)
	before, err := version(each, env)
	if err != nil {
		return 1, err
	}
	return upgradeHeld(env, repo, []plan{each}, map[string]string{each.name: before}, out, out), nil
}
