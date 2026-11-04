package hooks

import "testing"

// Each want is what Python's difflib.unified_diff(a, b, "held", "now", n=1) answers.
func TestUnifiedDiffIsPythons(t *testing.T) {
	a := []string{"0\n", "1\n", "2\n", "3\n", "4\n", "5\n", "6\n", "7\n", "8\n", "9\n", "10\n", "11\n"}
	b := append([]string{"0\n", "one\n"}, a[2:9]...)
	b = append(b, "10\n", "11\n", "end")
	if got, want := unifiedDiff(a, b, "held", "now", 1), "--- held\n+++ now\n@@ -1,3 +1,3 @@\n 0\n-1\n+one\n 2\n@@ -9,4 +9,4 @@\n 8\n-9\n 10\n 11\n+end"; got != want {
		t.Errorf("two hunks:\n%q\nwant\n%q", got, want)
	}
	// a line making up more than 1% of 200 or more starts no match, however long the run of it
	same := make([]string, 250)
	for i := range same {
		same[i] = "same\n"
	}
	other := append(append([]string{}, same[:249]...), "other\n")
	if got, want := unifiedDiff(same, other, "held", "now", 1), "--- held\n+++ now\n@@ -249,2 +249,2 @@\n same\n-same\n+other\n"; got != want {
		t.Errorf("autojunk:\n%q\nwant\n%q", got, want)
	}
	if got := unifiedDiff(a, a, "held", "now", 1); got != "" {
		t.Errorf("no change: %q", got)
	}
}
