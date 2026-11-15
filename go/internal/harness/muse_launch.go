package harness

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/commandhelp"
)

func museInteractive(root string, args []string, out, errOut io.Writer) int {
	if len(args) < 2 {
		fmt.Fprintln(errOut, "muse interactive needs <model> <effort> [session-id [new]]")
		return 2
	}
	if len(args) > 3 && args[3] == "new" {
		return 3 // Muse's TUI cannot be given a new session id.
	}
	rulebook := os.Getenv("AGENTKIT_RULEBOOK")
	if _, err := os.ReadFile(rulebook); err != nil {
		fmt.Fprintln(errOut, "muse interactive: no rulebook for this seat")
		return 2
	}
	// the line runs later, outside this adapter's environment: an account's login goes into it by name
	var login []string
	if account := os.Getenv("AGENTKIT_ACCOUNT"); account != "" {
		if err := museHome(account); err != nil {
			fmt.Fprintln(errOut, "muse interactive:", err)
			return 2
		}
		login = []string{"env", "-u", "META_API_KEY", "XDG_CONFIG_HOME=" + museConfig(account)}
	}
	line := append(login, "env", "MUSE_NO_AUTO_UPDATE=1", "MUSE_LAUNCHER_INSTALL=0", "TBH_EVAL_APPEND_SYSTEM_PROMPT_FILE="+rulebook,
		filepath.Join(root, "bin", "ak"), "adapter", root, "muse", "seat", "--", "muse")
	if len(args) > 2 && args[2] != "" {
		line = append(line, "resume", args[2])
	}
	// --yolo also removes the native question tool; these switches keep it available.
	line = append(line, "--trust-workspace", "--disable-approval", "--disable-sandbox", "--provider", "meta",
		"--model", args[0], "--reasoning-effort", args[1])
	fmt.Fprintln(out, commandhelp.ShellJoin(line))
	return 0
}

func museSeatWords(words, env []string) []string {
	values := map[string]string{}
	for _, pair := range env {
		key, value, _ := strings.Cut(pair, "=")
		values[key] = value
	}
	if values["AGENTKIT_SESSION"] == "" {
		return words
	}
	events := museEvents(words[0], env)
	if events == nil {
		return words
	}
	// the sessions `/new` opens read the settings file's, which each launch makes sure of in the
	// config home this Muse reads; one it cannot write leaves the launch as it was
	home := values["XDG_CONFIG_HOME"]
	if home == "" {
		home = museConfig("")
	}
	museWire(home, events)
	self, err := os.Executable()
	if err != nil {
		return words
	}
	hook := []string{"env"}
	// Muse drops the pane's environment when firing a hook; quote it into each command here.
	for _, key := range []string{"AGENTKIT_SESSION", "TMUX", "TMUX_PANE", "AGENTKIT_TMUX_SOCKET", museReceiptEnv} {
		hook = append(hook, key+"="+values[key])
	}
	hook = append(hook, self, "adapter", filepath.Dir(filepath.Dir(self)), "muse", "hook")
	for _, event := range events {
		entry := map[string]any{"type": "command", "command": commandhelp.ShellJoin(hook)}
		if museAsync(event) {
			entry["async"] = true
		}
		data, _ := json.Marshal([]any{map[string]any{"hooks": []any{entry}}})
		words = append(words, "-c", "hooks."+event+"="+string(data))
	}
	return words
}
