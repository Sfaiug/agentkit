package harness

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func codexToken() string {
	var token [16]byte
	rand.Read(token[:])
	token[6], token[8] = token[6]&15|64, token[8]&63|128
	return hex.EncodeToString(token[:])
}

// codexLaunched writes a launch receipt of this launch's own before its TUI starts, for its
// SessionStart hook to fill in, as codex.py `prepare` does.  A launch resuming the thread its last
// receipt proves carries that receipt's evidence on; a fresh one keeps the last launch's in its
// history.  Either keeps the seat's remote home, where its conversations are.
func codexLaunched(_, cwd, conversation string, before *run.Object) (*run.Object, []string, error) {
	if thread, _ := codexThread(before); conversation != "" && thread != conversation {
		return nil, nil, errors.New("Codex ownership changed before launch; reopen the seat to start fresh")
	}
	previous := codexReceipt(before)
	if previous == nil {
		previous = run.NewObject()
	}
	token := codexToken()
	path := filepath.Join(config.Home(), "state", "codex-launch-"+token+".json")
	receipt := run.Fields("launch", token, "cwd", codexResolved(cwd), "expected", nil, "remote", previous.Get("remote"))
	if !previous.Truthy("remote") {
		receipt.Set("remote", codexToken())
	}
	if conversation != "" {
		// a resumed thread keeps its rollout's directory, even where its checkout was removed
		if previous.Has("cwd") {
			receipt.Set("cwd", previous.Get("cwd"))
		}
		receipt.Set("expected", conversation)
		receipt.Set("event", previous.Get("event"))
		if previous.Truthy("home") {
			receipt.Set("home", previous.Get("home"))
		}
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return nil, nil, err
	}
	_, err = file.WriteString(run.Encode(receipt))
	closed := file.Close()
	if err != nil || closed != nil {
		os.Remove(path)
		if err == nil {
			err = closed
		}
		return nil, nil, err
	}
	history := append([]any(nil), before.List("codex_history")...)
	if conversation == "" && (before.Truthy("conversation") || before.Truthy(codexLaunch)) {
		old := run.NewObject()
		for _, key := range []string{"conversation", "id_source", codexLaunch} {
			if before.Has(key) {
				old.Set(key, before.Get(key))
			}
		}
		old.Set("receipt", previous)
		history = append(history, old)
	}
	var kept any
	if len(history) > 0 {
		kept = history
	}
	var owned, source any
	if conversation != "" {
		owned, source = conversation, codexSource
	}
	return run.Fields(codexLaunch, token, "codex_history", kept, "conversation", owned, "id_source", source, "resumable", conversation != ""),
		[]string{"AGENTKIT_CODEX_RECEIPT=" + path}, nil
}

func codexRetire(record *run.Object) error {
	if token := record.Str(codexLaunch); launchToken.MatchString(token) {
		err := os.Remove(filepath.Join(config.Home(), "state", "codex-launch-"+token+".json"))
		if !os.IsNotExist(err) {
			return err
		}
	}
	return nil
}

func codexMoveReady() bool {
	// Remote enrollment cleanup is still Python's, before the owner is asked.
	homes, err := filepath.Glob(filepath.Join(config.Home(), "state", "codex-remote-*"))
	return err == nil && len(homes) == 0
}

func codexHanded(record *run.Object) (string, bool) {
	if !codexMoveReady() {
		return "", false
	}
	_, path := codexThread(record)
	if path == "" {
		return "It cannot be read here.\n\n", true
	}
	return handedMessages(path, record.Str("orchestrator"), func(entry *run.Object) (string, string) {
		payload := entry.Dict("payload")
		if entry.Str("type") != "event_msg" || payload == nil || payload.Str("type") != "item_completed" || payload.Dict("item") == nil {
			return "", ""
		}
		item := payload.Dict("item")
		who := map[string]string{"UserMessage": "user", "AgentMessage": "model"}[item.Str("type")]
		if who == "" {
			return "", ""
		}
		return who, handedText(item.List("content"), "text", "Text")
	})
}
