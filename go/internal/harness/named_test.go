package harness

import "testing"

// A harness whose own evidence names its seats' conversations says, as strictly as Named answers,
// whether it named one yet: its owned, which takes a failure on the way for none, never decides.
func TestEveryHarnessReadingItsOwnEvidenceAnswersNamed(t *testing.T) {
	for name, own := range plugins {
		if own.owned != nil && own.named == nil {
			t.Errorf("%s has owned and no named", name)
		}
	}
}
