package harness

import (
	"os"
	"path/filepath"
)

// Conversation is the file that harness keeps the conversation a seat's record names in (its
// plugin's `transcript`), "" where the record names none; false where Go does not read that
// harness's conversations yet.
func Conversation(name string, record map[string]any) (string, bool) {
	if hook := plugins[name].conversation; hook != nil {
		return hook(record), true
	}
	return "", false
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
