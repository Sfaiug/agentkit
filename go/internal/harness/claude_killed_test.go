package harness

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A transcript's message stamped exactly when the turn began or ended is the turn's, as Python's
// inclusive span keeps it, whatever float its time and the file's make.
func TestAKilledTurnCountsAMessageOnEitherEndOfItsSpan(t *testing.T) {
	line := `{"type":"assistant","timestamp":"2026-11-05T09:00:AT","message":{"id":"msg_acme",` +
		`"model":"claude-opus-5","content":[{"type":"text","text":"Working."}],"usage":{"input_tokens":2,"output_tokens":OUT}}}` + "\n"
	for _, case_ := range []struct{ began, ended, at string }{
		{"04Z", "05.002Z", "05.002Z"}, {"05.011Z", "06Z", "05.011Z"}} {
		home := t.TempDir()
		t.Setenv("HOME", home)
		out := filepath.Join(home, "turn")
		write := func(path, text string) {
			os.MkdirAll(filepath.Dir(path), 0o700)
			if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
				t.Fatal(err)
			}
		}
		write(filepath.Join(out, "harness"), "claude")
		write(filepath.Join(out, "events.jsonl"), `{"type":"system","subtype":"init","cwd":"/acme/widgets","session_id":"session-acme"}`+"\n"+
			strings.NewReplacer("AT", "05.000Z", "OUT", "1").Replace(line))
		sources := claudeTokenSources(run.Fields("cwd", "/acme/widgets", "conversation", "session-acme"))
		write(sources[0], strings.NewReplacer("AT", case_.at, "OUT", "100").Replace(line))
		for name, at := range map[string]string{"harness": case_.began, "events.jsonl": case_.ended} {
			when, _ := time.Parse(time.RFC3339Nano, "2026-11-05T09:00:"+at)
			os.Chtimes(filepath.Join(out, name), when, when)
		}
		_, counts, reported := claudeTurnCounts(out)
		if want := []Counts{{"claude-opus-5", [4]int64{2, 0, 0, 100}}}; !reported || !reflect.DeepEqual(counts, want) {
			t.Errorf("message at %s: counts %v, want %v", case_.at, counts, want)
		}
	}
}

// A line Python reads keeps its counts in a killed turn's, however its content is cut: a lone
// surrogate, as from an emoji cut in half, is no reason to lose the message.
func TestAKilledTurnCountsALineHoldingALoneSurrogate(t *testing.T) {
	line := `{"type":"assistant","timestamp":"2026-11-05T09:00:05.000Z","message":{"id":"msg_acme",` +
		`"model":"claude-opus-5","content":[{"type":"text","text":"cut \ud83d"}],"usage":{"input_tokens":2,"output_tokens":OUT}}}` + "\n"
	for _, case_ := range []struct {
		transcript bool
		want       [4]int64
	}{{true, [4]int64{2, 0, 0, 100}}, {false, [4]int64{2, 0, 0, 1}}} {
		home := t.TempDir()
		t.Setenv("HOME", home)
		out := filepath.Join(home, "turn")
		os.MkdirAll(out, 0o700)
		write := func(path, text string) {
			os.MkdirAll(filepath.Dir(path), 0o700)
			if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
				t.Fatal(err)
			}
		}
		write(filepath.Join(out, "harness"), "claude")
		write(filepath.Join(out, "events.jsonl"), `{"type":"system","subtype":"init","cwd":"/acme/widgets","session_id":"session-acme"}`+"\n"+
			strings.Replace(line, "OUT", "1", 1))
		if case_.transcript {
			sources := claudeTokenSources(run.Fields("cwd", "/acme/widgets", "conversation", "session-acme"))
			write(sources[0], strings.Replace(line, "OUT", "100", 1))
		}
		// the turn ran from a second before the transcript's line to a second after it
		for name, at := range map[string]string{"harness": "2026-11-05T09:00:04Z", "events.jsonl": "2026-11-05T09:00:06Z"} {
			when, _ := time.Parse(time.RFC3339, at)
			os.Chtimes(filepath.Join(out, name), when, when)
		}
		_, counts, reported := claudeTurnCounts(out)
		if want := []Counts{{"claude-opus-5", case_.want}}; !reported || !reflect.DeepEqual(counts, want) {
			t.Errorf("transcript %v: counts %v, want %v", case_.transcript, counts, want)
		}
	}
}
