package notify

import (
	"path/filepath"

	"agentkit/internal/run"
)

// Pinged is the name a delivered card's receipt gave this user, or empty until one has.
func Pinged(user string) string {
	known, _ := run.ReadJSON(filepath.Join(state(), "discord-user.json"))
	if known != nil && known.Str("id") == user {
		return known.Str("name")
	}
	return ""
}
