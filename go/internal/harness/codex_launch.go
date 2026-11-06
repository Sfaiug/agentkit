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

func codexLaunched(cwd, conversation string, before *run.Object) (*run.Object, []string, error) {
	if conversation != "" {
		return nil, nil, errors.New("Codex ownership changed before launch; reopen the seat to start fresh")
	}
	token := codexToken()
	path := filepath.Join(config.Home(), "state", "codex-launch-"+token+".json")
	cwd, err := filepath.Abs(cwd)
	if err != nil {
		return nil, nil, err
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return nil, nil, err
	}
	_, err = file.WriteString(run.Encode(run.Fields("launch", token, "cwd", cwd, "expected", nil, "remote", codexToken())))
	closed := file.Close()
	if err != nil || closed != nil {
		os.Remove(path)
		if err == nil {
			err = closed
		}
		return nil, nil, err
	}
	history := append([]any(nil), before.List("codex_history")...)
	if before.Truthy("conversation") || before.Truthy(codexLaunch) {
		old := run.NewObject()
		for _, key := range []string{"conversation", "id_source", codexLaunch} {
			if before.Has(key) {
				old.Set(key, before.Get(key))
			}
		}
		receipt := codexReceipt(before)
		if receipt == nil {
			receipt = run.NewObject()
		}
		old.Set("receipt", receipt)
		history = append(history, old)
	}
	var kept any
	if len(history) > 0 {
		kept = history
	}
	return run.Fields(codexLaunch, token, "codex_history", kept, "conversation", nil, "id_source", nil, "resumable", false),
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
