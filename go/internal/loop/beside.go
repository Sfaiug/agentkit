package loop

import (
	"context"

	"agentkit/internal/gitcall"
)

// A besideReview is a check run beside the review, Python's beside_review: started with the
// review, so the review never waits on it, and joined before its result is recorded.  It runs on a
// loop of its own whose stop is the check's alone, which ends its boxes and its gits (l.git): a
// review that ends otherwise drops it, stopping its processes and waiting for them, and adopts
// nothing, so a resume starts it again.
type besideReview struct {
	stop    context.CancelFunc
	done    chan struct{}
	why     string
	err     error
	failure any // the check's panic, raised again where it is joined, which the driver answers
}

// besideReview starts check beside what the caller does next.
func (l *loop) besideReview(check func(*loop) (string, error)) *besideReview {
	ctx, stop := context.WithCancel(l.ctx)
	own := *l
	own.ctx = ctx
	b := &besideReview{stop: stop, done: make(chan struct{})}
	go func() {
		defer close(b.done)
		defer func() { b.failure = recover() }()
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

// drop stops the check and waits for its processes to end, one joined or nil already being done.
func (b *besideReview) drop() {
	if b != nil {
		b.stop()
		<-b.done
	}
}

// git is git in repo with env changed, stopped with the loop: a check dropped beside the review
// waits on none of its own.
func (l *loop) git(repo string, env ...string) gitcall.Git {
	return gitcall.Git{Repo: repo, Env: env, Ctx: l.ctx}
}
