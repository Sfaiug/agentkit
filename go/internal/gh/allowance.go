package gh

import (
	"time"

	"agentkit/internal/run"
)

// floor is how long a run waits before it asks a spent allowance again: a reset that looks past
// while GitHub still counts the allowance spent is a clock apart from GitHub's.
const floor = time.Minute

// serving is the run this process drives, as Python's run context names it: say writes a line of
// its log, and wait sleeps out a wait with its record saying until when.  Both are nil in a
// process that drives none.
var serving struct {
	say  func(string)
	wait func(time.Duration) error
}

// Serve makes this process's gh calls those of the run that says and waits with these, until
// the func it answers is called.
func Serve(say func(string), wait func(time.Duration) error) func() {
	serving.say, serving.wait = say, wait
	return func() { serving.say, serving.wait = nil, nil }
}

// call is ask, except that a run's call failing while GitHub counts its API allowance spent waits
// for the reset and asks again, for as long as GitHub says spent, as Python's gitcall.gh: on
// 26 Oct 2026 a review that had passed ended in error, unable to read its PR to post the verdict.
// It says so once per reset.  A call that serves no run, the tick's among them, never waits: the
// tick asks again next tick.
func call(dir string, args []string) (int, string, string, string, error) {
	said := 0.0
	for {
		code, out, errOut, why, err := ask(dir, args)
		if code == 0 || why != "" || err != nil || serving.wait == nil {
			return code, out, errOut, why, err
		}
		reset, spent := allowanceReset(dir)
		if !spent {
			return code, out, errOut, why, err
		}
		if reset != said {
			serving.say("waiting for GitHub's API allowance until " + time.Unix(int64(reset), 0).UTC().Format("15:04") + " UTC")
			said = reset
		}
		if err := serving.wait(max(floor, time.Duration((reset-now())*float64(time.Second)))); err != nil {
			return 0, "", "", "", err
		}
	}
}

// now is the time in seconds, as Python's time.time.
func now() float64 { return float64(time.Now().UnixNano()) / 1e9 }

// allowanceReset is when the spent allowance comes back: the later reset of `core` and `graphql`
// among those with none left, read off GitHub's own count, which spends none of it, never off
// gh's words.  Every gh command spends one or both, and which is not mapped: a failure of another
// cause while one is spent waits for its reset once, then fails as before.  None spent, or no
// count to read, is not spent.
func allowanceReset(dir string) (float64, bool) {
	code, out, _, why, err := ask(dir, []string{"api", "rate_limit"})
	if code != 0 || why != "" || err != nil {
		return 0, false
	}
	value, _ := run.Decode([]byte(out))
	answer, _ := value.(*run.Object)
	if answer == nil || answer.Dict("resources") == nil {
		return 0, false
	}
	counts := answer.Dict("resources")
	latest, spent := 0.0, false
	for _, name := range []string{"core", "graphql"} {
		count := counts.Dict(name)
		if count == nil || !count.Has("remaining") {
			return 0, false
		}
		if left, number := count.Num("remaining"); !number || left != 0 {
			continue
		}
		reset, ok := count.Num("reset")
		if !ok {
			return 0, false
		}
		latest, spent = max(latest, reset), true
	}
	return latest, spent
}
