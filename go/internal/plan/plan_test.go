package plan

import "testing"

func TestATickChangesOnlyTheBoxAndTheDone(t *testing.T) {
	where := "~/code/acme#0123456789ab · written 2026-10-20 09:00"
	for text, want := range map[string]string{
		// a check holding ` · done ` keeps it: only the done field the format parsed goes
		"- [x] x · check: `grep ' · done ' log` · " + where + " · done by hand": "x · check: `grep ' · done ' log` · " + where,
		"  - [ ] y · check: `true` · " + where + " on 0123456789ab  ":           "y · check: `true` · " + where + " on 0123456789ab",
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
