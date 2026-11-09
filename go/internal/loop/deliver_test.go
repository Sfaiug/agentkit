package loop

import "testing"

// The delivery lock is the file Python's merge_lock takes: each clone spelling names the key
// Python's remote_key gives it.
func TestARepositoryIsOneDeliveryLockHoweverItsCloneSpellsIt(t *testing.T) {
	for url, key := range map[string]string{
		"git@github.com:acme/widget.git":      "github.com/acme/widget",
		"ssh://git@github.com:22/acme/widget": "github.com/acme/widget",
		"https://github.com/Acme/widget":      "github.com/acme/widget",
		"/home/x/remotes/acme/widgets.git":    "/home/x/remotes/acme/widgets.git",
		"ssh://h//x":                          "h/x",
		"file:///srv/r.git":                   "file:///srv/r.git",
		`C:\r\x`:                              `c/\r\x`,
	} {
		if got := RemoteKey(url); got != key {
			t.Errorf("%s: %s, not %s", url, got, key)
		}
	}
}

// A final check's red is said as its first failing command and the line saying what failed.
func TestAFinalCheckRedNamesItsFirstFailure(t *testing.T) {
	text := "$ true\n[exit 0]\n\n$ make test\n[exit 2]\nok 1\nFAIL test_api\nsummary\n\n$ lint\n[exit 1]\nbad"
	if got := firstFailure(text); got != "`make test` \u2014 FAIL test_api" {
		t.Fatal(got)
	}
}
