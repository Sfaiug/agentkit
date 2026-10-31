// Package worker runs one turn of a model's harness, as Python's agentkit/worker.py does.  It
// hides the turn's out directory with its hand-in file and its prompt, the role's opening and then
// the task; the adapter's `auth` verb, asked before the turn and again after a quick turn that
// streamed nothing; the adapter's `run` in the worker box with its environment; and the
// conversation the turn leaves.
package worker

import (
	"bytes"
	"cmp"
	"context"
	"crypto/rand"
	"errors"
	"fmt"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/box"
	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/harness"
	"agentkit/internal/host"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// ErrPython leaves a turn to Python ak: where ak's adapter scripts live, on a home naming no
// $AGENTKIT_ADAPTER_DIR, and a box on any system but Linux, are not yet Go's.
var ErrPython = errors.New("left to Python")

const (
	authCap   = 20 * time.Second // the `auth` verb reads a file; one still silent after this is not answering
	authGrace = 60 * time.Second // a turn over this fast that streamed nothing never reached the model
)

// Turn runs one turn of the model name in role on the task's text, from the resolved workspace
// into out, resuming session where one is given: its exit status as the box reports it, and the
// conversation it leaves.  A harness whose login has expired is an error saying so.
func Turn(name, role, body, workspace, out, session string) (int, string, error) {
	model, err := config.ModelNamed(name)
	if err != nil {
		return 0, "", err
	}
	adapter, err := config.Adapter(model.Harness)
	if !box.Supported || errors.Is(err, config.ErrNoAdapterDir) || config.EnsureDirs() != nil {
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
	probe := append(seated, marker, "AGENTKIT_PROVIDER="+model.Provider)
	if err := expired(model.Harness, adapter, probe); err != nil {
		return 0, "", err
	}
	if err := os.MkdirAll(out, 0o777); err != nil {
		return 0, "", err
	}
	handIn, err := handin.Start(out, workspace, role)
	if err != nil {
		return 0, "", err
	}
	prompt := filepath.Join(out, "prompt.md")
	if err := os.WriteFile(prompt, []byte(Prompt(role, workspace)+"\n\n"+body), 0o666); err != nil {
		return 0, "", err
	}
	argv := []string{adapter, "run", model.ID, model.TurnEffort(strings.HasPrefix(role, "reviewer")), workspace, prompt, out}
	if session != "" {
		argv = append(argv, session)
	}
	env := map[string]string{}
	for _, pair := range append(seatless, marker, handIn) {
		key, value, _ := strings.Cut(pair, "=")
		env[key] = value
	}
	maps.Copy(env, harness.TurnEnv(model.Harness))
	// The adapter's own stderr, a line it prints before it hands the harness stderr.log, is kept
	// apart while the harness writes that log, and goes at its end once the turn is over.
	own := filepath.Join(out, "adapter-stderr.log")
	said, err := os.Create(own)
	if err != nil {
		return 0, "", err
	}
	began := time.Now()
	code, err := box.Run(argv, env, workspace, out, state, logins, config.Unswitched(model.Harness, env), said)
	said.Close()
	if data, err := os.ReadFile(own); err == nil && os.Remove(own) == nil && len(data) > 0 {
		if log, err := os.OpenFile(filepath.Join(out, "stderr.log"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o666); err == nil {
			log.Write(data)
			log.Close()
		}
	}
	if err != nil {
		return 0, "", err
	}
	left := conversation(out)
	// Nothing streamed and over at once: ask why before taking a silence for the turn's result.
	events, _ := os.ReadFile(filepath.Join(out, "events.jsonl"))
	if strings.TrimFunc(string(events), config.Space) == "" && time.Since(began) < authGrace {
		if err := expired(model.Harness, adapter, probe); err != nil {
			return code, left, err
		}
	}
	return code, left, nil
}

// expired says the harness's login expired where the adapter's `auth` verb says no.  Any other
// answer is no answer, which lets a turn run.
func expired(harness, adapter string, env []string) error {
	if answered, yes, line := Login(adapter, env); answered && !yes {
		return fmt.Errorf("%s login expired: %s", harness, line)
	}
	return nil
}

// Login is what the adapter's `auth` verb says of the login env names, as Python's
// worker.auth_ok reads it: answered where it said one line exiting 0 or 1, yes for 0, and that
// line.
func Login(adapter string, env []string) (answered, yes bool, line string) {
	ctx, cancel := context.WithTimeout(context.Background(), authCap)
	defer cancel()
	var stdout, stderr bytes.Buffer
	cmd := exec.CommandContext(ctx, adapter, "auth")
	// A stdin closed at once: asking opens no file of its own on a machine watching for that.
	cmd.Env, cmd.Stdin, cmd.Stdout, cmd.Stderr, cmd.WaitDelay = env, strings.NewReader(""), &stdout, &stderr, time.Second
	if err := cmd.Run(); err != nil && !errors.As(err, new(*exec.ExitError)) {
		return false, false, ""
	}
	var lines []string
	for _, line := range config.SplitLines(stdout.String() + stderr.String()) {
		if line = strings.TrimFunc(line, config.Space); line != "" {
			lines = append(lines, line)
		}
	}
	if code := cmd.ProcessState.ExitCode(); len(lines) == 1 && (code == 0 || code == 1) {
		return true, code == 0, lines[0]
	}
	return false, false, ""
}

// conversation is the one the turn leaves: the id its adapter wrote, else the last its events
// streamed, for a turn that ended before its adapter wrote one, in each shape Python's
// recovered_session reads.
func conversation(out string) string {
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
