package launch

// pastStall decides the run stalled first in line, Python's gate._host_admits on a stall: only
// the host's strain holds it (host.Strain); it goes past every other gate, slot_stall naming the
// one that held it.  The gates derived from those readings were retuned again and again, and one
// held every run for 22 hours of a calm host.
func (a *admission) pastStall(r *room) {
	if a.reason, a.kind = r.readings.Strain(r.minimum); a.reason != "" {
		return
	}
	if a.gates(r); !a.in {
		a.in, a.stall = true, "went in on a stall, past: "+a.reason
	}
}
