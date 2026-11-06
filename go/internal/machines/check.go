package machines

import (
	"context"
	_ "embed"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

const (
	timeout = 10      // the seconds a machine that does not answer holds the tick, all of them
	kept    = 3 * day // the checks "always on" is judged on; older ones go
)

// probe is tools/machine.sh, carried so a copied program needs no checkout beside it.
//
//go:embed machine.sh
var probe string

// readings is what the probe says, in the order Python's READINGS keeps it, each read as its
// type; an answer missing one is no answer.
var readings = []struct {
	name string
	read func(string) (any, bool)
}{{"system", text}, {"processor", text}, {"cores", whole}, {"memory_mb", whole},
	{"free_mb", whole}, {"load", fraction}, {"disk_free_mb", whole}, {"battery", whole},
	{"power", whole}}

// Check is the tick's: it asks each machine once, side by side, and replaces the record with what
// each answered, as Python's machines.check writes it.
func Check() error {
	now := float64(time.Now().UnixNano()) / 1e9
	names, found := known()
	answers := ask(names)
	record := run.NewObject()
	for i, name := range names {
		machine := found.Dict(name)
		if machine == nil {
			machine = run.NewObject()
		}
		checks := []any{}
		for _, check := range machine.List("checks") {
			if when, ok := run.Num(at(check, 0)); ok && when > now-kept {
				checks = append(checks, check)
			}
		}
		answered := said(answers[i])
		entry := run.NewObject()
		entry.Set("checks", append(checks, []any{run.Float(now), answered != nil}))
		if answered != nil {
			answered.Set("at", now)
			entry.Set("said", answered)
		} else {
			entry.Set("said", machine.Get("said"))
		}
		record.Set(name, entry)
	}
	temp := strings.TrimSuffix(path(), ".json") + ".tmp"
	if err := os.WriteFile(temp, []byte(run.Line(record)+"\n"), 0o666); err != nil {
		return err
	}
	return os.Rename(temp, path())
}

// Owns is whether an entry of ak's state folder is the record or the file it is written through.
func Owns(name string) bool { return name == "machines.json" || name == "machines.tmp" }

// ask is what each machine printed of the probe, all asked at once, here or over ssh: "" where it
// failed or had not answered whole by the timeout, which ends everything it started.
func ask(names []string) []string {
	ctx, cancel := context.WithTimeout(context.Background(), timeout*time.Second)
	defer cancel()
	answers := make([]string, len(names))
	var asking sync.WaitGroup
	for i, name := range names {
		command := []string{"bash", "-c", probe}
		if name != here {
			command = []string{"ssh", "-o", "BatchMode=yes", "-o", fmt.Sprintf("ConnectTimeout=%d", timeout),
				"--", name, commandhelp.ShellJoin(command)}
		}
		cmd := exec.CommandContext(ctx, command[0], command[1:]...)
		stop := host.Group(cmd)
		var out strings.Builder
		cmd.Stdout = &out
		if cmd.Start() != nil {
			continue
		}
		waited := make(chan error, 1)
		go func() { waited <- cmd.Wait() }()
		asking.Add(1)
		go func() {
			defer asking.Done()
			select {
			case err := <-waited:
				if err == nil {
					answers[i] = out.String()
				}
			// exec stops watching the deadline once the first process is gone, and a child it
			// left holding the output would hold Wait for as long as it lives
			case <-ctx.Done():
				stop()
			}
		}()
	}
	asking.Wait()
	return answers
}

// said is what the probe answered, by readings, or nil: it did not answer or said too little.
func said(answer string) *run.Object {
	lines := map[string]string{}
	for _, line := range config.SplitLines(gitcall.Decoded(answer)) {
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

func text(value string) (any, bool) { return value, true }

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
