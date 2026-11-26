package menu

import (
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/googlecloud"
	"agentkit/internal/notify"
)

// ConfigServices reads the saved Discord and cloud status without contacting either service.
func ConfigServices() (discord, cloud string) {
	discord = "not connected"
	if who, hook := DiscordShown(); hook != "" {
		discord = "webhook " + hook
		if who != "" {
			discord = who + " · " + discord
		}
	}
	return discord, googlecloud.Summary(false)
}

// DiscordShown is who a card pings and where it goes, as `Discord` shows them (menu.discord_shown):
// `@acme-owner`, the name a delivered card's receipt gave this user id (notify.Pinged), the id's
// last 4 digits until one has, and `…a1B2c3`, the only part of the webhook ever shown; "" for one
// not set.
func DiscordShown() (who, hook string) {
	secret := func(name string) []rune {
		data, _ := os.ReadFile(filepath.Join(config.Home(), "secrets", name))
		return []rune(strings.TrimFunc(string(data), config.Space))
	}
	if id := secret("discord_user_id"); len(id) > 0 {
		if who = notify.Pinged(string(id)); who != "" {
			who = "@" + who
		} else {
			who = "id …" + string(id[max(0, len(id)-4):])
		}
	}
	if webhook := secret("discord_webhook"); len(webhook) > 0 {
		hook = "…" + string(webhook[max(0, len(webhook)-6):])
	}
	return who, hook
}
