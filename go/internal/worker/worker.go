// Package worker runs one turn of a model's harness, as Python's agentkit/worker.py does.  It
// hides the turn's out directory with its hand-in file and its prompt, the role's opening and then
// the task; the adapter's `auth` verb, asked before the turn and again after a quick turn that
// streamed nothing; the harness's own logout words in the turn's log; the adapter's `run` on a
// machine that takes turns, else in the worker box, with its environment, stopped on ^C or on those
// words; and the conversation the turn leaves.
package worker

import (
	"cmp"
	"context"
	"crypto/rand"
	"errors"
	"fmt"
	"io"
	"maps"
	"os"
	"os/signal"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/box"
	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/harness"
	"agentkit/internal/host"
	"agentkit/internal/logins"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// ErrPython leaves a turn to Python ak: where ak's adapter scripts live, on a home naming no
// $AGENTKIT_ADAPTER_DIR, a box on any system but Linux, and a turn on a provider listing accounts
// on none of them, whose login Python's turn picks (usage.account), are not yet Go's.
var ErrPython = errors.New("left to Python")

// ErrInterrupted is a turn ^C or its Given's context ended, once the box it ran in has.
var ErrInterrupted = errors.New("interrupted")

const authGrace = 60 * time.Second // a turn over this fast that streamed nothing never reached the model

// Turn runs one turn of the model name in role on the task's text, from the resolved workspace
// into out, resuming session where one is given: its exit status as the box reports it, and the
// conversation it leaves.  A harness whose login has expired is a LoginExpired.  Each process the
// turn's end stopped is a line in errOut.
func Turn(name, role, body, workspace, out, session string, given Given, errOut io.Writer) (int, string, error) {
	model, err := config.ModelNamed(name)
	if err != nil {
		return 0, "", err
	}
	if given.Efforts != nil {
		model.Efforts = given.Efforts
	}
	adapter, err := Adapter(model, given.Account)
	if errors.Is(err, ErrPython) || config.EnsureDirs() != nil {
		return 0, "", ErrPython
	} else if err != nil {
		return 0, "", err
	}
	seated, err := config.ChildEnv()
	if err != nil {
		return 0, "", err
	}
	seatless, err := config.SeatlessEnv()
	if err != nil {
		return 0, "", err
	}
	state, err := config.Words(model.Harness, "worker", "state")
	if err != nil {
		return 0, "", err
	}
	logins, _ := config.Words(model.Harness, "worker", "logins")
	// A turn ends apart from the suite and the loop's helpers beside it, even on a plain host.
	var id [16]byte
	rand.Read(id[:])
	marker := fmt.Sprintf("%s=%s/turn-%x", host.Marker, cmp.Or(os.Getenv(host.Marker), filepath.Join(config.Home(), "runs", "worker")), id)
	named := []string{marker}
	if given.Account != "" {
		named = append(named, config.AccountEnv(given.Account))
	}
	probe := slices.Concat(seated, named, []string{"AGENTKIT_PROVIDER=" + model.Provider})
	if why := refused(adapter, probe); why != "" {
		return 0, "", &LoginExpired{model.Harness, why}
	}
	if err := os.MkdirAll(out, 0o777); err != nil {
		return 0, "", err
	}
	handIn, err := handin.Start(out, workspace, role, given.Findings, given.Previous, given.Checks)
	if err != nil {
		return 0, "", err
	}
	prompt := filepath.Join(out, "prompt.md")
	if err := os.WriteFile(prompt, []byte(opening(role, workspace, given)+"\n\n"+body), 0o666); err != nil {
		return 0, "", err
	}
	argv := []string{adapter, "run", model.ID, model.TurnEffort(strings.HasPrefix(role, "reviewer")), workspace, prompt, out}
	if session != "" {
		argv = append(argv, session)
	}
	env := map[string]string{}
	for _, pair := range slices.Concat(seatless, named, []string{handIn}, given.Env) {
		key, value, _ := strings.Cut(pair, "=")
		env[key] = value
	}
	maps.Copy(env, harness.TurnEnv(model.Harness))
	if err := receipts(out, model.Harness, env); err != nil {
		return 0, "", err
	}
	// The adapter's own stderr, a line it prints before it hands the harness stderr.log, is kept
	// apart while the harness writes that log, and goes at its end once the turn is over.
	own := filepath.Join(out, "adapter-stderr.log")
	said, err := os.Create(own)
	if err != nil {
		return 0, "", err
	}
	began := time.Now()
	away := elsewhere(model, argv, workspace, out, env, session)
	words := loggedOut(model.Harness, out)
	interrupt, restore := signal.NotifyContext(cmp.Or(given.Context, context.Background()), os.Interrupt)
	heartbeats, _ := config.Words(model.Harness, "worker", "heartbeats")
	// launch runs one try at the turn under a watch of its own, as Python's launch does: whether
	// the watch stopped it.  A turn a full machine refused gets a whole silence limit here.
	launch := func(try func(ctx context.Context)) bool {
		ctx, unwatch := words.watch(interrupt)
		ctx, watched := host.Watch{Silence: given.Silence, Heard: Heard(filepath.Join(out, "events.jsonl"), heartbeats), Declared: host.Declared(env[host.Marker])}.Stop(ctx)
		markLaunched()
		try(ctx)
		unwatch()
		return watched() != ""
	}
	code, left, there, stopped := 0, map[int]string(nil), false, false
	if away != nil {
		stopped = launch(func(ctx context.Context) { there = away.Run(ctx) })
		// its results come home and the machine lets it go once the watch is over: neither is the
		// turn's silence
		code, session = away.Home(Conversation)
	}
	if !there {
		stopped = launch(func(ctx context.Context) {
			code, left, err = box.Run(ctx, argv, env, workspace, out, state, logins, config.Unswitched(model.Harness, env, workspace), said)
		})
	}
	interrupted := interrupt.Err() != nil
	restore()
	said.Close()
	harness.RecordTurn(model.Harness, out, filepath.Join(config.Home(), "state"), env["AGENTKIT_ACCOUNT"])
	if data, err := os.ReadFile(own); err == nil && os.Remove(own) == nil && len(data) > 0 {
		if log, err := os.OpenFile(filepath.Join(out, "stderr.log"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o666); err == nil {
			log.Write(data)
			log.Close()
		}
	}
	for _, pid := range slices.Sorted(maps.Keys(left)) {
		fmt.Fprintf(errOut, "%s %s left process %d: %s; stopping it\n", role, name, pid, left[pid])
	}
	if err != nil {
		return 0, "", err
	}
	if !there { // a machine's turn says which conversation it leaves
		session = Conversation(out)
	}
	if interrupted {
		return code, session, ErrInterrupted
	}
	if stopped {
		return code, session, ErrSilent
	}
	why := words.seen()
	// Nothing streamed and over at once: ask why before taking a silence for the turn's result.
	events, _ := os.ReadFile(filepath.Join(out, "events.jsonl"))
	if why == "" && strings.TrimFunc(string(events), config.Space) == "" && time.Since(began) < authGrace {
		why = refused(adapter, probe)
	}
	if why != "" {
		return code, session, &LoginExpired{model.Harness, why}
	}
	return code, session, nil
}

// refused is the line the adapter's `auth` verb says no with, else "": any other answer is no
// answer, which lets a turn run.
func refused(adapter string, env []string) string {
	if answered, yes, line := logins.Auth(adapter, env); answered && !yes {
		return line
	}
	return ""
}

// Conversation is the one the turn in out leaves: the id its adapter wrote, else the last its events
// streamed, for a turn that ended before its adapter wrote one, in each shape Python's
// recovered_session reads.
func Conversation(out string) string {
	if data, err := os.ReadFile(filepath.Join(out, "session_id")); err == nil {
		if id := strings.TrimFunc(string(data), config.Space); id != "" {
			return id
		}
	}
	data, _ := os.ReadFile(filepath.Join(out, "events.jsonl"))
	found := ""
	for _, line := range strings.Split(task.Text(data), "\n") {
		decoded, _ := run.Decode([]byte(line))
		event, ok := decoded.(*run.Object)
		if !ok {
			continue
		}
		var id any
		for _, key := range []string{"session_id", "sessionID", "thread_id", "conversation_id"} {
			if event.Truthy(key) {
				id = event.Get(key)
				break
			}
		}
		if stream := event.Dict("stream"); id == nil && stream != nil {
			id = stream.Get("id")
		}
		if text, ok := id.(string); ok && strings.TrimFunc(text, config.Space) != "" {
			found = strings.TrimFunc(text, config.Space)
		}
	}
	return found
}
