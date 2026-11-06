package menu

import (
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/googlecloud"
	"agentkit/internal/notify"
)

// ConfigServices reads the saved Discord and cloud status without contacting either service.
func ConfigServices(now time.Time) (discord, cloud string) {
	secret := func(name string) string {
		data, _ := os.ReadFile(filepath.Join(config.Home(), "secrets", name))
		return strings.TrimFunc(string(data), config.Space)
	}
	discord = "not connected"
	if hook := []rune(secret("discord_webhook")); len(hook) > 0 {
		var parts []string
		if user := secret("discord_user_id"); user != "" {
			if name := notify.Pinged(user); name != "" {
				parts = append(parts, "@"+name)
			} else {
				id := []rune(user)
				parts = append(parts, "id …"+string(id[max(0, len(id)-4):]))
			}
		}
		discord = strings.Join(append(parts, "webhook …"+string(hook[max(0, len(hook)-6):])), " · ")
	}
	return discord, googlecloud.Summary(now, false)
}
