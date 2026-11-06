package harness

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestOpenCodeReadsAReportedSessionWhereItCanReadItsDatabase(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("XDG_DATA_HOME", filepath.Join(home, "share"))
	t.Setenv("OPENCODE_DB", "opencode.db")
	token := strings.Repeat("a", 32)
	path := filepath.Join(home, ".agentkit", "state", "opencode-launch-"+token, "session")
	record := run.NewObject()
	record.Set("conversation", "legacy")
	record.Set("id_source", "launcher")
	record.Set("resumable", true)
	check := func(ready bool) {
		t.Helper()
		before := run.Encode(record)
		if _, known := For("opencode").Reconciled("acme", record); known != ready || run.Encode(record) != before {
			t.Fatalf("readiness differs or record changed: %s, ready=%v", run.Encode(record), known)
		}
	}
	check(true) // an older launch with no receipt
	record.Set("opencode_launch", token)
	check(true) // a receipt not made yet
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	check(true) // prepare made the directory, but its plugin has reported nothing
	for session, ready := range map[string]bool{
		"": true, "ses_": true, "--session": true, "ses_a/b": true, "ses_a\nses_b": true,
		"ses_A012z": true, " \u0085ses_A012z\n": true, // no database yet: no turn to read
	} {
		if err := os.WriteFile(path, []byte(session), 0o600); err != nil {
			t.Fatal(err)
		}
		check(ready)
	}
	if err := os.WriteFile(path, []byte("ses_A012z"), 0o600); err != nil {
		t.Fatal(err)
	}
	record.Set("conversation", "ses_A012z")
	database := filepath.Join(home, "share", "opencode", "opencode.db")
	for name, data := range map[string]string{database: "pages", database + "-wal": "pages it has yet to take in"} {
		if err := os.MkdirAll(filepath.Dir(name), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(name, []byte(data), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	check(false) // its database being written into is Python's to read
	record.Set("opencode_launch", "../"+token)
	check(true) // not a receipt token, as Python's path_for decides
}

func TestOpenCodeReadsASessionsLastTurnAsPythonDoes(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("XDG_DATA_HOME", filepath.Join(home, "share"))
	t.Setenv("OPENCODE_DB", "opencode.db")
	// testdata/opencode.db is OpenCode 2.2.3's session_message as Python's sqlite3 writes it:
	// ses_Free asked, answered on opencode/m-free at high and failed on the free limit at 1000 ms,
	// 500 ms to wait; ses_Again's rows in no seq order, failed, prompted again since, and its
	// answer at OpenCode's default effort.
	data, err := os.ReadFile("testdata/opencode.db")
	if err != nil {
		t.Fatal(err)
	}
	for name, data := range map[string][]byte{filepath.Join(home, "share", "opencode", "opencode.db"): data} {
		if err := os.MkdirAll(filepath.Dir(name), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(name, data, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	token := strings.Repeat("b", 32)
	record := run.Fields("opencode_launch", token)
	type read struct {
		said              string
		ended             bool
		model, effort, at any
		answered          bool
	}
	for session, want := range map[string]read{
		"ses_Free": {"Error: provider.free-limit 429 Free usage limit reached. try again at 1970-01-01T00:00:01.500+00:00", true,
			"opencode/m-free", "high", run.Float(0.999), true},
		"ses_Again": {"", true, "opencode/m", nil, run.Float(1.5), true},
		"ses_None":  {},
	} {
		path := filepath.Join(home, ".agentkit", "state", "opencode-launch-"+token, "session")
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(session), 0o600); err != nil {
			t.Fatal(err)
		}
		reader, ready := For("opencode").Reconciled("acme", record)
		var got read
		got.said, got.ended = reader.RecordedError(record)
		got.model, got.effort, got.at, got.answered = reader.LastAnswer(record)
		if resumable, known := reader.Resumable(record); !ready || got != want || !resumable || !known {
			t.Errorf("%s: %+v, resumable %v", session, got, resumable)
		}
		if said, ended := reader.RecordedError(run.Fields("opencode_launch", strings.Repeat("c", 32))); said != "" || ended {
			t.Errorf("%s: another launch's record read this session's", session)
		}
	}
}
