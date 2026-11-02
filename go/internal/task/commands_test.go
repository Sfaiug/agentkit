package task

import (
	"slices"
	"testing"
)

func TestARoundsCommandsAreTheTasksWithoutALanding(t *testing.T) {
	got := RoundCommands([]string{"a", "b  # once"}, "suite", false)
	if want := []string{"a", "b"}; !slices.Equal(got, want) {
		t.Fatalf("got %v", got)
	}
}

func TestALandingRunsTheDeclaredSuiteOnceHoweverTheTaskNamesIt(t *testing.T) {
	suite := "make test 2>&1 | tee log"
	got := RoundCommands([]string{"a", "make  test", "make test 2>&1 | tee log  # once", "other  # once"}, suite, true)
	if want := []string{"a", "other  # once", suite + "  # once"}; !slices.Equal(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	every, once := Group(got)
	if !slices.Equal(every, []string{"a"}) || !slices.Equal(once, []string{"other", suite}) {
		t.Fatalf("every %v once %v", every, once)
	}
	if plain := RoundCommands([]string{"a"}, "", true); !slices.Equal(plain, []string{"a"}) {
		t.Fatalf("got %v", plain)
	}
}

func TestPlumbingInsideQuotesOrASubstitutionIsTheCommandsOwn(t *testing.T) {
	for cmd, want := range map[string]string{
		"make test | tee x": "make test ",
		"run 'a|b'; next":   "run 'a|b'",
		"run $(a | b) && c": "run $(a | b) ",
		"plain":             "plain",
		`say "x;y" 2>&1`:    `say "x;y" `,
	} {
		if got := firstCommand(cmd); got != want {
			t.Errorf("%q: got %q, want %q", cmd, got, want)
		}
	}
}
