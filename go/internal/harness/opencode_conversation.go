package harness

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"agentkit/internal/config"
)

var opencodeSession = regexp.MustCompile(`^ses_[0-9A-Za-z]+$`)

// opencodeConversation is the session that seat's launch reported into its receipt (opencode.py
// `conversation`), "" where it reported none yet: OpenCode's TUI is never told an id.
func opencodeConversation(record map[string]any) string {
	token, _ := record["opencode_launch"].(string)
	if !launchToken.MatchString(token) {
		return ""
	}
	reported, err := os.ReadFile(filepath.Join(config.Home(), "state", "opencode-launch-"+token, "session"))
	session := strings.TrimFunc(string(reported), config.Space)
	if err != nil || !opencodeSession.MatchString(session) {
		return ""
	}
	return session
}
