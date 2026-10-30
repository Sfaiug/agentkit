package launch

import "testing"

// Git's bytes that are no UTF-8 read as Python's errors="replace" reads them, a branch named
// in Latin-1 among them.
func TestReplacedDecodesAsPython(t *testing.T) {
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
		if got := replaced(text); got != want {
			t.Errorf("%q: got %q, want %q", text, got, want)
		}
	}
}
