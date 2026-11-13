package harness

import (
	"crypto/rand"
	"encoding/hex"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// opencodeReceiptEnv names a launch's receipt to the seat plugin (opencode.py RECEIPT_ENV).
const opencodeReceiptEnv = "AGENTKIT_OPENCODE_RECEIPT"

// OpenCode's TUI cannot be told the id of a session it has not opened, so each launch learns its
// own: a receipt, a folder in state/ named in its record and its environment, into which ak
// writes the session the seat is in (opencode.py `launched`, `follow`).  A resumed session is in
// it from the start, and the plugin is asked there to title the session as the seat is named
// (`sync_title`).
func opencodeLaunched(seat, _, conversation string, _ *run.Object) (*run.Object, []string, error) {
	token, request := randomHex(), randomHex()
	path := opencodeReceipt(token)
	if err := os.Mkdir(path, 0o700); err != nil {
		return nil, nil, err
	}
	if conversation != "" {
		if err := os.WriteFile(filepath.Join(path, "session"), []byte(conversation), 0o666); err != nil {
			return nil, nil, err
		}
	}
	tmp := filepath.Join(path, "title-request.tmp")
	err := os.WriteFile(tmp, []byte(run.Encode(run.Fields("title", seat, "id", request))+"\n"), 0o666)
	if err == nil {
		err = os.Rename(tmp, filepath.Join(path, "title-request.json"))
	}
	if err != nil {
		return nil, nil, err
	}
	return run.Fields("opencode_launch", token, "session_title", nil), []string{opencodeReceiptEnv + "=" + path}, nil
}

// opencodeReceipt is the receipt a launch's token names.
func opencodeReceipt(token string) string {
	return filepath.Join(config.Home(), "state", "opencode-launch-"+token)
}

// randomHex is 32 random hex digits, Python's uuid.uuid4().hex.
func randomHex() string {
	random := make([]byte, 16)
	rand.Read(random)
	random[6], random[8] = random[6]&0x0f|0x40, random[8]&0x3f|0x80
	return hex.EncodeToString(random)
}
