package usage

import (
	"testing"

	"agentkit/internal/run"
)

// Python's mark_exhausted: the refusal's own moment, else the provider's next window, an hour at
// most where no meter shows the refusal, and every later read finds the mark in the snapshot.
func TestAMarkIsTheRefusalsMomentElseItsWindowAtMostAnHour(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if took := MarkExhausted("acme", "", clock()+500); took-clock() > 500 || took-clock() < 400 {
		t.Fatalf("the moment named: %v from now", took-clock())
	}
	marked := cachedProvider("acme")
	if !marked.Has("exhausted_until") || !marked.Has("exhausted_at") || !marked.Has("exhausted_ends") || marked.Get("exhausted_by") != nil {
		t.Fatalf("the mark: %s", run.Line(marked))
	}
	if took := MarkExhausted("acme", "", 0); took-clock() > dryFor || took-clock() < dryFor-100 {
		t.Fatalf("nothing named, no meter: %v from now", took-clock())
	}
}

func TestTheNextWindowIsTheSoonestStillToRollOver(t *testing.T) {
	prov := fields("meters", []any{fields("name", "old", "resets_at", 5.0), fields("name", "late", "resets_at", 90.0), fields("name", "soon", "resets_at", 20.0)})
	if at := nextWindow(prov, 10); at != 20 {
		t.Fatalf("soonest: %v", at)
	}
	if at := nextWindow(run.NewObject(), 10); at != 10+dryFor {
		t.Fatalf("no window: %v", at)
	}
}

// An account's mark is its own (usage._patch with an account): the provider's record keeps none.
func TestAnAccountsMarkParksThatLoginAlone(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	MarkExhausted("acme", "shoal", clock()+500)
	marked := cachedProvider("acme")
	if marked.Has("exhausted_until") || !object(marked.Dict("accounts").Get("shoal")).Has("exhausted_until") {
		t.Fatalf("the mark: %s", run.Line(marked))
	}
}
