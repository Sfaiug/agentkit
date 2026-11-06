package harness

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

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
	schema, err := os.MkdirTemp("", "ak-muse-schema-")
	if err != nil {
		return words
	}
	defer os.RemoveAll(schema)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	probe := exec.CommandContext(ctx, Binary(words[0]), "schema", "generate-json-schema", "--out", schema)
	probe.Env = env
	if probe.Run() != nil {
		return words
	}
	files, _ := filepath.Glob(filepath.Join(schema, "*.json"))
	notifies := false
	for _, file := range files {
		data, _ := os.ReadFile(file)
		notifies = notifies || bytes.Contains(data, []byte(`"notification"`))
	}
	if !notifies {
		return words
	}
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
	for _, event := range []string{"SessionStart", "Stop", "Notification", "PostToolBatch", "Interrupt"} {
		entry := map[string]any{"type": "command", "command": commandhelp.ShellJoin(hook)}
		if event == "PostToolBatch" || event == "Interrupt" {
			entry["async"] = true
		}
		data, _ := json.Marshal([]any{map[string]any{"hooks": []any{entry}}})
		words = append(words, "-c", "hooks."+event+"="+string(data))
	}
	return words
}
