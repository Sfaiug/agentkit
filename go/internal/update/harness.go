package update

import (
	"cmp"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"time"
	"unicode"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/seat"
)

const swapsKept = 16 // Python's SWAPS_KEPT: the latest installs and reverts state/harness-swaps.json keeps

var (
	// build is a release with its build, 1.4.1-R4503.1, Python's BUILD: a newer build of the same
	// release is a newer release
	build = regexp.MustCompile(`\p{Nd}+\.\p{Nd}+\.\p{Nd}+-R\p{Nd}+(?:\.\p{Nd}+)*`)
	// versionWord is what `[update] revert`'s {version} stands for, Python's VERSION: a release
	// and what follows it up to a space or a bracket
	versionWord = regexp.MustCompile(`\p{Nd}+\.\p{Nd}+\.\p{Nd}+[^` + strings.Trim(config.SpaceClass, "[]") + `()]*`)
	digits      = regexp.MustCompile(`\p{Nd}+`)
)

// An upgrade is one run of Python's update.upgrade: the harnesses it moves, the release each
// began on, the log every command of it writes to, and the snapshot of the one that has one.
type upgrade struct {
	env         []string
	repo        string
	plans       []plan
	before      map[string]string
	log         *os.File
	out, errOut io.Writer
	snapshotted plan      // the harness put back from a snapshot, the first whose manifest has one
	snapshot    *snapshot // until a restore uses it up
}

// movable is whether Go moves these harnesses as Python's update.main would, asked before
// anything is written: with no seat on record, as Go reads no seat's word yet; with no user
// systemd manager, which would put the live gate in ak's slice; and with a snapshot Go can take.
func movable(plans []plan) bool {
	home, known := seat.Read(time.Now())
	if !known || !home.Seatless() || host.UserManager() {
		return false
	}
	at := slices.IndexFunc(plans, func(each plan) bool { return each.snapshot != nil })
	if at >= 0 {
		_, _, err := layout(plans[at])
		return err == nil
	}
	return true
}

// upgradeAll is Python's update.main once harnesses here are to move: under the lock that keeps
// two upgrades apart host-wide, the tick's own included; the exit code.
func upgradeAll(env []string, repo string, plans []plan, before map[string]string, out, errOut io.Writer) int {
	tmp := filepath.Join(config.Home(), "tmp")
	held, err := lock.Try(filepath.Join(tmp, upgrades))
	if errors.Is(err, lock.ErrHeld) {
		fmt.Fprintln(out, "update: harnesses: skipped: another upgrade is running; try when it is done")
		return 0
	}
	if err != nil {
		fmt.Fprintf(errOut, "update: %s\n", pyError(err))
		return 1
	}
	defer held.Close()
	// a move of ~/agentkit under way ends before anything here reads it; any later one waits
	// for this upgrade to end (moveAgentkit)
	move, err := lock.Wait(context.Background(), filepath.Join(tmp, moving))
	if err != nil {
		fmt.Fprintf(errOut, "update: %s\n", pyError(err))
		return 1
	}
	move.Close()
	log, err := os.CreateTemp(tmp, "update-"+time.Now().Format("20060102-150405")+"-*.log")
	if err != nil {
		fmt.Fprintf(errOut, "update: %s\n", pyError(err))
		return 1
	}
	defer log.Close()
	defer retain(log.Name())()
	u := &upgrade{env: env, repo: repo, plans: plans, before: before, log: log, out: out, errOut: errOut}
	if at := slices.IndexFunc(plans, func(each plan) bool { return each.snapshot != nil }); at >= 0 {
		u.snapshotted = plans[at]
	}
	return u.run()
}

// run is Python's update.upgrade: each harness's upgrade, the gates, and what goes back; the
// exit code.
func (u *upgrade) run() int {
	before, logPath := u.before, u.log.Name()
	if name := u.snapshotted.name; name != "" {
		var err error
		if before[name] == "" {
			err = fmt.Errorf("installed %s failed its pinned version check", name)
		} else {
			u.snapshot, err = take(u.snapshotted, before[name], u.env)
		}
		if err != nil {
			fmt.Fprintf(u.errOut, "update: %s; nothing was upgraded; the gate was not run\n", err)
			return 1
		}
		fmt.Fprintf(u.out, "update: %s snapshot verified at %s\n", name, u.snapshot.path)
		fmt.Fprintf(u.log, "%s snapshot: %s\n", name, u.snapshot.path)
	}
	var upgraded, failed, missing []string
	for _, each := range u.plans {
		if before[each.name] == "" {
			missing = append(missing, each.name)
			fmt.Fprintf(u.out, "update: %s failed its version check; nothing to upgrade\n", each.name)
			continue
		}
		note := ""
		if each.name == u.snapshotted.name {
			note = " (local rollback snapshot: " + u.snapshot.path + ")"
		}
		fmt.Fprintf(u.out, "update: upgrading %s from %s%s\n", each.name, before[each.name], note)
		if u.swap(each, each.upgrade) {
			upgraded = append(upgraded, each.name)
		} else {
			failed = append(failed, each.name)
			fmt.Fprintf(u.out, "update: WARN upgrading %s failed; see %s\n", each.name, logPath)
		}
	}
	after := u.versions()
	for _, name := range upgraded {
		if after[name] == "" {
			failed = append(failed, name)
		}
	}
	// A channel that moved backwards is not an upgrade: whatever it installed goes back before
	// the gate sees a downgraded box, and the report keeps what was installed.
	downgraded := map[string]string{}
	var back []plan
	for _, each := range u.plans {
		if old, now := before[each.name], after[each.name]; downgrade(old, now) {
			downgraded[each.name] = fmt.Sprintf("installed %s is newer than the channel's %s", releaseOf(old), releaseOf(now))
			fmt.Fprintf(u.out, "update: %s: kept: %s\n", each.name, downgraded[each.name])
			back = append(back, each)
		}
	}
	if len(back) > 0 {
		u.revert(back, after)
		after = u.versions()
		for _, each := range back {
			if after[each.name] != before[each.name] {
				failed = append(failed, each.name)
			}
		}
	}
	changed := moved(u.plans, before, after)
	// Upgrading every one of them is the job: one left behind is named and costs the exit code,
	// and nothing is worth verifying, so whatever moved goes back and no gate runs.
	trouble, why := map[string]string{}, []string{}
	for _, name := range failed {
		if trouble[name] == "" {
			trouble[name] = name + " could not be upgraded"
			why = append(why, trouble[name])
		}
	}
	for _, name := range missing {
		trouble[name] = name + " failed its version check"
		why = append(why, trouble[name])
	}
	if len(trouble) > 0 {
		landed := u.revert(u.plans, after)
		head := strings.Join(upgraded, ", ") + " did not move"
		if len(upgraded) == 0 {
			head = "nothing was upgraded"
		} else if len(changed) > 0 {
			head = strings.Join(changed, ", ") + ", and then undone where it could be: a part of an upgrade is not one"
		}
		fmt.Fprintf(u.errOut, "update: %s (%s); the gate was not run -- see %s\n", head, strings.Join(why, "; "), logPath)
		report(u.plans, landed, u.errOut)
		for _, each := range u.plans { // one that installed fine counts no red: no gate judged it
			if trouble[each.name] != "" {
				gateResult([]plan{each}, false, "", logPath, []string{trouble[each.name]})
			}
		}
		return 1
	}
	fmt.Fprintf(u.out, "update: %s; running live.sh\n", cmp.Or(strings.Join(changed, ", "), "no harness moved"))
	// A red gate runs again on the release before: the checks that fail there too are agentkit's
	// own, never the harness's red, and the release the gate tested goes back in.  The hand-back
	// names only the checks the red is the harness's for.
	red, titles, outcome := "", []string(nil), map[string]string{}
	var landed map[string][2]string
	for _, key := range []string{"live", "fresh"} {
		passed, failed, lines, why := u.gate(key)
		if outcome[key] = why; passed {
			continue
		}
		red = "live"
		if key == "fresh" {
			red = "the fresh-install gate (" + why + ")"
		}
		landed = u.revert(u.plans, after)
		own := strings.Join(failed, ", ")
		if len(failed) == 0 || slices.ContainsFunc(u.plans, func(each plan) bool { return landed[each.name][0] == "cannot revert" }) {
			titles = failed
			if len(failed) == 0 {
				titles = lines
			}
			break
		}
		var reverted []plan
		for _, each := range u.plans {
			if landed[each.name][0] == "reverted" {
				reverted = append(reverted, each)
			}
		}
		if len(reverted) > 0 { // with none, the box it failed on is the release before
			fmt.Fprintf(u.out, "update: %s failed %s; running it on the release before\n", red, own)
			_, again, _, _ := u.gate(key)
			titles = slices.DeleteFunc(slices.Clone(failed), func(label string) bool { return slices.Contains(again, label) })
			if len(titles) > 0 {
				break
			}
			fmt.Fprintf(u.out, "update: %s failed %s on the release before too: agentkit's own checks; "+
				"installing the release it tested again\n", red, own)
		}
		outcome[key] = "failed only agentkit's own checks (" + own + ")"
		if key == "fresh" {
			freshStanding(failed, lines, logPath)
		}
		ok := true
		for _, each := range reverted {
			if each.name == u.snapshotted.name {
				// the restore used the snapshot up: a new one is taken before installing again
				var err error
				if u.snapshot, err = take(each, before[each.name], u.env); err != nil {
					fmt.Fprintf(u.out, "update: %s\n", err)
					ok = false
					break
				}
			}
			ok = u.swap(each, each.upgrade) && ok
		}
		again := u.versions()
		if !ok || !maps.Equal(again, after) {
			red += ", and its release did not install again: " +
				cmp.Or(strings.Join(moved(u.plans, after, again), ", "), "the reinstall failed")
			titles = nil // every check it failed was agentkit's; the red is the reinstall
			landed = u.revert(u.plans, again)
			break
		}
		red = ""
	}
	if red == "" {
		done := "every harness was already current"
		if len(changed) > 0 {
			done = strings.Join(changed, ", ")
		}
		fmt.Fprintf(u.out, "update: %s, live %s, fresh-install gate %s (%s)\n", done, outcome["live"], outcome["fresh"], logPath)
		landed = kept(u.plans, before, after)
		for name, why := range downgraded {
			if after[name] == before[name] {
				landed[name] = [2]string{"kept", why}
			}
		}
		report(u.plans, landed, u.out)
		if u.snapshot != nil {
			u.snapshot.discard()
		}
		gateResult(u.plans, true, "", logPath, nil)
		return 0
	}
	fmt.Fprintf(u.errOut, "update: %s FAILED after %s -- see %s\n", red, cmp.Or(strings.Join(changed, ", "), "no change"), logPath)
	report(u.plans, landed, u.errOut)
	gateResult(u.plans, false, red, logPath, titles)
	return 1
}

// revert puts each of plans that moved from before to now back where it was, as Python's
// update.revert: where every harness landed.  One that will not go back, or has no command
// that could, is named with what it is on and the command to try by hand: from here on
// nothing else will.
func (u *upgrade) revert(plans []plan, now map[string]string) map[string][2]string {
	landed := kept(u.plans, u.before, now)
	for _, each := range plans {
		name, old := each.name, u.before[each.name]
		if u.snapshot != nil && name == u.snapshotted.name {
			// a failed installer can replace bytes and still report the old release label
			fmt.Fprintf(u.out, "update: restoring %s from %s\n", name, u.snapshot.path)
			var err error
			swapping(name, func() bool { err = u.snapshot.restore(); return err == nil })
			landed[name] = [2]string{"reverted", "back on " + old}
			if err != nil {
				landed[name] = [2]string{"cannot revert", pyError(err) + "; snapshot retained at " + u.snapshot.path}
			} else {
				u.snapshot = nil // what it saved is installed again, and an upgrade after takes another
			}
			continue
		}
		if old == "" || now[name] == old {
			continue
		}
		if each.revert == nil {
			landed[name] = [2]string{"cannot revert", fmt.Sprintf("on %s and not back on %s: %s, so no command puts it back",
				cmp.Or(now[name], "?"), old, each.cannot)}
			continue
		}
		fmt.Fprintf(u.out, "update: reverting %s to %s\n", name, old)
		command := make([]string, len(each.revert))
		for i, word := range each.revert {
			command[i] = strings.ReplaceAll(word, "{version}", versionWord.FindString(old))
		}
		ok := u.swap(each, command)
		back, _ := version(each, u.env)
		landed[name] = [2]string{"reverted", "back on " + old}
		if !ok || back != old {
			landed[name] = [2]string{"cannot revert", fmt.Sprintf("on %s and not back on %s; run `%s` by hand",
				cmp.Or(back, "?"), old, commandhelp.ShellJoin(command))}
		}
	}
	return landed
}

// kept is where each harness ended up when nothing had to be put back, as Python's update.kept:
// its state and what to say of it.
func kept(plans []plan, before, after map[string]string) map[string][2]string {
	landed := map[string][2]string{}
	for _, each := range plans {
		old, now := before[each.name], after[each.name]
		switch {
		case old == "":
			landed[each.name] = [2]string{"unchanged", "not installed here"}
		case now == old:
			landed[each.name] = [2]string{"unchanged", "still on " + old}
		case downgrade(old, now):
			landed[each.name] = [2]string{"kept", fmt.Sprintf("installed %s is newer than the channel's %s", releaseOf(old), releaseOf(now))}
		default:
			landed[each.name] = [2]string{"upgraded", old + "->" + cmp.Or(now, "?")}
		}
	}
	return landed
}

// report is one line per harness: what happened to it, and where that leaves it.
func report(plans []plan, landed map[string][2]string, out io.Writer) {
	for _, each := range plans {
		fmt.Fprintf(out, "update: %s: %s, %s\n", each.name, landed[each.name][0], landed[each.name][1])
	}
}

// moved is each harness whose version changed, as `name old->new`.
func moved(plans []plan, before, after map[string]string) []string {
	var changed []string
	for _, each := range plans {
		if old, now := before[each.name], after[each.name]; old != now {
			changed = append(changed, each.name+" "+cmp.Or(old, "?")+"->"+cmp.Or(now, "?"))
		}
	}
	return changed
}

func (u *upgrade) versions() map[string]string {
	found := map[string]string{}
	for _, each := range u.plans {
		// a release that writes what is not UTF-8 reads as none, which no real one does
		found[each.name], _ = version(each, u.env)
	}
	return found
}

// releaseOf is the build an identity names, else its first release, else "", as Python's
// update._release: a label may say `1.4.1` before its build `1.4.1-R4503.1`.
func releaseOf(identity string) string {
	return cmp.Or(build.FindString(identity), release.FindString(identity))
}

// downgrade is whether both identities name a release and the new one is the lower, as Python's
// update._downgrade: a build is compared only with a build, as a label without one says nothing
// of which build of its release is installed.
func downgrade(old, new string) bool {
	was, is := digits.FindAllString(releaseOf(old), -1), digits.FindAllString(releaseOf(new), -1)
	if len(was) == 3 || len(is) == 3 {
		was, is = was[:min(3, len(was))], is[:min(3, len(is))]
	}
	return len(was) > 0 && len(is) > 0 && slices.CompareFunc(is, was, func(a, b string) int {
		a, b = number(a), number(b)
		return cmp.Or(cmp.Compare(len(a), len(b)), strings.Compare(a, b))
	}) < 0
}

// number is a run of digits as Python's int() reads it, in ASCII without its leading zeros:
// Unicode's decimal digits run 0 to 9 in a row, several scripts' back to back.
func number(digits string) string {
	var ascii []byte
	for _, r := range digits {
		zero := r
		for unicode.IsDigit(zero - 1) {
			zero--
		}
		ascii = append(ascii, byte('0'+(r-zero)%10))
	}
	return strings.TrimLeft(string(ascii), "0")
}

// swap runs argv, an install or revert of harness each, as a step marked as a swap.
func (u *upgrade) swap(each plan, argv []string) bool {
	return swapping(each.name, func() bool { return u.step(argv, each.env, stepCap) })
}

// step runs one command of an upgrade into its log, as Python's update.step: its program found
// as a harness's adapter finds it, extra in its environment, its stdin empty, in a session of its
// own killed whole once it outlives limit; whether it exited 0.  One that did not is said with
// the log's last lines.
func (u *upgrade) step(argv, extra []string, limit time.Duration) bool {
	argv = append([]string{cmp.Or(harness.Binary(argv[0]), argv[0])}, argv[1:]...)
	fmt.Fprintf(u.log, "\n$ %s\n", commandhelp.ShellJoin(argv))
	ctx, cancel := context.WithTimeout(context.Background(), limit)
	defer cancel()
	command := exec.CommandContext(ctx, argv[0], argv[1:]...)
	if errors.Is(command.Err, exec.ErrDot) {
		command.Err = nil // Python's subprocess runs what a relative PATH entry finds
	}
	command.Env, command.Stdout, command.Stderr = append(slices.Clip(u.env), extra...), u.log, u.log
	host.Group(command)
	code := "0"
	var exited *exec.ExitError
	switch err := command.Run(); {
	case err != nil && ctx.Err() != nil:
		fmt.Fprintf(u.log, "[timed out after %ds]\n", int(limit.Seconds()))
		code = "timeout"
	case errors.As(err, &exited):
		code = fmt.Sprint(returncode(exited))
	case err != nil:
		fmt.Fprintf(u.log, "[%s]\n", pyError(err))
		code = "could not start"
	}
	fmt.Fprintf(u.log, "[exit %s]\n", code)
	if code == "0" {
		return true
	}
	fmt.Fprintf(u.out, "update: command=%s exit=%s log=%s\n", commandhelp.ShellJoin(argv), code, u.log.Name())
	data, _ := os.ReadFile(u.log.Name())
	lines := config.SplitLines(decoded(data))
	for _, line := range lines[max(0, len(lines)-20):] {
		fmt.Fprintf(u.out, "  %s\n", line)
	}
	return false
}

// decoded is data as Python decodes it with errors="replace": each byte that is not UTF-8 a
// replacement character.
func decoded(data []byte) string {
	return string([]rune(string(data)))
}

// swapping runs do, an install or revert of harness name, marked in state/harness-swaps.json as
// begun and as ended, as Python's update.swapping: how a worker turn that failed meanwhile tells
// the swap from a harness that cannot run.  A mark that cannot be written costs a turn its
// retry, never the upgrade.
func swapping(name string, do func() bool) bool {
	began := now()
	markSwap(name, began, nil)
	defer func() { markSwap(name, began, now()) }()
	return do()
}

func markSwap(name string, began float64, ended any) {
	path := filepath.Join(config.Home(), "state", "harness-swaps.json")
	var swaps [][]any
	if data, err := os.ReadFile(path); err != nil || json.Unmarshal(data, &swaps) != nil {
		swaps = nil
	}
	swaps = slices.DeleteFunc(swaps, func(swap []any) bool { return len(swap) > 1 && swap[0] == name && swap[1] == began })
	data, _ := json.Marshal(append(swaps[max(0, len(swaps)-swapsKept+1):], []any{name, began, ended}))
	put(path, data)
}

// put writes data to path whole, as Python's update._put: a reader sees the old file or the new
// one, never half.  The file it writes first is path with `.tmp` for its suffix.
func put(path string, data []byte) error {
	temporary := strings.TrimSuffix(path, filepath.Ext(path)) + ".tmp"
	if err := os.WriteFile(temporary, data, 0o666); err != nil {
		return err
	}
	return os.Rename(temporary, path)
}

// retain registers the log at path for ak's collection while an upgrade writes it, as Python's
// retention.artifact does, in `<path>.agentkit-ephemeral.json` under its writer's lease; what it
// returns marks it finished.  One it cannot register stays out of collection.
func retain(path string) (finish func()) {
	marker := path + ".agentkit-ephemeral.json"
	record := map[string]any{"version": 1, "kind": "update", "path": path, "created_at": now(),
		"pid": os.Getpid(), "process_identity": nil}
	if born, ok := host.ReadIdentity(os.Getpid()); ok {
		record["process_identity"] = map[string]any{"boot": born.Boot, "ticks": born.Ticks, "started_at": born.StartedAt}
	}
	if !unlinked(path) || create(marker, record) != nil {
		return func() {}
	}
	lease, _ := lock.Try(marker)
	return func() {
		record["finished_at"] = now()
		if create(marker+".part", record) == nil {
			os.Rename(marker+".part", marker)
		}
		lease.Close()
	}
}

// create writes value to a file path names that is not there yet, as JSON, synced.
func create(path string, value any) error {
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o666)
	if err != nil {
		return err
	}
	data, _ := json.Marshal(value)
	_, err = file.Write(data)
	return errors.Join(err, file.Sync(), file.Close())
}

// now is the time as Python's time.time() says it.
func now() float64 {
	return float64(time.Now().UnixNano()) / 1e9
}
