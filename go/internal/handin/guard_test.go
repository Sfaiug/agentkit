package handin

import "testing"

// Each want is what Python's hand_in.exit_guard finds, "" for None.
func TestExitGuard(t *testing.T) {
	for command, want := range map[string]string{
		"2>&1 exit 0": "exit 0", "exit >x 0": "", "false || Aé=1 true": "|| true", "é=1 exit 0": "",
		`false \|| true`: "", `echo "a\"b || true"`: "", "a#b || true": "", "false || ':": "",
	} {
		if got := exitGuard(command); got != want {
			t.Errorf("exitGuard(%q) = %q, want %q", command, got, want)
		}
	}
}
