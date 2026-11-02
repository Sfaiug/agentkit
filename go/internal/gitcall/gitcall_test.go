package gitcall

import "testing"

// Git's bytes that are no UTF-8 read as Python's errors="replace" reads them, a branch named
// in Latin-1 among them.
func TestDecodedAsPython(t *testing.T) {
	for text, want := range map[string]string{
		"z-\xff":           "z-�",
		"\xe0\x80\xbf":     "���",
		"\xed\xa0\x80":     "���",
		"\xf0\x9f\x98!":    "�!",
		"\xe2\x82":         "�",
		"a\xc3":            "a�",
		"\xf4\x90\x80\x80": "����",
		"\xc0\xaf":         "��",
		"ok \xe2\x82\xac":  "ok €",
	} {
		if got := Decoded(text); got != want {
			t.Errorf("%q: got %q, want %q", text, got, want)
		}
	}
}

func TestOnlyALostRaceForARefIsFetchedAgain(t *testing.T) {
	for out, want := range map[string]bool{
		"error: cannot lock ref 'refs/remotes/origin/a': is at 1a but expected 2b":                    true,
		"error: cannot lock ref 'refs/remotes/origin/a': Unable to create '/x/a.lock': File exists.":  true,
		"fatal: could not read from remote repository":                                                false,
		" ! [rejected] a -> origin/a (would clobber)":                                                 false,
		"error: cannot lock ref 'refs/remotes/origin/a': is at 1a but expected 2b\nfatal: went wrong": false,
		"": false,
	} {
		if got := refHeld(out); got != want {
			t.Errorf("%q: got %v", out, got)
		}
	}
}
