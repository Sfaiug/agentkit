// Package helper is Go's client of the suite helper, Python's agentkit/helper.py: a machine ak may
// use, named under `[machines]` in config.toml or by `suite_helper`, runs a sharded suite's pieces
// beside this one, each in a VM or container of its own built from the repository's recipe.  It
// hides ssh, the remote script and the parcel: each verb is one line over ssh, `bash -c <script>
// mac.sh VERB ...`, the script tools/helper's linux.sh and mac.sh as this program carries them, and
// a suite reaches the machine as one tar on `prepare`'s stdin: the recipe and the files it copies,
// the piece's script, the heads under test and the history the machine lacks, and a model turn's
// own files where it carries one.  A machine ak may rent stays Python's (ErrPython).
package helper

import (
	"cmp"
	"context"
	"crypto/rand"
	"embed"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"maps"
	"math"
	"os"
	"os/exec"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/harness"
)

// The machine's exits, as mac.sh and piece.sh give them: ssh's own failure, history the parcel
// left out, a VM out of memory, off its charger, no room, a container that could not run.
const (
	lost    = 255
	lacks   = 3
	short   = 254
	battery = 251
	full    = 252
	broken  = 253
)

const (
	// vmCPUs is the least a piece's VM gets: a one-CPU VM's kernel hands a terminal's bytes over
	// late, and the suite's terminal tests read them at once.
	vmCPUs = 2
	// maxArg is Linux's MAX_ARG_STRLEN, the most one argument holds: ssh is given a piece's whole
	// line as one, and the machine's shell gets it as one, the piece's command in it.
	maxArg = 128 * 1024
	// wide is a number no probe has told yet, at its widest, as a piece's line may come to hold it.
	wide   = "18446744073709551615"
	asleep = "did not answer (asleep or away)"
)

// carried is the remote script, every kind of machine sent every kind's functions to pick its own
// by `uname`, and the piece's and the turn's scripts the parcel holds.  Carried, so the verbs of one
// suite all send the same script, and a copied program needs no checkout beside it.
//
//go:embed linux.sh mac.sh piece.sh turn.sh
var carried embed.FS

// ErrPython is helper work Go leaves to Python: a machine ak may rent, or a piece that did not
// pass there, whose tests Python runs again here or which it sends on to the next machine.
var ErrPython = errors.New("the suite helper's work is not Go's yet")

// May is whether a helper may take this host's work: a machine config.toml names, or one ak may
// rent.
func May() bool {
	return len(config.MachineNames()) > 0 || config.MayRent()
}

// An Away is a suite a helper took: Alias the machine, Count the VMs it runs there at once, CPUs
// and MemoryMB each VM's, Most the VMs it fits empty.  Its key names its tree and VMs there.
type Away struct {
	Alias                       string
	Count, CPUs, MemoryMB, Most int
	key, repo, image, branch    string
	base, programs, command     string
}

// Start sends the suite to the machine with the most room that takes it, and on to the next where
// one turns it away, Python's start: the Away there, or nil and why its pieces run here.  command
// is what each piece runs there, cpus and memoryMB one piece's cost; what it has to say goes to
// say.  A model turn's, with its own files for the parcel (turnFiles), is one piece that goes to
// the machine with the least room that takes turns, holding its cpus there until it starts, not
// half the machine.  Work a machine ak may rent could take is ErrPython's, before anything is sent.
func Start(cwd string, cpus, memoryMB float64, command string, turn map[string]file, say func(string)) (*Away, string, error) {
	return start(cwd, cpus, memoryMB, pinned(command), turn, false, say)
}

// start is Start of the line command each piece runs there, as pinned; with one, a probe's, it
// holds only the CPUs its one piece gets (Probe).
func start(cwd string, cpus, memoryMB float64, command string, turn map[string]file, one bool, say func(string)) (*Away, string, error) {
	work, first, holds := "tests", -1, []string(nil)
	if turn != nil {
		work, first, holds = "turns", 1, []string{strconv.FormatFloat(cpus, 'f', -1, 64)}
	}
	aliases := takers(work)
	if len(aliases) == 0 && !config.MayRent() {
		return nil, "no suite helper set up", nil
	}
	away := &Away{key: token(), repo: gitcall.RepositoryID(cwd), command: command, programs: programs()}
	image, files, err := recipeOf(cwd, away.repo)
	if err != nil {
		say(fmt.Sprintf("WARN the suite helper cannot build suite_image: %v; the suite runs here", err))
		return nil, "the suite helper cannot build suite_image: " + err.Error(), nil
	}
	if image == "" {
		return nil, "no recipe for the suite helper", nil
	}
	away.image = image
	maps.Copy(files, turn)
	g := gitcall.Git{Repo: cwd}
	if code, branch, err := g.Out("symbolic-ref", "-q", "--short", "HEAD"); err == nil && code == 0 {
		away.branch = branch
	}
	if code, base, err := g.Out("rev-parse", "--abbrev-ref", "origin/HEAD"); err == nil && code == 0 {
		away.base = strings.TrimPrefix(base, "origin/")
	}
	if size := len(Line("run", away.args(wide+"/"+wide, wide, wide)...)); size >= maxArg {
		return nil, fmt.Sprintf("a piece's line to the suite helper would take %d bytes, more than one argument holds (%d, Linux's MAX_ARG_STRLEN)", size, maxArg), nil
	}
	if config.MayRent() {
		return nil, "", fmt.Errorf("%w: ak may rent a machine for the suite", ErrPython)
	}
	least := least(away.repo)
	fits, why := make([]fit, len(aliases)), make([]string, len(aliases))
	var order []int
	for i, alias := range aliases {
		if fits[i], why[i] = room(alias, cpus, memoryMB, least, turn != nil); fits[i].count > 0 {
			order = append(order, i)
		}
	}
	// A suite splits into as many pieces as fit, so most room first; a turn takes one place and is
	// as fast on a busy machine, so least first.  On to the next where one refuses: its room can go
	// between the probe and `prepare`.
	slices.SortStableFunc(order, func(a, b int) int { return cmp.Compare(first*fits[a].count, first*fits[b].count) })
	for _, i := range order {
		there := *away
		there.Alias, there.Count, there.CPUs, there.MemoryMB, there.Most = aliases[i], fits[i].count, fits[i].cpus, fits[i].mb, fits[i].most
		if one {
			holds = []string{strconv.Itoa(there.CPUs)}
		}
		sent := there.send(cwd, files, holds)
		if sent == 0 {
			say(fmt.Sprintf("suite on %s: %d pieces, %d CPUs and %d MiB each", there.Alias, there.Count, there.CPUs, there.MemoryMB))
			return &there, "", nil
		}
		there.Finish()
		why[i] = Failure(sent) // its room is gone
	}
	for i, alias := range aliases {
		why[i] = "helper " + alias + " " + why[i]
	}
	return nil, strings.Join(why, " · "), nil
}

// Piece runs the suite's piece of shard there, its output into out, until it ends or ctx does: its
// exit there, `lost` where ssh could not start.
func (a *Away) Piece(ctx context.Context, shard string, out io.Writer) int {
	cmd := remote(ctx, a.Alias, "run", a.args(shard, strconv.Itoa(a.CPUs), strconv.Itoa(a.MemoryMB))...)
	cmd.Stdout, cmd.Stderr = out, out
	cmd.Run()
	if cmd.ProcessState == nil {
		return lost
	}
	return cmd.ProcessState.ExitCode()
}

// Named are the tests the ended piece of shard named there as failed (`AK_FAILED`), or with named
// "flaky" as failed, then passed (`AK_FLAKY`), from the file piece.sh gives it, never from what it
// printed; none where the machine does not answer.
func (a *Away) Named(shard, named string) []string {
	code, said := ask(a.Alias, 30*time.Second, nil, "failed", a.key, a.vm(shard), named)
	var tests []string
	for _, test := range strings.Split(said, "\n") {
		if test = strings.TrimSpace(test); code == 0 && test != "" && !slices.Contains(tests, test) {
			tests = append(tests, test)
		}
	}
	return tests
}

// Gone is whether a piece's exit says the machine lost it or had no room for it, never its own
// red: Python's GONE and FULL, which it sends on to the next machine with room.
func Gone(code int) bool {
	return slices.Contains([]int{lost, short, battery, broken, full}, code)
}

// Finish takes the suite's tree off the machine; one that does not answer clears it a day later.
func (a *Away) Finish() {
	ask(a.Alias, 30*time.Second, nil, "finish", a.key)
}

// args are a piece's words after `run`: KEY IMAGE VM CPUS MEMORY_MB REPO, then piece.sh's SHARD
// BRANCH DEFAULT PROGRAMS COMMAND.
func (a *Away) args(shard, cpus, memoryMB string) []string {
	return []string{a.key, a.image, a.vm(shard), cpus, memoryMB, a.repo, shard, a.branch, a.base, a.programs, a.command}
}

func (a *Away) vm(shard string) string {
	return "ak-" + a.key + "-" + strings.ReplaceAll(shard, "/", "-")
}

// send prepares the suite there, holding the CPUs holds names where it names any: a parcel of the
// history the machine lacks, sent once more whole where its copy went since it answered; the
// machine's exit, `lost` where it never answered.
func (a *Away) send(cwd string, files map[string]file, holds []string) int {
	code, said := ask(a.Alias, 30*time.Second, nil, "known", a.repo)
	if code != 0 {
		return lost
	}
	known := strings.Fields(said)
	for {
		sent := a.prepare(cwd, known, files, holds)
		if sent != lacks || len(known) == 0 {
			return sent
		}
		known = nil
	}
}

func (a *Away) prepare(cwd string, known []string, files map[string]file, holds []string) int {
	parcel, err := os.CreateTemp("", "ak-parcel-*")
	if err != nil {
		return lost
	}
	defer os.Remove(parcel.Name())
	defer parcel.Close()
	if err := a.pack(cwd, known, files, parcel); err != nil {
		return lost
	}
	if _, err := parcel.Seek(0, io.SeekStart); err != nil {
		return lost
	}
	// a new recipe's build fetches packages, a first suite sends the whole history
	code, _ := ask(a.Alias, 30*time.Minute, parcel, "prepare", append([]string{a.key, a.image, a.repo}, holds...)...)
	return code
}

// A fit is a machine's room for a suite: the VMs it starts now, the CPUs and MiB each gets, and the
// most it fits empty.
type fit struct{ count, cpus, mb, most int }

// room is the machine's fit for pieces of that cost, or why it has none: its CPUs less its load,
// split equally among VMs of two CPUs or more, as VMs time-share them, and the MiB ak's VMs may
// still be given there, beside other suites' VMs.  For turns, only where its probe reads `turns
// 1`: a Mac runs suites alone.
func room(alias string, cpus, memoryMB float64, least int, turns bool) (fit, string) {
	code, said := ask(alias, 30*time.Second, nil, "probe")
	if code != 0 {
		return fit{}, Failure(code)
	}
	readings := map[string]float64{}
	for _, line := range config.SplitLines(said) {
		if !strings.Contains(line, " ") {
			continue
		}
		words := strings.Fields(line)
		if len(words) != 2 {
			return fit{}, asleep
		}
		value, err := strconv.ParseFloat(words[1], 64)
		if err != nil {
			return fit{}, asleep
		}
		readings[words[0]] = value
	}
	if turns && readings["turns"] != 1 {
		return fit{}, "takes no model turns"
	}
	machine, hasCPUs := readings["cpus"]
	load, hasLoad := readings["load"]
	roomMB, hasRoom := readings["room_mb"]
	spare, each, mb := machine-load, max(cpus, vmCPUs), int(max(2*memoryMB, float64(least)))
	byCPU, byMemory := math.Floor(spare/each), math.Floor(roomMB/float64(mb))
	if !hasCPUs || !hasLoad || !hasRoom || math.IsInf(byCPU+byMemory, 0) || math.IsNaN(byCPU+byMemory) {
		return fit{}, asleep
	}
	count := int(min(byCPU, byMemory))
	if count < 1 {
		return fit{}, fmt.Sprintf("has no room (%.6g spare CPUs and %.6g MiB)", spare, roomMB)
	}
	return fit{count, int(math.Floor(spare / float64(count))), mb, int(math.Floor(machine / each))}, ""
}

// Failure is the machine's reason, decided from its exit, never its diagnostic output.
func Failure(code int) string {
	switch code {
	case lost:
		return asleep
	case battery:
		return "is on battery"
	case full:
		return "has no room"
	case broken:
		return "could not prepare or run the container"
	case short:
		return "ran out of memory"
	}
	return fmt.Sprintf("failed (exit %d)", code)
}

// ask runs one verb there, stdin given it where one is: its exit and what it printed, `lost` where
// it never answered within limit or ssh could not start.
func ask(alias string, limit time.Duration, stdin *os.File, verb string, args ...string) (int, string) {
	ctx, cancel := context.WithTimeout(context.Background(), limit)
	defer cancel()
	cmd := remote(ctx, alias, verb, args...)
	if stdin != nil {
		cmd.Stdin = stdin
	}
	said, _ := cmd.Output()
	if ctx.Err() != nil || cmd.ProcessState == nil {
		return lost, ""
	}
	return cmd.ProcessState.ExitCode(), string(said)
}

// remote is ssh running one verb there, never asking for a password, ended with ctx.
func remote(ctx context.Context, alias, verb string, args ...string) *exec.Cmd {
	return exec.CommandContext(ctx, "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", alias, Line(verb, args...))
}

// Line is the shell line running one verb on a machine: the remote script, every kind's functions,
// handed to bash as mac.sh, which picks its own by `uname`.
func Line(verb string, args ...string) string {
	linux, _ := carried.ReadFile("linux.sh")
	mac, _ := carried.ReadFile("mac.sh")
	return commandhelp.ShellJoin(append([]string{"bash", "-c", string(linux) + string(mac), "mac.sh", verb}, args...))
}

// pinned is command as a piece runs it there, Python's gate.pinned with no file times or changed
// files, as Go hands its pieces here neither: in a clone the lander's look at its checkout never
// sees, so it checks that clone itself, and fails where it changed.
func pinned(command string) string {
	return "head=$(git rev-parse HEAD) && bash -c " + commandhelp.ShellJoin([]string{command}) + " || exit\n" +
		`[ "$(git rev-parse HEAD)" = "$head" ] && git diff --quiet HEAD ||` +
		` { echo "the piece changed the checkout it tests" >&2; exit 1; }`
}

// programs are the harness programs this host has, which piece.sh stands in for there.
func programs() string {
	names, _ := config.Programs()
	var found []string
	for _, name := range names {
		if harness.Binary(name) != "" && !slices.Contains(found, name) {
			found = append(found, name)
		}
	}
	slices.Sort(found)
	return strings.Join(found, " ")
}

func token() string {
	key := make([]byte, 6)
	rand.Read(key)
	return hex.EncodeToString(key)
}
