package menu

import (
	"os"
	"path/filepath"
	"testing"
)

func TestConfigServicesShowSavedStatusWithoutRevealingSecrets(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	write := func(name, text string) {
		t.Helper()
		path := filepath.Join(home, ".agentkit", name)
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0600); err != nil {
			t.Fatal(err)
		}
	}
	discord, cloud := ConfigServices()
	if discord != "not connected" || cloud != "off" {
		t.Fatalf("unconfigured: %q, %q", discord, cloud)
	}
	write("secrets/discord_webhook", "https://example.com/acme-secret\n")
	write("secrets/discord_user_id", "12345678\n")
	discord, _ = ConfigServices()
	if discord != "id …5678 · webhook …secret" {
		t.Fatal(discord)
	}
	write("state/discord-user.json", `{"id":"12345678","name":"acme-owner"}`)
	discord, _ = ConfigServices()
	if discord != "@acme-owner · webhook …secret" {
		t.Fatal(discord)
	}
	write("secrets/discord_user_id", "87654321\n")
	discord, _ = ConfigServices()
	if discord != "id …4321 · webhook …secret" {
		t.Fatal(discord)
	}
}
