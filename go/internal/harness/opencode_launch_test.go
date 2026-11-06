package harness

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A launch gets a receipt of its own, the session it resumes in it from the start and the plugin
// asked to title it as the seat is named; the session read back is what the plugin wrote there,
// and retiring the launch takes its receipt.
func TestAnOpenCodeLaunchKeepsItsSessionInAReceiptOfItsOwn(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(filepath.Join(home, ".agentkit", "state"), 0o700); err != nil {
		t.Fatal(err)
	}
	issued, env, err := Launched("opencode", "acme", home, "ses_A012z", run.NewObject())
	if err != nil {
		t.Fatal(err)
	}
	receipt := opencodeReceipt(issued.Str("opencode_launch"))
	if len(env) != 1 || env[0] != opencodeReceiptEnv+"="+receipt || !issued.Has("session_title") || issued.Get("session_title") != nil {
		t.Fatal(issued, env)
	}
	request, _ := run.ReadJSON(filepath.Join(receipt, "title-request.json"))
	if request == nil || request.Str("title") != "acme" || !launchToken.MatchString(request.Str("id")) {
		t.Fatal("no title asked of the plugin", request)
	}
	record := map[string]any{"opencode_launch": issued.Str("opencode_launch")}
	if got := opencodeConversation(record); got != "ses_A012z" {
		t.Fatal(got)
	}
	if err := os.WriteFile(filepath.Join(receipt, "session"), []byte("ses_B345y\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if conversation, known := Owned("opencode", record); conversation != "ses_B345y" || !known {
		t.Fatal(conversation, known)
	}
	if err := Retire("opencode", issued); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(receipt); !os.IsNotExist(err) || opencodeConversation(record) != "" {
		t.Fatal("the retired launch's receipt stands", err)
	}
}
