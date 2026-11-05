package harness

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
)

// Conversation is the file that harness keeps the conversation a seat's record names in (its
// plugin's `transcript`), "" where the record names none; false where Go does not read that
// harness's conversations yet.
func Conversation(name string, record map[string]any) (string, bool) {
	if hook := plugins[name].conversation; hook != nil {
		return hook(record), true
	}
	_, plugged := plugins[name]
	return "", !plugged && seatDefaults(name).seats
}

// claudeConversation is where Claude Code files it (claude.py `transcript_path`): under the
// seat's working directory, in the folder of the login it runs on.
func claudeConversation(record map[string]any) string {
	conversation, _ := record["conversation"].(string)
	cwd, _ := record["cwd"].(string)
	if conversation == "" || cwd == "" {
		return ""
	}
	home, _ := os.UserHomeDir()
	folder := ".claude"
	if account, _ := record["account"].(string); account != "" && account != "default" {
		folder += "-" + account
	}
	return filepath.Join(home, folder, "projects", projectFolder(cwd), conversation+".jsonl")
}

// Framed is whether that frame of the harness's manifest opens the words, and for a notice is all
// of them.
func Framed(name, frame, said string) bool {
	rest, opened := strings.CutPrefix(said, frame)
	ends, notice := plugins[name].notices[frame]
	return opened && (!notice || slices.Contains(ends, rest))
}
