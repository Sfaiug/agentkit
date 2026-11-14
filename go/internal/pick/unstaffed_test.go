package pick

import "testing"

func TestUnstaffedNamesTheGroupLeftWithNobody(t *testing.T) {
	const out = "acme is not logged in"
	both := &Rules{executors: []string{"a"}, reviewers: []string{"a"}, reviewList: []string{"a"}}
	apart := &Rules{executors: []string{"a"}, reviewers: []string{"b"}, reviewList: []string{"b", "c"}}
	barred := &Rules{executors: []string{"a"}, reviewList: []string{"c"}}
	for _, each := range []struct {
		rules  *Rules
		cannot map[string]string
		want   string
	}{
		{both, map[string]string{"a": out}, "none of the workers a and reviewers a can run here (a: acme is not logged in); log in to another harness or add another model to the groups"},
		{both, map[string]string{}, ""},
		{apart, map[string]string{"b": out}, "none of the reviewers b, c can run here (b: acme is not logged in); log in to another harness or add another model to the groups"},
		{apart, map[string]string{"a": out}, "none of the workers a can run here (a: acme is not logged in); log in to another harness or add another model to the groups"},
		{barred, map[string]string{"a": out}, ""},
		// review off asks for no reviewer, and names every model that cannot run
		{apart.Alone(), map[string]string{"b": out}, ""},
		{barred.Alone(), map[string]string{"a": out, "c": out}, "none of the workers a can run here (a: acme is not logged in; c: acme is not logged in); log in to another harness or add another model to the groups"},
	} {
		if got := each.rules.Unstaffed(each.cannot); got != each.want {
			t.Errorf("%v of %v: %q, want %q", each.cannot, each.rules.reviewList, got, each.want)
		}
	}
}
