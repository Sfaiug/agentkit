package cli

import (
	"cmp"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

// menuDiscord is `Discord` on `c` (menu.config_discord): who a card mentions and the webhook it
// goes to, a row each, each typed anew in a field under its row (saveDiscord).
func menuDiscord(keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	return configPage("discord", "A card reads only Needs you · <seat> or Done · <seat>, and mentions you.", func() ([]menu.PageRow, bool) {
		who, hook := menu.DiscordShown()
		return []menu.PageRow{
			{Label: "Mention", Value: cmp.Or(who, "nobody"), Placeholder: "your Discord user id",
				Field: func(typed string) string { return saveDiscord("discord_user_id", typed) }},
			{Label: "Webhook", Value: cmp.Or(hook, "not connected"), Placeholder: "your channel's webhook URL",
				Field: func(typed string) string { return saveDiscord("discord_webhook", typed) }},
		}, true
	}, keyboard, painter)
}

// saveDiscord is one of Discord's secrets typed in its field (menu.discord_secret): what was typed,
// spaces around it aside, written owner-only as install.sh writes it.  Nothing typed keeps what is
// there, and a user id that is not digits is refused, nothing written.
func saveDiscord(name, typed string) string {
	value := strings.TrimFunc(typed, config.Space)
	switch {
	case value == "":
		return ""
	case name == "discord_user_id" && strings.Trim(value, "0123456789") != "":
		return "a user id is only digits: Discord's Copy User ID gives it"
	}
	path := filepath.Join(config.Home(), "secrets", name)
	err := config.EnsureDirs()
	if err == nil {
		err = os.WriteFile(path, []byte(value+"\n"), 0o600)
	}
	if err == nil {
		err = os.Chmod(path, 0o600) // one written before stays owner-only too
	}
	if err != nil {
		return "discord: " + config.PyError(err)
	}
	return ""
}
