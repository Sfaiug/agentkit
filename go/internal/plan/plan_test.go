package plan

import (
	"os"
	"path/filepath"
	"testing"
)

func TestATickChangesOnlyTheBoxAndTheDone(t *testing.T) {
	where := "~/code/acme#0123456789ab · written 2026-10-20 09:00"
	for text, want := range map[string]string{
		// a check holding ` · done ` keeps it: only the done field the format parsed goes
		"- [x] x · check: `grep ' · done ' log` · " + where + " · done by hand": "x · check: `grep ' · done ' log` · " + where,
		"\x1f - [ ] y · check: `true` · " + where + " on 0123456789ab \x1f":     "y · check: `true` · " + where + " on 0123456789ab",
	} {
		line, ok := parse(text)
		if !ok || line.proven() || line.ticked("") != "- [ ] "+want || line.ticked("abc1234 fix") != "- [x] "+want+" · done abc1234 fix" {
			t.Fatalf("%q: %+v", text, line)
		}
	}
	if line, ok := parse("- [x] z · your eye · " + where); !ok || line.Check != "" {
		t.Fatalf("an eye line has no check: %+v", line)
	}
	if line, _ := parse("- [x] z · check: `true` · " + where + " · done 0123456789ab init"); !line.proven() {
		t.Fatal("a line done on a commit is proven")
	}
	if _, ok := parse("- [ ] shipped the parser"); ok {
		t.Fatal("a hand-kept line is no line ak wrote")
	}
}

func TestOnlyTheRunningLaunchsTurnCountsAReachOfTheLiveHost(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("USERPROFILE", os.Getenv("HOME"))
	state := filepath.Join(os.Getenv("HOME"), ".agentkit", "state")
	put := func(name, text string) {
		if err := os.MkdirAll(state, 0o700); err != nil || os.WriteFile(filepath.Join(state, name), []byte(text), 0o600) != nil {
			t.Fatal(name)
		}
	}
	put("session-acme.json", `{}`)
	put("stop-acme.json", `{"turn": 100}`)
	if reachedLive("acme") {
		t.Fatal("no reach is no reach")
	}
	put("live-acme.txt", "101.5\n")
	if !reachedLive("acme") {
		t.Fatal("a reach since the turn began counts")
	}
	// renamed into acme, its harness still writes under the old name, whose turn is the newer
	put("session-old.json", `{"renamed": "acme"}`)
	put("stop-old.json", `{"turn": 200}`)
	if reachedLive("acme") {
		t.Fatal("a reach before the running launch's turn counts not")
	}
	put("live-old.txt", "200")
	if !reachedLive("acme") {
		t.Fatal("the running launch's reach counts")
	}
}
