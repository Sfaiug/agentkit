package notify

import "io"

// Failed is ak's own failure about a seat, a recovery it could not carry out (watch.revive_seats'
// shaped): recorded once for its event, kept as Needs keeps a notice, and carded as Needs cards a
// question, on the seat's word as `asked` reads it with the notice standing.  A failure is no
// question: its card goes out with its own text, whoever is in the seat.
func Failed(name, text, source string, kept bool, asked Asked, errOut io.Writer) (bool, error) {
	return needs(name, text, source, kept, true, asked, errOut)
}
