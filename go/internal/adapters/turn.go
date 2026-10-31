package adapters

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"syscall"

	"agentkit/internal/config"
	"agentkit/internal/harness"
)

// Turn is one worker's turn, `run <model> <effort> <workspace> <prompt-file> <out-dir> [<id>]`,
// as the Python adapters' `run`: the harness runs headless in the workspace on the login
// $AGENTKIT_ACCOUNT names, with the worker token ak holds for it, resuming the id's conversation
// or else starting one of its own.  The prompt is the file its words name, or else goes down its
// stdin: never one argument, which Linux caps at 128 KiB.  Its stdout goes to events.jsonl and its
// stderr to stderr.log in the out-dir, then the last result's text to final.md and the last
// session id the events name to session_id.  It answers the harness's exit code, or 2 where it
// starts none.
func Turn(name string, args []string, errOut io.Writer) int {
	if len(args) < 5 {
		fmt.Fprintf(errOut, "%s run needs <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]\n", name)
		return 2
	}
	workspace, prompt, out, id := args[2], args[3], args[4], ""
	if len(args) > 5 {
		id = args[5]
	}
	if launch, err := config.Section(name, "launch"); err != nil || launch["turn"] == nil {
		return refused(name, "run", err, errOut)
	}
	call, err := conversation(name, id, id == "")
	call["model"], call["effort"], call["prompt"] = args[:1], args[1:2], []string{prompt}
	words := []string(nil)
	if err == nil {
		words, _, err = config.Words(name, "turn", call)
	}
	if err != nil {
		return refused(name, "run", err, errOut)
	}
	if err := os.MkdirAll(out, 0o777); err != nil {
		fmt.Fprintf(errOut, "%s run: %s\n", name, err)
		return 2
	}
	if info, err := os.Stat(workspace); err != nil || !info.IsDir() {
		fmt.Fprintf(errOut, "%s run: no such workspace: %s\n", name, workspace)
		return 2
	}
	given, err := os.Open(prompt)
	if err != nil {
		fmt.Fprintf(errOut, "%s run: no such prompt file: %s\n", name, prompt)
		return 2
	}
	defer given.Close()
	login, _, err := config.Account(name)
	if err == nil && login.Account != "" {
		err = share(login)
	}
	if err != nil {
		fmt.Fprintf(errOut, "%s run: %s\n", name, err)
		return 2
	}
	words, env := environ(words, token(name, login, login.Environ(os.Environ())))
	var stdin io.Reader = given
	if slices.Contains(words, prompt) {
		stdin = os.Stdin // it reads the prompt from the file itself
	}
	code := start(words, workspace, env, stdin, out, errOut)
	summarize(out)
	return code
}

// token is env with the worker token ak holds for the login, where it holds one, as its
// manifest's `[worker_token]` names it: the file under ~/.agentkit/secrets, an account's beside
// it under its name, and the variable it goes in.
func token(name string, login config.Login, env []string) []string {
	table, _ := config.Section(name, "worker_token")
	file, _ := table["file"].(string)
	variable, _ := table["env"].(string)
	if file == "" || variable == "" {
		return env
	}
	if login.Account != "" {
		file += "." + login.Account
	}
	data, _ := os.ReadFile(filepath.Join(config.Home(), "secrets", file))
	if value := strings.TrimRight(string(data), "\n"); value != "" {
		_, env = environ([]string{"env", variable + "=" + value}, env)
	}
	return env
}

// start runs the words in the workspace, their output in the out-dir's files, and answers their
// exit code as a shell gives it: 128 and the signal's number for one a signal ended, 127 where
// the program is not found.
func start(words []string, workspace string, env []string, stdin io.Reader, out string, errOut io.Writer) int {
	events, err := os.Create(filepath.Join(out, "events.jsonl"))
	if err != nil {
		fmt.Fprintln(errOut, err)
		return 2
	}
	defer events.Close()
	log, err := os.Create(filepath.Join(out, "stderr.log"))
	if err != nil {
		fmt.Fprintln(errOut, err)
		return 2
	}
	defer log.Close()
	program := harness.Binary(words[0])
	if program == "" {
		fmt.Fprintf(log, "ak adapter: %s: not found\n", words[0])
		return 127
	}
	cmd := exec.Command(program, words[1:]...)
	cmd.Args[0], cmd.Dir, cmd.Env = words[0], workspace, env
	cmd.Stdin, cmd.Stdout, cmd.Stderr = stdin, events, log
	if err := cmd.Run(); cmd.ProcessState == nil {
		fmt.Fprintf(log, "ak adapter: %s: %s\n", words[0], err)
		return 126
	}
	if status, ok := cmd.ProcessState.Sys().(syscall.WaitStatus); ok && status.Signaled() {
		return 128 + int(status.Signal())
	}
	return cmd.ProcessState.ExitCode()
}

// summarize writes final.md and session_id from the turn's events as the Python adapters' jq
// reads them: the last result event's `result`, and the last session id an event names, each
// "" where it is null or false.  Events jq cannot read, not JSON or a value neither an object
// nor null, leave both empty.
func summarize(out string) {
	data, err := os.ReadFile(filepath.Join(out, "events.jsonl"))
	events := json.NewDecoder(bytes.NewReader(data))
	events.UseNumber()
	var result, session any
	for err == nil {
		var event any
		if err = events.Decode(&event); errors.Is(err, io.EOF) {
			break
		}
		object, read := event.(map[string]any)
		if err == nil && event != nil && !read {
			err = errors.New("not an object")
		}
		if object["type"] == "result" {
			result = object["result"]
		}
		if object["session_id"] != nil {
			session = object["session_id"]
		}
	}
	final, id := "", ""
	if err == nil || errors.Is(err, io.EOF) {
		final, id = line(result), line(session)
	}
	os.WriteFile(filepath.Join(out, "final.md"), []byte(final), 0o666)
	os.WriteFile(filepath.Join(out, "session_id"), []byte(id), 0o666)
}

// line is a value as `jq -r '. // ""'` prints it.
func line(value any) string {
	switch value := value.(type) {
	case nil:
		return "\n"
	case bool:
		if !value {
			return "\n"
		}
	case string:
		return value + "\n"
	}
	var text bytes.Buffer
	encoder := json.NewEncoder(&text)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	encoder.Encode(value)
	return text.String()
}
