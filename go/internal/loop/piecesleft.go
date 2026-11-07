package loop

import (
	"slices"
	"sync"

	"agentkit/internal/helper"
)

// piecesLeft are a suite's pieces not yet run, Python's _Pieces: each place, a place here or a VM
// there, takes the next waiting one as it frees.  One a machine lost goes back to the head of the
// line, for any place but the VMs of the suite there that lost it, and the go that runs it next
// counts.
type piecesLeft struct {
	held    sync.Mutex
	freed   sync.Cond
	waiting []*piece
	out     int                       // taken and not yet ended
	lost    map[*piece][]*helper.Away // by piece, the suites there that lost it
}

func leftOf(all []*piece) *piecesLeft {
	left := &piecesLeft{waiting: slices.Clone(all), lost: map[*piece][]*helper.Away{}}
	left.freed.L = &left.held
	return left
}

// next is the piece a place takes next, nil once none may come to it: a VM there takes the first
// waiting one its suite there never lost, and a place here with none waiting waits while any is
// out, as one may come back.
func (p *piecesLeft) next(there *helper.Away) *piece {
	p.held.Lock()
	defer p.held.Unlock()
	for there == nil && len(p.waiting) == 0 && p.out > 0 {
		p.freed.Wait()
	}
	for i, at := range p.waiting {
		if !slices.Contains(p.lost[at], there) {
			p.waiting = slices.Delete(p.waiting, i, i+1)
			p.out++
			return at
		}
	}
	return nil
}

// done ends a piece a place took, one lost on the suite there where it ran given back.
func (p *piecesLeft) done(at *piece, lost bool) {
	p.held.Lock()
	defer p.held.Unlock()
	p.out--
	if lost {
		p.waiting = slices.Insert(p.waiting, 0, at)
		p.lost[at] = append(p.lost[at], at.there)
	}
	p.freed.Broadcast()
}

// waits is how many pieces wait.
func (p *piecesLeft) waits() int {
	p.held.Lock()
	defer p.held.Unlock()
	return len(p.waiting)
}

// over is whether no piece waits or runs.
func (p *piecesLeft) over() bool {
	p.held.Lock()
	defer p.held.Unlock()
	return len(p.waiting) == 0 && p.out == 0
}
