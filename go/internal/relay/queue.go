//go:build unix

package relay

import (
	"io"
	"sync"
)

// limit is a ceiling on the bytes queued each way, not on throughput: a slow writer backs up its
// reader, and a faster one takes what was read as soon as it is.
const limit = 64 << 10

// A queue holds the bytes read one way until they are written: one goroutine fills it and one
// empties it.
type queue struct {
	mu      sync.Mutex
	moved   *sync.Cond
	pending []byte
	ended   bool // nothing more comes in
	stuck   bool // nothing more goes out
}

func newQueue() *queue {
	q := &queue{}
	q.moved = sync.NewCond(&q.mu)
	return q
}

// fill queues what read reads, reading only while the queue is not full, until read fails or
// nothing more goes out; it answers read's error.
func (q *queue) fill(read func([]byte) (int, error)) error {
	buffer := make([]byte, limit)
	for {
		q.mu.Lock()
		for len(q.pending) == limit && !q.stuck {
			q.moved.Wait()
		}
		room, stuck := limit-len(q.pending), q.stuck
		q.mu.Unlock()
		if stuck {
			return nil
		}
		n, err := read(buffer[:room])
		q.put(buffer[:n])
		if err != nil {
			return err
		}
	}
}

func (q *queue) put(data []byte) {
	q.mu.Lock()
	q.pending = append(q.pending, data...)
	q.mu.Unlock()
	q.moved.Broadcast()
}

// end says nothing more comes in.
func (q *queue) end() {
	q.mu.Lock()
	q.ended = true
	q.mu.Unlock()
	q.moved.Broadcast()
}

// empty writes what is queued to w until the queue has ended and is empty, or a write fails,
// after which nothing more goes out; it answers that write's error.
func (q *queue) empty(w io.Writer) error {
	for {
		q.mu.Lock()
		for len(q.pending) == 0 && !q.ended {
			q.moved.Wait()
		}
		next := q.pending // fill only appends past it
		q.mu.Unlock()
		if len(next) == 0 {
			return nil
		}
		n, err := w.Write(next)
		q.mu.Lock()
		q.pending, q.stuck = q.pending[n:], err != nil
		q.mu.Unlock()
		q.moved.Broadcast()
		if err != nil {
			return err
		}
	}
}
