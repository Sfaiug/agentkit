package tmux

import (
	"slices"
	"testing"
)

// A call is a UTF-8 client once the first of LC_ALL, LC_CTYPE and LANG that is set names UTF-8,
// as tmux reads its locale, and asks with -u otherwise.
func TestUTF8FollowsTheFirstLocaleSet(t *testing.T) {
	for _, each := range []struct {
		all, ctype, lang string
		flag             []string
	}{
		{"", "", "C.UTF-8", nil},
		{"", "en_US.utf8", "C", nil},
		{"C", "", "C.UTF-8", []string{"-u"}},
		{"", "", "", []string{"-u"}},
	} {
		t.Setenv("LC_ALL", each.all)
		t.Setenv("LC_CTYPE", each.ctype)
		t.Setenv("LANG", each.lang)
		if got := utf8(); !slices.Equal(got, each.flag) {
			t.Errorf("LC_ALL=%q LC_CTYPE=%q LANG=%q: %q, want %q", each.all, each.ctype, each.lang, got, each.flag)
		}
	}
}
