package cli

import (
	"os"
	"path/filepath"
	"testing"
)

func TestADiscordFieldSavesWhatWasTypedOwnerOnly(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	path := filepath.Join(home, ".agentkit", "secrets", "discord_user_id")
	if said := saveDiscord("discord_user_id", "12a4"); said == "" {
		t.Fatal("a user id with a letter was taken")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("a refused id was written:", err)
	}
	if said := saveDiscord("discord_user_id", " 12345678 "); said != "" {
		t.Fatal(said)
	}
	if said := saveDiscord("discord_user_id", "  "); said != "" { // nothing typed keeps it
		t.Fatal(said)
	}
	data, err := os.ReadFile(path)
	info, _ := os.Stat(path)
	if err != nil || string(data) != "12345678\n" || info.Mode().Perm() != 0o600 {
		t.Fatalf("%q %v %v", data, info.Mode(), err)
	}
}
