package harness

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"slices"
	"strings"
	"syscall"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// codexOnServer is tools/codex-seat.py's `serve` and `connected`: the seat's TUI on an app server of
// its own, in a Codex home of the seat's own (`codexSeatHome`), for as long as the TUI runs and the
// seat is not forgotten.  The server takes the line's settings, ak's hooks among them, and the
// seat's permissions; the TUI reaches it through a socket that connection.json names, for a Stop
// to ask what work is in flight (`codexInFlight`).  What Python's guard does beside it, naming
// the seat's remote-control environment and keeping its enrollments, and removing a home forgotten
// while it ran, is Python's still: its next forget finds that home and does it.
func codexOnServer(cmd, prompt []string, receipt string, env []string, errOut io.Writer, terminal func(words, env []string) int) int {
	failed := func(err error) int {
		fmt.Fprintf(errOut, "codex seat: %v\n", err)
		return 1
	}
	data, err := os.ReadFile(receipt)
	if err != nil {
		return failed(err)
	}
	read, _ := run.Decode(data)
	held, _ := read.(*run.Object)
	remote := ""
	if held != nil {
		remote = held.Str("remote")
	}
	if !launchToken.MatchString(remote) {
		return failed(fmt.Errorf("%s names no remote home", receipt))
	}
	home := filepath.Join(config.Home(), "state", "codex-remote-"+remote)
	// the owner's signals end the seat, and none ends this before it has cleaned up
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGHUP, syscall.SIGTERM, syscall.SIGINT)
	defer signal.Stop(signals)
	alive := func() bool {
		_, err := os.Stat(home + ".forgotten")
		return errors.Is(err, os.ErrNotExist) && len(signals) == 0
	}
	// A launch replaces the receipt before tmux ends the last one's pane: one at a time, cleanup
	// included, under a lock beside the home, which the first launch has yet to make.
	if err := os.MkdirAll(filepath.Dir(home), 0o700); err != nil {
		return failed(err)
	}
	var guard *os.File
	for guard == nil {
		if !alive() {
			return 0
		}
		if guard, err = lock.Try(home + ".lock"); errors.Is(err, lock.ErrHeld) {
			time.Sleep(50 * time.Millisecond)
		} else if err != nil {
			return failed(err)
		}
	}
	defer guard.Close()
	if _, err := os.Stat(receipt); err != nil {
		return 0
	}
	if err := codexSeatHome(home, remote, env); err != nil {
		return failed(err)
	}
	// A home Go launches in is new (codexLaunched mints its remote), so no earlier server's
	// backfill lease is left in its database to put back.
	source := codexHome(env)
	sqlite, sqliteSet := codexEnv(env, "CODEX_SQLITE_HOME")
	env = append(slices.DeleteFunc(slices.Clone(env), func(pair string) bool {
		return strings.HasPrefix(pair, "CODEX_HOME=") || strings.HasPrefix(pair, "CODEX_SQLITE_HOME=")
	}), "CODEX_HOME="+home)
	cmd = append(cmd, "-c", "sqlite_home="+codexJSON(home))
	runtime, err := os.MkdirTemp("", ".cx-")
	if err != nil {
		return failed(err)
	}
	defer os.RemoveAll(runtime)
	socket := filepath.Join(runtime, "s")
	words := []string{cmd[0], "app-server", "--remote-control", "--listen", "unix://" + socket}
	for i, word := range cmd[:len(cmd)-1] {
		switch word {
		case "-c", "--config":
			words = append(words, "-c", cmd[i+1])
		case "-m", "--model":
			words = append(words, "-c", "model="+codexJSON(cmd[i+1]))
		}
	}
	// Only Codex itself needs the seat's home: its shells and their ak workers keep the login's.
	words = append(words, "-c", `approval_policy="never"`, "-c", `sandbox_mode="danger-full-access"`,
		"-c", "shell_environment_policy.set.CODEX_HOME="+codexJSON(source))
	if sqliteSet {
		words = append(words, "-c", "shell_environment_policy.set.CODEX_SQLITE_HOME="+codexJSON(sqlite))
	}
	log, err := os.Create(filepath.Join(home, "server.log"))
	if err != nil {
		return failed(err)
	}
	defer log.Close()
	server := exec.CommandContext(context.Background(), Binary(cmd[0]), words[1:]...)
	server.Args[0], server.Env, server.Stdout, server.Stderr = cmd[0], env, log, log
	// npm's codex is a parent shim: its server goes with its session
	stop := host.Group(server)
	if err := server.Start(); err != nil {
		return failed(err)
	}
	exited := make(chan struct{})
	go func() { server.Wait(); close(exited) }()
	defer func() {
		host.Term(server)
		select {
		case <-exited:
		case <-time.After(5 * time.Second):
		}
		stop()
		<-exited
	}()
	for {
		if _, err := os.Stat(socket); err == nil {
			break
		}
		select {
		case <-exited:
			return failed(fmt.Errorf("Codex seat server did not start; see %s", filepath.Join(home, "server.log")))
		case <-time.After(50 * time.Millisecond):
		}
		if !alive() {
			return 0
		}
	}
	// written before the TUI starts a turn, whose Stop asks the server
	connection := filepath.Join(home, "connection.json")
	if err := os.WriteFile(connection, []byte(run.Encode(run.Fields("socket", socket))), 0o666); err != nil {
		return failed(err)
	}
	defer os.Remove(connection)
	// The server holds the seat's permissions: since 0.160 a remote TUI asking for its own is
	// refused.  --remote is global, so it goes before a `resume`.
	tui := []string{cmd[0], "--remote", "unix://" + socket}
	tui = append(append(tui, slices.DeleteFunc(slices.Clone(cmd[1:]), func(word string) bool { return word == "--yolo" })...), prompt...)
	// The TUI runs on the seat's terminal, which hands it this process's signals: a server that
	// stops, or a seat forgotten, ends it with one.
	running, ended := make(chan struct{}), make(chan error, 1)
	go func() {
		for {
			select {
			case <-running:
				ended <- nil
				return
			case <-exited:
				ended <- errors.New("Codex seat server stopped")
			case <-time.After(250 * time.Millisecond):
				if alive() {
					continue
				}
				ended <- errGone
			}
			if self, err := os.FindProcess(os.Getpid()); err == nil {
				self.Signal(syscall.SIGTERM)
			}
			return
		}
	}()
	code := terminal(tui, env)
	close(running)
	switch err := <-ended; err {
	case nil:
		return code
	case errGone:
		return 0
	default:
		return failed(err)
	}
}

// errGone is a seat whose owner ended it, or forgot it, under its TUI.
var errGone = errors.New("gone")

// codexSeatHome makes the seat's own Codex home, as codex-seat.py `seat_home` does.  Remote
// enrollment is tied to a home's installation_id and state database, so sharing either lets a
// second seat take the first one's connection; a new database imports every conversation under its
// home first, so the seat's conversations are its own, in a folder that outlives the home and is
// the same whichever login it runs on.  The login, config, extensions and thread names stay shared,
// linked from the login's home; a link the home has, made before or on another login, stays.
func codexSeatHome(home, remote string, env []string) error {
	if err := os.MkdirAll(home, 0o700); err != nil {
		return err
	}
	source := codexHome(env)
	if err := os.MkdirAll(source, 0o777); err != nil {
		return err
	}
	source = codexResolved(source)
	index := filepath.Join(source, "session_index.jsonl")
	file, err := os.OpenFile(index, os.O_CREATE|os.O_WRONLY, 0o666)
	if err != nil {
		return err
	}
	file.Close()
	now := time.Now()
	if err := os.Chtimes(index, now, now); err != nil {
		return err
	}
	seats := filepath.Join(config.UserHome(), ".codex", "agentkit-seats")
	conversations := []string{"sessions", "archived_sessions"}
	for _, name := range conversations {
		if _, err := os.Lstat(filepath.Join(home, name)); errors.Is(err, os.ErrNotExist) {
			own := filepath.Join(seats, remote, name)
			if err := os.MkdirAll(own, 0o700); err != nil {
				return err
			}
			if err := os.Symlink(own, filepath.Join(home, name)); err != nil {
				return err
			}
		}
	}
	names := []string{"auth.json", "config.toml", "session_index.jsonl"}
	entries, _ := os.ReadDir(source)
	for _, entry := range entries {
		names = append(names, entry.Name())
	}
	skipped := append([]string{"installation_id", "app-server-control", "tmp", filepath.Base(seats)}, conversations...)
	for _, name := range slices.Compact(slices.Sorted(slices.Values(names))) {
		if slices.Contains(skipped, name) || strings.Contains(name, ".sqlite") {
			continue
		}
		target, linked := filepath.Join(home, name), filepath.Join(source, name)
		if info, err := os.Lstat(target); err == nil && info.Mode()&os.ModeSymlink != 0 {
			if to, _ := os.Readlink(target); to == linked {
				continue
			}
			if err := os.Remove(target); err != nil {
				return err
			}
		}
		if _, err := os.Stat(target); errors.Is(err, os.ErrNotExist) {
			if err := os.Symlink(linked, target); err != nil {
				return err
			}
		}
	}
	return nil
}

// codexHome is the login's Codex home the environment names: $CODEX_HOME, else ~/.codex.
func codexHome(env []string) string {
	if home, set := codexEnv(env, "CODEX_HOME"); set {
		return home
	}
	return filepath.Join(config.UserHome(), ".codex")
}

// codexResolved is a path made absolute, each link it passes through followed, as Python's
// Path.resolve makes it.
func codexResolved(path string) string {
	path, _ = filepath.Abs(path)
	if resolved, err := filepath.EvalSymlinks(path); err == nil {
		return resolved
	}
	return path
}

// codexEnv is the value environment gives key, the last one given, and whether it gives one.
func codexEnv(env []string, key string) (string, bool) {
	for i := len(env) - 1; i >= 0; i-- {
		if name, value, _ := strings.Cut(env[i], "="); name == key {
			return value, true
		}
	}
	return "", false
}
