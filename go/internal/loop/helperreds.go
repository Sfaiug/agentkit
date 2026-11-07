package loop

import (
	"context"
	"fmt"
	"os"
)

// helperReds is what a suite does first with its pieces red on the suite helper, Python's
// run_suite: each keeps a copy of what it printed there, and the tests each named failed there
// run here alone, a piece at a time and taking no turn, as they cost what a model's own test does
// (retryTests).  One failing again settles the suite: the pieces after it keep what they printed
// there.  The helper's runner stops at its first failure, naming that one test, so passing alone
// says nothing of the tests it never reached: the whole piece then runs here and decides, a pass
// a flake of the helper (handedOn), and of the tests it named there where memory killed them alone.
// What each printed there is its first failed go (failed): one that named tests leaves its helper,
// and one that named none keeps it until it runs here whole next (pieces).
func (l *loop) helperReds(ctx context.Context, all []*piece, path string, rerun func(*piece, string, []string) error) error {
	var named, whole []*piece
	unseen := map[*piece][]string{} // the tests a piece named there that memory killed here alone
	for _, at := range all {
		if at.there == nil || at.ended.code == 0 || ctx.Err() != nil {
			continue
		}
		printed, err := os.ReadFile(at.out.Name())
		if err != nil {
			return err
		}
		// its go here takes its place in the suite's output: a copy keeps what it printed there
		kept, err := os.CreateTemp(l.dir, stem(path)+"-helper-failed-*.log")
		if err == nil {
			_, err = kept.Write(printed)
			kept.Close()
		}
		if err != nil {
			return err
		}
		l.say(fmt.Sprintf("WARN AK_SHARD=%s failed on the suite helper; what it printed there: %s", at.shard, kept.Name()))
		at.failed, at.how = printed, "failed on the suite helper "+at.there.Alias
		if len(at.ended.failed) > 0 {
			at.there = nil
			named = append(named, at)
		}
	}
	for _, at := range named {
		if ctx.Err() != nil {
			return nil
		}
		tests := at.ended.failed
		decided, err := retryTests(at, rerun)
		if err != nil {
			return err
		}
		// one killed for memory is the host's red, which says nothing of its tests: the whole piece
		// decides, as Python's run_suite runs again a piece out of memory
		if at.ended.starved {
			unseen[at] = tests
		}
		if !decided || at.ended.starved {
			whole = append(whole, at)
		} else if len(at.ended.confirmed) > 0 {
			break
		}
	}
	for _, at := range whole {
		if ctx.Err() != nil {
			return nil
		}
		if err := rerun(at, pieceRetry, nil); err != nil {
			return err
		}
		if at.ended.code == 0 {
			at.ended.flaky = append(at.ended.flaky, unseen[at]...)
		}
	}
	return nil
}
