package host

import (
	"os"
	"os/exec"
	"runtime"
	"testing"
	"time"
)

func TestACommandInsideTheTimeItGaveIsDeclared(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("no process is found by its environment here")
	}
	marker := "/acme/" + t.Name() // a path, as every run's marker is
	cmd := exec.Command("timeout", "60", "sleep", "60")
	cmd.Env = append(os.Environ(), Marker+"="+marker)
	if err := cmd.Start(); err != nil {
		t.Skip(err)
	}
	defer func() {
		cmd.Process.Kill()
		cmd.Wait()
	}()
	now := float64(time.Now().UnixNano()) / 1e9
	for late := time.Now().Add(30 * time.Second); !Declared(marker)(now) && time.Now().Before(late); {
		time.Sleep(10 * time.Millisecond)
	}
	if !Declared(marker)(now) {
		t.Fatal("inside its 60 seconds")
	}
	if Declared(marker)(now + 61) {
		t.Fatal("past its 60 seconds")
	}
	if Declared("")(now) {
		t.Fatal("no marker declares nothing: every run's processes are below an empty one")
	}
}

func TestTimeoutSecondsReadsWhatTimeoutWasGiven(t *testing.T) {
	for _, each := range []struct {
		argv []string
		want float64
	}{
		{[]string{"timeout", "30", "make"}, 30},
		{[]string{"/usr/bin/timeout", "2m", "make"}, 120},
		{[]string{"timeout", "-k", "5", "--signal", "KILL", "1.5h", "make"}, 5400},
		{[]string{"timeout", "--preserve-status", "--", "1d", "make"}, 86400},
		{[]string{"timeout", "soon", "make"}, 0},
		{[]string{"make", "30"}, 0},
		{nil, 0},
	} {
		if got := TimeoutSeconds(each.argv); got != each.want {
			t.Errorf("%q: got %g, want %g", each.argv, got, each.want)
		}
	}
}
