package harness

import "testing"

func TestAdapterOnlySeatsUseDefaultHooksWhileUnreadPluginsStayUnread(t *testing.T) {
	for _, name := range []string{"echo", "", "antigravity"} {
		want := name == "echo"
		if _, known := Reopens(name); known != want || Looks(name) != want {
			t.Fatalf("%q: reopens=%v, looks=%v", name, known, Looks(name))
		}
		if path, known := Conversation(name, map[string]any{"conversation": "c"}); path != "" || known != want {
			t.Fatalf("%q: conversation=%q, known=%v", name, path, known)
		}
	}
}
