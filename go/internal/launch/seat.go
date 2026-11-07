package launch

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

// Seat is the seat this launch is a seat's own, Python's from_seat: a recorded session's, outside
// any run, by the name it goes by now, with its record; "" for none, a name with no record among
// them.  The error is config's for a name no file can have, which refuses any launch.
func Seat() (string, map[string]any, error) {
	name, record, err := queueSeat()
	if os.Getenv("AGENTKIT_RUN_DIR") != "" {
		return "", nil, err
	}
	return name, record, err
}

// queueSeat is the current session where it is a recorded one, whatever AGENTKIT_RUN_DIR says: the
// seat whose queue Python's check_seat_queue asks.
func queueSeat() (string, map[string]any, error) {
	name, record, err := config.CurrentSession()
	if _, pointer := record[config.Renamed]; err != nil || record == nil || pointer {
		return "", nil, err
	}
	return name, record, nil
}

// seated is whether a launch here is a seat's, or names a seat no file can have: Python's.
func seated() bool {
	seat, _, err := Seat()
	return seat != "" || err != nil
}

// SeatRefusal is why Python's seat_refusal refuses this launch, "" for none: a seat names no
// model, no place in the queue and no second run of a change under way, since ak decides each, and
// launches only while its plan has an open line, which its bar counts.
func SeatRefusal(values map[string]string, flags map[string]bool) string {
	seat, _, err := Seat()
	if err != nil {
		return err.Error()
	}
	if seat == "" {
		return ""
	}
	var given []string
	for _, flag := range []string{"--exec", "--review", "--anyway", "--first"} {
		if values[flag] != "" || flags[flag] {
			given = append(given, flag)
		}
	}
	if len(given) > 0 {
		return strings.Join(given, ", ") + ": not a seat's; ak picks the models, decides what goes first and refuses a second run of a change under way, so launch without"
	}
	if opened, err := plan.Opened(seat); err != nil {
		return err.Error()
	} else if !opened {
		return `your plan has no open line, and the plan is what your bar counts: first run ak plan add "<outcome>" --check '<command>'`
	}
	return ""
}

// bind is what this launch binds: a seat's own lists and efforts, which a record naming no
// executor leaves Python to refuse in its own words, else the config's.
func bind() (config.Binding, error) {
	if seat, record, _ := Seat(); seat != "" {
		return config.BindSeat(record)
	}
	return config.Bind()
}

// seatQueue is what becomes of a seat's launch once everything Python asks before its queue
// passed: refused where the seat may queue no more (seatFull), else on its way.
func seatQueue(seat string) error {
	if why := seatFull(seat, 1); why != "" {
		return &refusedOutright{why}
	}
	return nil
}

// seatFull is why that seat may not launch that many more runs, Python's gate.seat_full: a seat may
// have as many runs waiting for a slot as holding one, and always one.  It names the run to `ak
// wait` for: the one holding its slot longest, else the oldest waiting.
func seatFull(seat string, launches int) string {
	type place struct {
		since float64
		id    string
	}
	var holding, waiting []place
	for _, dir := range run.Dirs() {
		record, _ := run.Read(dir)
		// a run below another holds no slot of its own (Python's slot_place)
		if record == nil || run.Seat(record) != seat || record.Truthy("run_depth") {
			continue
		}
		switch state := record.Str("state"); {
		case state == "running" && run.ProcessActive(record):
			since, _ := record.Num("slot_started_at")
			holding = append(holding, place{since, filepath.Base(dir)})
		case state == "queued" && record.Truthy("slot_waiting"):
			waiting = append(waiting, place{firstQueued(record), filepath.Base(dir)})
		}
	}
	room := max(len(holding), 1) - len(waiting)
	if launches <= room {
		return ""
	}
	then, earliest := "launch one at a time", holding
	if len(earliest) == 0 {
		earliest = waiting
	}
	if len(earliest) > 0 {
		named := earliest[0]
		for _, each := range earliest[1:] {
			if each.since < named.since || each.since == named.since && each.id < named.id {
				named = each
			}
		}
		then = "`ak wait " + named.id + "`, then launch again"
	}
	return fmt.Sprintf("%s may have as many runs waiting for a slot as holding one, and always one: it has %d waiting and %d holding, so room for %d more, not %d; %s",
		seat, len(waiting), len(holding), max(room, 0), launches, then)
}
