package harness

import (
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strconv"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func put(t *testing.T, path, text string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil || os.WriteFile(path, []byte(text), 0o600) != nil {
		t.Fatal(path)
	}
}

// spends is what Spends counts of the file at path from cursor.
func spends(t *testing.T, name, path string, cursor *run.Object) []Spend {
	t.Helper()
	found, told, err := Spends(name, path, cursor)
	if !told || err != nil {
		t.Fatalf("%s: told %v, %v", path, told, err)
	}
	return found
}

// A file is read on from where its cursor stopped, each whole line once: a line still being
// written waits, and a file replaced at its path, or one that shrank, is read from its start.
func TestSpendsReadEachWholeLineOnce(t *testing.T) {
	path := filepath.Join(t.TempDir(), "conversation.jsonl")
	said := `{"type": "assistant", "timestamp": "2026-11-05T09:00:05.250Z", "message": {"id": "msg_01acme", ` +
		`"model": "claude-opus-5-5", "usage": {"input_tokens": 3, "output_tokens": 40, "cache_read_input_tokens": 5000}}}` + "\n"
	writing := `{"type": "assistant", "uuid": "u2", "timestamp": "2026-11-05T09:00:09.500Z", "message": {"usage": {"output_tokens": 7}}}`
	put(t, path, said+"not json\n"+`{"type": "user"}`+"\n"+writing)
	cursor := run.NewObject()
	want := Spend{Start: 0, At: 1793869205.25, Event: "msg_01acme", Tokens: 5043, Model: "claude-opus-5-5", Counts: []int{3, 0, 5000, 40}}
	if got := spends(t, "claude", path, cursor); !reflect.DeepEqual(got, []Spend{want}) {
		t.Fatalf("%+v", got)
	}
	if got := spends(t, "claude", path, cursor); len(got) != 0 {
		t.Fatalf("read again: %+v", got)
	}
	file, _ := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0)
	file.WriteString("\n")
	file.Close()
	ended := Spend{Start: int64(len(said) + len("not json\n") + len(`{"type": "user"}`+"\n")), At: 1793869209.5, Event: "u2", Tokens: 7, Counts: []int{0, 0, 0, 7}}
	if got := spends(t, "claude", path, cursor); !reflect.DeepEqual(got, []Spend{ended}) {
		t.Fatalf("the line once it ended: %+v", got)
	}
	put(t, path+".new", said)
	os.Rename(path+".new", path)
	if got := spends(t, "claude", path, cursor); !reflect.DeepEqual(got, []Spend{want}) {
		t.Fatalf("a file replaced at its path: %+v", got)
	}
	file, _ = os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0)
	file.WriteString(said)
	file.Close()
	spends(t, "claude", path, cursor)
	os.Truncate(path, int64(len(said)))
	if got := spends(t, "claude", path, cursor); !reflect.DeepEqual(got, []Spend{want}) {
		t.Fatalf("a file that shrank: %+v", got)
	}
	if cursor.Str("source") != path || !cursor.Has("identity") {
		t.Fatalf("cursor: %s", run.Line(cursor))
	}
	if offset, _ := cursor.Int("offset"); offset != len(said) {
		t.Fatalf("offset %d", offset)
	}
	if got := spends(t, "opencode", path, run.NewObject()); len(got) != 0 {
		t.Fatalf("a harness with no reader counted %+v", got)
	}
	if _, read := TokenSources("opencode", run.NewObject()); read {
		t.Fatal("a harness with no reader names sources")
	}
}

// A Codex step counts what its rollout's running total grew by since the step before, once by the
// total it reached, split by type under the model of the turn before it.
func TestCodexStepsCountWhatTheTotalGrewBy(t *testing.T) {
	path := filepath.Join(t.TempDir(), "rollout-2026-11-05T09-00-00-t1.jsonl")
	step := func(at string, total, input, cached, written, output int) string {
		return `{"timestamp": "2026-11-05T09:00:` + at + `.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": ` +
			`{"total_token_usage": {"input_tokens": ` + strconv.Itoa(input) + `, "cached_input_tokens": ` + strconv.Itoa(cached) +
			`, "cache_write_input_tokens": ` + strconv.Itoa(written) + `, "output_tokens": ` + strconv.Itoa(output) + `, "total_tokens": ` + strconv.Itoa(total) + `}}}}` + "\n"
	}
	put(t, path, `{"type": "session_meta", "payload": {"id": "t1"}}`+"\n"+
		`{"timestamp": "2026-11-05T09:00:01.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": null}}`+"\n"+
		`{"type": "turn_context", "payload": {"model": "gpt-a"}}`+"\n"+
		step("06", 1000, 900, 300, 100, 100)+step("07", 1000, 900, 300, 100, 100)+step("11", 1500, 1300, 500, 100, 200))
	cursor := run.NewObject()
	var got [][]any
	for _, each := range spends(t, "codex", path, cursor) {
		got = append(got, []any{each.Event, each.Tokens, each.Model, each.Counts})
	}
	name := filepath.Base(path)
	want := [][]any{{name + ":1000", 1000, "gpt-a", []int{500, 100, 300, 100}}, {name + ":1000", 0, "gpt-a", []int{0, 0, 0, 0}},
		{name + ":1500", 500, "gpt-a", []int{200, 0, 200, 100}}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("%v", got)
	}
	if run.Line(cursor.Get("running")) != "[1300, 500, 100, 200]" || cursor.Str("model") != "gpt-a" {
		t.Fatalf("cursor: %s", run.Line(cursor))
	}
	// a cursor saved before the counts were carried reads steps whose counts it lacks
	old := run.Fields("total", 1000)
	if found := spends(t, "codex", path, old); len(found) != 3 || found[0].Tokens != 0 || found[0].Counts != nil || found[2].Counts == nil {
		t.Fatalf("%+v", found)
	}
}

// A Codex seat with no remote store counts its thread's rollout and those of every thread spawned
// from it, at any depth, found in Codex's sessions and archived sessions by their first lines.
func TestCodexSourcesWithoutARemoteAreItsThreadAndItsSpawn(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	rollout := func(folder, id, parent string) string {
		path := filepath.Join(home, ".codex", folder, "2026", "11", "05", "rollout-2026-11-05T09-00-00-"+id+".jsonl")
		source := `"cli"`
		if parent != "" {
			source = `{"subagent": {"thread_spawn": {"parent_thread_id": "` + parent + `"}}}`
		}
		put(t, path, `{"type": "session_meta", "payload": {"id": "`+id+`", "source": `+source+`}}`+"\n")
		return path
	}
	own := []string{rollout("sessions", "t1", ""), rollout("archived_sessions", "t2", "t1"), rollout("sessions", "t3", "t2")}
	rollout("sessions", "other", "")
	rollout("sessions", "child-of-other", "other")
	found, read := TokenSources("codex", run.Fields("conversation", "t1"))
	slices.Sort(found)
	slices.Sort(own)
	if !read || !slices.Equal(found, own) {
		t.Fatalf("%v", found)
	}
}

// A Muse seat counts each provider usage its session's logs and its child sessions' attribute,
// dated when Muse recorded it.
func TestMuseUsageIsWhatItsSessionsAttribute(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("XDG_DATA_HOME", t.TempDir())
	token := strings.Repeat("a", 32)
	put(t, filepath.Join(home, ".agentkit", "state", "muse-launch-"+token, "session"), "acme")
	usage := func(id string, record *run.Object) *run.Object {
		entry := museEvent("kind", "goal_usage_attribution", "record", record)
		entry.Set("id", id)
		entry.Set("recorded_at", 1_793_955_600_250_000)
		return entry
	}
	provided := func(quantity ...any) *run.Object {
		return run.Fields("usage_family", "provider", "quantity", run.Fields(quantity...))
	}
	museLogs(t, "acme", usage("u1", provided("input_tokens", 10, "output_tokens", 5)),
		usage("u2", provided("input_tokens", 10, "reported", false)),
		usage("u3", run.Fields("usage_family", "tool", "quantity", run.Fields("input_tokens", 10))),
		museEvent("kind", "started", "prompt", "Build the acme preview."))
	log := museLog("acme")
	child := filepath.Join(filepath.Dir(log), "subagent", "explore", "session.jsonl")
	put(t, child, "")
	found, read := TokenSources("muse", run.Fields("muse_launch", token))
	if !read || !slices.Equal(found, []string{log, child}) {
		t.Fatalf("%v", found)
	}
	got := spends(t, "muse", log, run.NewObject())
	if len(got) != 1 || got[0].Event != "u1" || got[0].Tokens != 15 || got[0].At != 1793955600.25 || got[0].Model != nil || got[0].Counts != nil {
		t.Fatalf("%+v", got)
	}
}
