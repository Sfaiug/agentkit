package run
import ("os"; "os/exec"; "path/filepath"; "testing")
func TestReviewLateLookTiming(t *testing.T) {
    originalGroup, originalReap := group, reap
    t.Cleanup(func() { group, reap = originalGroup, originalReap })
    group = func(cmd *exec.Cmd) func() {
        cmd.Args[2] += "; exec >/dev/null 2>&1; while [ ! -f release ]; do sleep .01; done"
        return originalGroup(cmd)
    }
    foundRunning := false
    reap = func(cmd *exec.Cmd, wait bool) (bool, int, error) {
        if wait {
            ended, code, err := originalReap(cmd, false)
            if ended || err != nil { return ended, code, err }
            foundRunning = true
            if err := os.WriteFile(filepath.Join(cmd.Dir, "release"), nil, 0600); err != nil { t.Fatal(err) }
        }
        return originalReap(cmd, wait)
    }
    if t.Run("existing_test", TestAShellEndedBeforeTheDeadlineHasAnsweredWhenTheLookComesAfter) && foundRunning {
        t.Fatal("late-look test accepted a shell still running at the final nonblocking check")
    }
}
