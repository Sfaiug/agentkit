package machines

import (
	"context"
	_ "embed"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

const kept = 3 * day // the checks "always on" is judged on; older ones go

// probe is tools/machine.sh, carried so a copied program needs no checkout beside it.
//
//go:embed machine.sh
var probe string

// readings is what the probe says, in the order Python's READINGS keeps it, each read as its
// type; an answer missing one is no answer.
var readings = []struct {
	name string
	read func(string) (any, bool)
}{{"system", asIs}, {"processor", asIs}, {"cores", whole}, {"memory_mb", whole},
	{"free_mb", whole}, {"load", fraction}, {"disk_free_mb", whole}, {"battery", whole},
	{"power", whole}}

// Check is the tick's: it asks each machine once, side by side, and records what each answered,
// as Python's machines.check writes it.  The record keeps the last three days' checks of each
// machine, of one it did not ask too: one Add asked meanwhile.
func Check() error {
	now := float64(time.Now().UnixNano()) / 1e9
	names, _ := known()
	answers := answers(context.Background(), names)
	return write(context.Background(), func(record *run.Object) {
		for i, name := range names {
			was := record.Dict(name)
			if was == nil {
				was = run.NewObject()
			}
			answered := said(answers[i].Out)
			entry := run.NewObject()
			entry.Set("checks", append(was.List("checks"), []any{run.Float(now), answered != nil}))
			if answered != nil {
				answered.Set("at", now)
				entry.Set("said", answered)
			} else {
				entry.Set("said", was.Get("said"))
			}
			record.Set(name, entry)
		}
		for _, name := range record.Keys() {
			var checks []any
			if was := record.Dict(name); was != nil {
				for _, check := range was.List("checks") {
					if when, ok := run.Num(at(check, 0)); ok && when > now-kept {
						checks = append(checks, check)
					}
				}
				was.Set("checks", checks)
			}
			if len(checks) == 0 {
				record.Delete(name)
			}
		}
	})
}

// write changes the record under Python's lock of it: the tick and Add each read it, change it
// and write it whole, through the one temporary file, so each keeps what the other wrote.  The
// lock is waited on until ctx ends, nothing written then.
func write(ctx context.Context, change func(record *run.Object)) error {
	held, err := lock.Wait(ctx, filepath.Join(filepath.Dir(path()), ".machines.lock"))
	if err != nil {
		return err
	}
	defer held.Close()
	record := recorded()
	change(record)
	temp := strings.TrimSuffix(path(), ".json") + ".tmp"
	if err := os.WriteFile(temp, []byte(run.Line(record)+"\n"), 0o666); err != nil {
		return err
	}
	return os.Rename(temp, path())
}

// answers is each machine's Answer to the probe, all asked at once, here or over ak's ssh given
// options, until ctx ends.
func answers(ctx context.Context, names []string, options ...string) []host.Answer {
	commands := make([][]string, len(names))
	for i, name := range names {
		commands[i] = []string{"bash", "-c", probe}
		if name != Here {
			commands[i] = host.SSH(name, commandhelp.ShellJoin(commands[i]), slices.Concat(options, route(ctx, name))...)
		}
	}
	return host.Ask(ctx, commands)
}

// route is how ak's ssh reaches name (Python's machines.ssh and _keys): by ssh's own config, with
// ak's key, once made, offered after the keys that config gives it (`ssh -G`, bounded, a `Match
// exec` with it), so a machine set up by hand is offered first what it was.  Naming any ends the
// defaults ssh offers while none is, so they are named too.
func route(ctx context.Context, name string) []string {
	if _, err := os.Stat(key()); err != nil {
		return nil
	}
	var options []string
	shown := host.Ask(ctx, [][]string{{"ssh", "-G", "--", name}})[0].Out
	for _, line := range config.SplitLines(text(shown)) {
		if setting, path, _ := strings.Cut(line, " "); setting == "identityfile" {
			options = append(options, "-o", `IdentityFile="`+path+`"`)
		}
	}
	return append(options, "-o", `IdentityFile="`+key()+`"`)
}

// said is what the probe answered, by readings, or nil: it did not answer or said too little.
func said(answer *string) *run.Object {
	lines := map[string]string{}
	for _, line := range config.SplitLines(text(answer)) {
		name, value, _ := strings.Cut(line, " ")
		lines[name] = value
	}
	said := run.NewObject()
	for _, reading := range readings {
		found, ok := lines[reading.name]
		if !ok {
			return nil
		}
		value, ok := reading.read(found)
		if !ok {
			return nil
		}
		said.Set(reading.name, value)
	}
	return said
}

// text is what a command printed, as Python decodes it: "" where it did not answer.
func text(said *string) string {
	if said == nil {
		return ""
	}
	return gitcall.Decoded(*said)
}

func asIs(value string) (any, bool) { return value, true }

// whole is the number Python's int() reads.
func whole(value string) (any, bool) {
	number := config.Int(strings.TrimFunc(value, config.Space))
	if number == nil {
		return nil, false
	}
	return run.Number(number.String()), true
}

// fraction is the number Python's float() reads, as the probe writes one.
func fraction(value string) (any, bool) {
	number, err := strconv.ParseFloat(strings.TrimFunc(value, config.Space), 64)
	return number, err == nil
}
