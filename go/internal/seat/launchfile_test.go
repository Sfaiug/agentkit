package seat

import (
	"os"
	"testing"
	"time"
)

func TestASeatCanBeReadBeforeItsPaneConsumesItsLaunch(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", prompting)
	_, path, err := launchFile(stateFile(home, ""), "acme", nil, []string{"true"})
	if err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	lives, known := Lives(time.Now())
	if !known || len(lives) != 1 || lives[0].Name != "acme" {
		t.Fatalf("a pending launch hid its seat: known=%v, lives=%+v", known, lives)
	}
	if after, err := os.ReadFile(path); err != nil || string(after) != string(before) {
		t.Fatalf("reading consumed the pending launch: %s, %v", after, err)
	}
}
