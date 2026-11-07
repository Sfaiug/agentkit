package harness

import (
	"os"
	"path/filepath"
	"testing"
)

func TestAdapterOnlySeatsUseDefaultHooksWhileUnreadPluginsStayUnread(t *testing.T) {
	adapters := t.TempDir()
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	if err := os.WriteFile(filepath.Join(adapters, "echo.toml"), []byte("version = 1\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	plugins["unread"] = plugin{}
	t.Cleanup(func() { delete(plugins, "unread") })
	for _, name := range []string{"echo", "", "unread", "no-such-harness"} {
		want := name == "echo"
		if _, known := Reopens(name); known != want || Looks(name) != want {
			t.Fatalf("%q: reopens=%v, looks=%v", name, known, Looks(name))
		}
		if path, known := Conversation(name, map[string]any{"conversation": "c"}); path != "" || known != want {
			t.Fatalf("%q: conversation=%q, known=%v", name, path, known)
		}
		if said, cards, known, err := Answered(name, map[string]any{"conversation": "c"}); said != nil || cards != nil || known != want || err != nil {
			t.Fatalf("%q: answered %v %v, known=%v, %v", name, said, cards, known, err)
		}
	}
}
