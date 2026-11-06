package features

import (
	"os"
	"path/filepath"
	"testing"

	record "agentkit/internal/run"
)

// A stamp reads as the moment Python's fromisoformat makes of it, a time with no offset as UTC;
// one Go cannot read as Python does is ErrStamp, and a row off for everyone, or unstamped, has none.
func TestAStampReadsAsPythonsMoment(t *testing.T) {
	for _, each := range []struct {
		row   string
		micro int64 // the epoch Python's timestamp() gives, in microseconds
		on    bool
		err   error
	}{
		{`{"everyone": true, "everyone_since": "2026-10-20T12:00:00Z"}`, 1792497600_000000, true, nil},
		{`{"everyone": true, "everyone_since": "2026-10-20 12:00:00.1234567+05:30"}`, 1792477800_123456, true, nil},
		{`{"everyone": true, "everyone_since": "2026-10-20T12:00-01:00"}`, 1792501200_000000, true, nil},
		{`{"everyone": true, "everyone_since": "2026-10-20"}`, 1792454400_000000, true, nil},
		{`{"everyone": true, "everyone_since": "2026-10-20T12:00:00.5"}`, 1792497600_500000, true, nil},
		{`{"everyone": true, "everyone_since": "2026-10-20T12:00:00+0000"}`, 1792497600_000000, true, nil},
		{`{"everyone": true, "everyone_since": "2026-10-20 12:00:00,1234567-0130"}`, 1792503000_123456, true, nil},
		{`{"everyone": true, "everyone_since": "2026-10-20T12:00+0530"}`, 1792477800_000000, true, nil},
		{`{"everyone": true, "everyone_since": "2026-02-30T00:00:00Z"}`, 0, false, ErrStamp},
		{`{"everyone": true, "everyone_since": "2026-10-20T24:00:00Z"}`, 0, false, ErrStamp},
		{`{"everyone": true, "everyone_since": "yesterday"}`, 0, false, ErrStamp},
		{`{"everyone": true, "everyone_since": null}`, 0, false, nil},
		{`{"everyone": false, "everyone_since": "2026-10-20T12:00:00Z"}`, 0, false, nil},
	} {
		value, _ := record.Decode([]byte(each.row))
		at, on, err := Since(value.(*record.Object))
		if on != each.on || err != each.err || on && at.UnixMicro() != each.micro {
			t.Errorf("%s: read %v %v %v", each.row, at, on, err)
		}
	}
}

// A switch's check reads the list the check's environment gives, not ak's own, and leaves a stamp
// Go cannot read to the check as written, where Python ak reads it.
func TestASwitchCheckReadsTheListItsEnvironmentGives(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("ROWS", `[{"id": "fast-search", "everyone": true}]`)
	tree := t.TempDir()
	if err := os.WriteFile(filepath.Join(tree, "features.sh"), []byte(`printf '%s' "$ROWS"`), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(tree, "AGENTS.md"), []byte("---\nfeatures: sh features.sh\n---\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	for _, each := range []struct {
		rows         string
		proven       bool
		passed, ours bool
	}{
		{`[]`, true, true, true},
		{`[{"id": "fast-search", "everyone": false}]`, true, false, true},
		{`[{"id": "fast-search", "everyone": true, "everyone_since": null}]`, false, false, true},
		{`[{"id": "fast-search", "everyone": true, "everyone_since": "2026-10-20T12:00:00Z"}]`, false, true, true},
		{`[{"id": "fast-search", "everyone": true, "everyone_since": "yesterday"}]`, false, false, false},
	} {
		passed, ours := Checked(tree, Check("fast-search", each.proven), append(os.Environ(), "ROWS="+each.rows))
		if passed != each.passed || ours != each.ours {
			t.Errorf("%s, proven %v: passed %v, ours %v", each.rows, each.proven, passed, ours)
		}
	}
}
