package harness

import "testing"

func TestAdapterOnlySeatsUseDefaultHooksWhileUnreadPluginsStayUnread(t *testing.T) {
	plugins["unread"] = plugin{}
	t.Cleanup(func() { delete(plugins, "unread") })
	for _, name := range []string{"echo", "", "unread"} {
		want := name == "echo"
		if _, known := Reopens(name); known != want || Looks(name) != want {
			t.Fatalf("%q: reopens=%v, looks=%v", name, known, Looks(name))
		}
		if path, known := Conversation(name, map[string]any{"conversation": "c"}); path != "" || known != want {
			t.Fatalf("%q: conversation=%q, known=%v", name, path, known)
		}
	}
}
