package cli

import (
	"reflect"
	"slices"
	"testing"
)

func TestCharacterNameWithNoneFree(t *testing.T) {
	held := []string{}
	taken := func(name string) (bool, bool) {
		return slices.Contains(characters, name) || slices.Contains(held, name), true
	}
	if got := characterName(taken); got != "unnamed" {
		t.Errorf("every character taken: %q", got)
	}
	held = []string{"unnamed", "unnamed-2"}
	if got := characterName(taken); got != "unnamed-3" {
		t.Errorf("`unnamed` taken too: %q", got)
	}
	free := func(name string) (bool, bool) { return false, name == "rex" }
	if got := characterName(free); got != "rex" {
		t.Errorf("a name only Python could call free was taken: %q", got)
	}
}

func TestWorkersNamed(t *testing.T) {
	names := []string{"opus", "spark", "astra"}
	for answer, want := range map[string][]string{
		"ALL": names, "2": {"spark"}, "Spark, 1": {"spark", "opus"}, "3 opus": {"astra", "opus"},
		"4": nil, "+1": nil, "nosuch": nil, "opus 1": nil, "opus,opus": nil, ",": nil,
	} {
		if got := workersNamed(answer, names); !reflect.DeepEqual(got, want) {
			t.Errorf("%q: %v, want %v", answer, got, want)
		}
	}
}
