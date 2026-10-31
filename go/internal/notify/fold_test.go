package notify

import "testing"

func TestQuestionKeyFoldsAsPython(t *testing.T) {
	for question, key := range map[string]string{
		" Which\tBRANCH?\n": "which branch?", "Straße?": "strasse?", "İ ı ſ ς": "i̇ ı s σ",
		"ﬁx ᾈ?": "fix ἀι?", "Ꭰ ꭰ ᏸ": "Ꭰ Ꭰ Ᏸ",
	} {
		if got := questionKey(question); got != key {
			t.Errorf("questionKey(%q) = %q, want %q", question, got, key)
		}
	}
}
