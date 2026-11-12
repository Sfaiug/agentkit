package loop

import (
	"slices"
	"sync"

	"agentkit/internal/helper"
)

// piecesLeft are a suite's pieces not yet run, Python's _Pieces: each place, a place here or a VM
// there, takes the next waiting one as it frees.  One a machine gave back goes back to the head of
// the line: one it lost for any place but the VMs of the suite there that lost it, one it had no
// room to start for any place, and the go that runs it next counts.
type piecesLeft struct {
	held    sync.Mutex
	freed   sync.Cond
	waiting []*piece
	out     int                       // taken and not yet ended
	lost    map[*piece][]*helper.Away // by piece, the suites there that lost it
	vms     int                       // the VMs there taking pieces
	here    bool                      // whether places here take them
}

func leftOf(all []*piece) *piecesLeft {
	left := &piecesLeft{waiting: slices.Clone(all), lost: map[*piece][]*helper.Away{}}
	left.freed.L = &left.held
	return left
}

// open counts a VM there as it starts, before it takes a piece, so no place is missed meanwhile.
func (p *piecesLeft) open(there *helper.Away) {
	if there != nil {
		p.held.Lock()
		p.vms++
		p.held.Unlock()
	}
}

// next is the piece a place takes next, nil once none may come to it: a VM there takes the first
// waiting one its suite there never lost, and ends without one, and a place here with none waiting
// waits while any is out, as one may come back.
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
	if there != nil {
		p.vms--
	}
	return nil
}

// done ends a piece a place took, one the machine where it ran gave back (back) waiting again, and
// that VM's place ending with it.
func (p *piecesLeft) done(at *piece, back bool) {
	p.held.Lock()
	defer p.held.Unlock()
	p.out--
	if back {
		p.waiting = slices.Insert(p.waiting, 0, at)
		if helper.Lost(at.ended.code) {
			p.lost[at] = append(p.lost[at], at.there)
		}
		p.vms--
	}
	p.freed.Broadcast()
}

// waits is how many pieces wait.
func (p *piecesLeft) waits() int {
	p.held.Lock()
	defer p.held.Unlock()
	return len(p.waiting)
}

// over is whether the places take no more: no piece waits or runs, or no place is left to take one,
// where what waits goes elsewhere (placeAgain).
func (p *piecesLeft) over() bool {
	p.held.Lock()
	defer p.held.Unlock()
	return len(p.waiting) == 0 && p.out == 0 || !p.here && p.vms == 0
}

// back is whether the machine gave the piece's last go there back, lost or with no room to start
// it (helper.Back), which keeps no exit, as Python's observed: the go that runs it next counts.
func (at *piece) back() bool {
	return at.there != nil && helper.Gone(at.ended.code)
}
