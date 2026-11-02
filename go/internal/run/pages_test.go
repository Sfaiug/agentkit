package run

import "testing"

// Consecutive documents are a list of pages, as Python's json_pages reads them.
func TestPagesReadsConsecutiveDocuments(t *testing.T) {
	value, err := Pages([]byte(" {\"items\": []}\n[1]\n\n"))
	if err != nil {
		t.Fatal(err)
	}
	if got := Line(value); got != `[{"items": []}, [1]]` {
		t.Errorf("read %s", got)
	}
	for _, text := range []string{"", " \n", "{} x", "\xff"} {
		if value, err := Pages([]byte(text)); err == nil {
			t.Errorf("%q read as %v", text, value)
		}
	}
}
