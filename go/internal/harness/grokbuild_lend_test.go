package harness

import "testing"

func TestGrokEndsReadsEveryFormLendReads(t *testing.T) {
	for _, form := range []string{"2099-10-28T17:36:12Z", "2099-10-28T17:36:12.123456789Z",
		"2099-10-28T12:36:12-05:00", "2099-10-28T12:36:12-0500", "2099-10-28T23:06:12.5+05:30",
		"2099-10-28T23:06:12+0530", "2099-10-28T23:06:12.5+0530"} {
		if ends, ok := grokEnds(form); !ok || ends != 4096892172 {
			t.Fatalf("grokEnds(%q) = %d, %t, want 4096892172", form, ends, ok)
		}
	}
}
