package loop

import (
	"context"
	"io"

	"agentkit/internal/gitcall"
	"agentkit/internal/host"
)

// A besideReview is a check run beside the review, Python's beside_review: started with the
// review, so the review never waits on it, and joined before its result is recorded.  It runs on a
// loop of its own, whose stop is the check's alone and whose marker every process it starts
// carries, its boxes' and its gits' (l.git) and theirs: nothing of it outlives it.  A review that
// ends otherwise drops it, stopping its processes and waiting for them, and adopts nothing, so a
// resume starts it again.
type besideReview struct {
	stop    context.CancelFunc
	marker  string
	done    chan struct{}
	why     string
	err     error
	failure any // the check's panic, raised again where it is joined, which the driver answers
}

// besideReview starts check, under the name its processes are marked by, beside what the caller
// does next.
func (l *loop) besideReview(name string, check func(*loop) (string, error)) *besideReview {
	ctx, stop := context.WithCancel(l.ctx)
	own := *l
	own.ctx, own.marker = ctx, l.dir+"/"+name
	b := &besideReview{stop: stop, marker: own.marker, done: make(chan struct{})}
	go func() {
		defer close(b.done)
		defer func() { b.failure = recover() }()
		defer host.EndMarked(own.marker, io.Discard)
		b.why, b.err = check(&own)
	}()
	return b
}

// join waits for the check to end, and is what it found.
func (b *besideReview) join() (string, error) {
	<-b.done
	if b.failure != nil {
		panic(b.failure)
	}
	return b.why, b.err
}

// drop stops the check and its processes, a git's filter holding its output too, and waits for
// them to end, one joined or nil already being done.
func (b *besideReview) drop() {
	if b != nil {
		b.stop()
		host.EndMarked(b.marker, io.Discard)
		<-b.done
	}
}

// git is git in repo with env changed, stopped with the loop and carrying its marker: a check
// dropped beside the review waits on none of its own.
func (l *loop) git(repo string, env ...string) gitcall.Git {
	if l.marker != "" {
		env = append(env, host.Marker+"="+l.marker)
	}
	return gitcall.Git{Repo: repo, Env: env, Ctx: l.ctx}
}
