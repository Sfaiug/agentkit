package notify

import (
	"io"

	"agentkit/internal/run"
)

// TurnedGoneNeed cards the needs you of a seat nobody is in that no notice asks, a plan owing a
// line say, as notify.transition does for a closed seat: its card begins when the seat went and
// goes out with the seat's reason once it has stood a minute.
func TurnedGoneNeed(name string, said func(string) (string, any), errOut io.Writer) (bool, error) {
	return questionTransition(name, said, clock, cardWait, errOut, nil, goneNeed, func(string) error { return nil })
}

// goneNeed is the notice a gone seat's needs you stands for, asked at no moment of its own; none
// where a notice stands or the seat is there.
func goneNeed(name string, file *run.Object) *run.Object {
	if Last(name) != nil {
		return nil
	}
	if _, _, gone, known := questionActivity(name); !known || !gone {
		return nil
	}
	return run.Fields("text", file.Str("reason"))
}
