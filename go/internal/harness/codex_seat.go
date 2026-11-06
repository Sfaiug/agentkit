package harness

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

const (
	codexReceiptEnv = "AGENTKIT_CODEX_RECEIPT"
	codexCaptureEnv = "AGENTKIT_CODEX_CAPTURE"
	// Codex's default command deadline; only Interrupt has its separate three-second cap.
	// Callbacks stay ordered: a late tool completion must not clear a newer question.
	codexHookTimeout = 600
	// A Plan-mode turn asks with `request_user_input`, which waits in a dialog of the seat's own,
	// and an async card with `request_user_input_async`; Codex reads a matcher as a regex.
	codexQuestions = "request_user_input(_async)?"
)

// codexEffort is an effort -c can take inside the quotes the line puts around it.
var codexEffort = regexp.MustCompile(`^[A-Za-z0-9_.-]*$`)

// codexInteractive prints the line a Codex seat opens on, as adapters/codex.sh `interactive`
// does, with Go's wrapper where tools/codex-seat.py is: the rulebook it is handed, then `codex`,
// resumed on the thread its record owns, at the model (none for `default`) and effort, with the
// repository's AGENTS.md kept out (the rulebook holds it), its first prompt last after a `--`.
// An account's Codex home is codex.sh's to make, so Python opens that seat.
func codexInteractive(root string, args []string, out, errOut io.Writer) int {
	switch {
	case len(args) < 2:
		fmt.Fprintln(errOut, "codex interactive needs <model> <effort> [session-id [new]]")
		return 2
	case len(args) > 3 && args[3] == "new":
		// the TUI takes no thread id of anyone else's making; the seat's SessionStart receipt
		// records the one it opens
		fmt.Fprintln(errOut, "codex interactive: the TUI cannot be given a thread id")
		return 3
	case os.Getenv("AGENTKIT_ACCOUNT") != "":
		fmt.Fprintln(errOut, "ak adapter: codex interactive on an account is not carried out in Go yet")
		return 2
	case !codexEffort.MatchString(args[1]):
		fmt.Fprintf(errOut, "codex interactive: effort '%s' is not a plain word\n", args[1])
		return 2
	}
	rulebook := os.Getenv("AGENTKIT_RULEBOOK")
	if _, err := os.Stat(rulebook); rulebook == "" || err != nil {
		fmt.Fprintln(errOut, "codex interactive: no rulebook for this seat")
		return 2
	}
	line := []string{"env", "AGENTKIT_RULEBOOK=" + rulebook, filepath.Join(root, "bin", "ak"), "adapter", root, "codex", "seat", "--", "codex"}
	if len(args) > 2 && args[2] != "" {
		line = append(line, "resume", args[2])
	}
	line = append(line, "--yolo")
	if args[0] != "" && args[0] != "default" {
		line = append(line, "-m", args[0])
	}
	line = append(line, "-c", `model_reasoning_effort="`+args[1]+`"`, "-c", "project_doc_max_bytes=0")
	if first := os.Getenv("AGENTKIT_FIRST_PROMPT"); first != "" {
		line = append(line, "--", first)
	}
	fmt.Fprintln(out, commandhelp.ShellJoin(line))
	return 0
}

// codexServeSeat is tools/codex-seat.py's launch, in the seat's pane: the folder trusted, the rulebook
// handed over as `developer_instructions`, and, where this launch has a receipt and its Codex
// reports hook support, ak's hooks registered beside the receipt's capture and the TUI run on an
// app server of the seat's own (`codexOnServer`); else the TUI alone, as it came.
func codexServeSeat(words, env []string, errOut io.Writer, terminal func(words, env []string) int) int {
	at := slices.Index(words, "--")
	if at < 0 {
		at = len(words)
	}
	cmd, prompt := slices.Clone(words[:at]), words[at:]
	codexTrustHere()
	rulebook := os.Getenv("AGENTKIT_RULEBOOK")
	rules, err := os.ReadFile(rulebook)
	if err != nil {
		// a seat up without the rules it was launched with would work to nobody's
		fmt.Fprintf(errOut, "codex seat: cannot read this seat's rulebook %s: %v\n", rulebook, err)
		return 1
	}
	cmd = append(cmd, "-c", "developer_instructions="+string(rules))
	// only this invocation installs a hook: a nested launch needs a receipt of its own
	receipt := ""
	env = slices.DeleteFunc(slices.Clone(env), func(pair string) bool {
		key, value, _ := strings.Cut(pair, "=")
		if key == codexReceiptEnv {
			receipt = value
		}
		return key == codexReceiptEnv || key == codexCaptureEnv
	})
	if receipt == "" {
		return terminal(append(cmd, prompt...), env)
	}
	if !codexHooked(cmd[0], env) {
		fmt.Fprintln(errOut, "orch: Codex cannot capture seat ownership on this version; an unbound seat starts fresh next time")
		return terminal(append(cmd, prompt...), env)
	}
	self, _ := os.Executable()
	self, _ = filepath.EvalSymlinks(self)
	cmd = append(cmd, codexHookFlags(self)...)
	return codexOnServer(cmd, prompt, receipt, append(env, codexCaptureEnv+"="+receipt), errOut, terminal)
}

// codexHooked is whether that Codex takes hooks on its command line: its help names the flag
// that would bypass their trust, which is never passed, as no other hook's trust is waived.  The
// Codex asked is the one the seat runs, found where an installer put it.
func codexHooked(program string, env []string) bool {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	help := exec.CommandContext(ctx, Binary(program), "--help")
	help.Env = env
	out, _ := help.Output()
	return bytes.Contains(out, []byte("--dangerously-bypass-hook-trust"))
}

// A codexHook is one event's command, as the events Codex emits say what its seat is doing.
type codexHook struct {
	event, also, matcher string
	timeout              int
}

// codexHooks are the seat's hooks, each the shared seat hook on Go's own adapter verb, which
// reads Codex's payload first (`codexHookEvent`).  They go on the launch's command line rather
// than into ~/.codex/config.toml, which is the user's.  A Stop is judged by the end-of-turn rule
// too, its answer Codex's to read; SessionStart captures the launch's receipt, and a compaction
// leaves the seat holding its launch's rulebook again; PreToolUse is a question going up.
var codexHooks = []codexHook{
	{event: "SessionStart", timeout: codexHookTimeout},
	{event: "UserPromptSubmit", timeout: codexHookTimeout},
	{event: "Stop", also: "seat-state orchestrator-stop", timeout: codexHookTimeout},
	{event: "Interrupt", timeout: 3},
	{event: "PermissionRequest", timeout: codexHookTimeout},
	{event: "PreToolUse", matcher: codexQuestions, timeout: codexHookTimeout},
	{event: "PostToolUse", timeout: codexHookTimeout},
}

// codexHookFlags are the -c words that register codexHooks on self, this program, then the one
// that trusts exactly them.  Codex 0.160 runs a hook only once its hash is trusted, else stops a new seat on "Hooks
// need review"; it reads that trust from the command line too, keyed by layer, event, group and
// position, and hashes the hook's sorted JSON, its group's matcher in it (`hook_hash` in
// codex-rs/hooks/src/engine/discovery.rs).
func codexHookFlags(self string) []string {
	base := commandhelp.ShellJoin([]string{self, "adapter", filepath.Dir(filepath.Dir(self)), "codex", "hook"})
	var flags, trusted []string
	for _, hook := range codexHooks {
		command := strings.TrimSpace(base + " " + hook.also)
		matcher := ""
		identity := map[string]any{"event_name": codexLabel(hook.event), "hooks": []any{map[string]any{
			"async": false, "command": command, "timeout": hook.timeout, "type": "command"}}}
		if hook.matcher != "" {
			matcher = "matcher=" + codexJSON(hook.matcher) + ","
			identity["matcher"] = hook.matcher
		}
		flags = append(flags, "-c", fmt.Sprintf(`hooks.%s=[{%shooks=[{type="command",command=%s,timeout=%d}]}]`,
			hook.event, matcher, codexJSON(command), hook.timeout))
		digest := sha256.Sum256([]byte(codexJSON(identity)))
		trusted = append(trusted, fmt.Sprintf("%s={trusted_hash=%s}",
			codexJSON("/<session-flags>/config.toml:"+codexLabel(hook.event)+":0:0"), codexJSON("sha256:"+hex.EncodeToString(digest[:]))))
	}
	return append(flags, "-c", "hooks.state={"+strings.Join(trusted, ",")+"}")
}

// codexLabel is an event as Codex names it in a hook's trust: PreToolUse is pre_tool_use.
func codexLabel(event string) string {
	var label strings.Builder
	for i, r := range event {
		if i > 0 && 'A' <= r && r <= 'Z' {
			label.WriteByte('_')
		}
		label.WriteRune(r)
	}
	return strings.ToLower(label.String())
}

// codexJSON is a value as compact JSON, its keys sorted and nothing escaped JSON does not need,
// as serde writes it: also a TOML basic string, for a string.
func codexJSON(value any) string {
	var out bytes.Buffer
	encoder := json.NewEncoder(&out)
	encoder.SetEscapeHTML(false)
	encoder.Encode(value)
	return strings.TrimSuffix(out.String(), "\n")
}

// codexTrustHere marks the launch's folder trusted in ~/.codex/config.toml, which every account's
// home links to, so the seat opens on its prompt rather than on "do you trust this folder?", as
// codex.py `trust_here` does.  Appended, never rewritten, since the file is the user's; read
// first, so a folder trusted in any spelling gets no second table, and a file that does not parse,
// or would not with it, a `projects` inline table, or a file this cannot read or write, stays as
// it is: Codex asks for itself.
func codexTrustHere() {
	here, err := os.Getwd()
	if err == nil {
		here, err = filepath.EvalSymlinks(here)
	}
	path := filepath.Join(config.UserHome(), ".codex", "config.toml")
	data, read := os.ReadFile(path)
	if err != nil || read != nil && !os.IsNotExist(read) || !utf8.Valid(data) {
		return
	}
	entry := "\n[projects." + codexJSON(here) + "]\ntrust_level = \"trusted\"\n"
	held, err := config.ReadTOML(string(data))
	projects, ok := held["projects"].(map[string]any)
	if _, set := held["projects"]; err != nil || set && !ok {
		return
	}
	if _, trusted := projects[here]; trusted {
		return
	}
	if _, err := config.ReadTOML(string(data) + entry); err != nil || os.MkdirAll(filepath.Dir(path), 0o700) != nil {
		return
	}
	if file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o666); err == nil {
		file.WriteString(entry)
		file.Close()
	}
}
