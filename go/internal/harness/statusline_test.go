package harness

import "testing"

func TestAListingReadsPastWhatTheStatusLineKeeps(t *testing.T) {
	for entry, kept := range map[string]bool{
		"model-conv-acme.json": true, ".model-conv-acme.x1Y2z3": true,
		"limits-conv-acme.json": true, ".limits-conv-acme.x1Y2z3": false,
		"limits-conv-acme.txt": false, "limits-conv.acme.json": false, "notes-conv-acme.json": false,
	} {
		if KeptInState(entry) != kept {
			t.Errorf("%s kept: %v", entry, !kept)
		}
	}
}
