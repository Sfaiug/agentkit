package cli

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"

	"agentkit/internal/menu"
)

// The variables Python's menu crosses a restart with its last read and its frame under (warm.READ,
// terminal.FRAME).
const menuRead, menuFrame = "AK_MENU_READ", "AK_MENU_FRAME"

// handedReading is a reading as it crosses: JSON, as the data of the [code, data] Python's
// warm.hand_on pickles.
type handedReading struct {
	Seats    []menu.Seat
	Cells    []menu.Cell
	Standing string
	Past     []menu.PastSeat
	Handoff  bool
	Switches map[string]int
}

// handOn is found as it crosses an exec to this same code; nil where the code cannot be read.
func handOn(found reading) []byte {
	code := menuCode()
	data, err := json.Marshal(handedReading{found.seats, found.cells, found.standing, found.past, found.handoff, found.switches})
	if code == "" || err != nil {
		return nil
	}
	return pickled(code, data)
}

// handedRead is the read the program before this exec handed on (handOn), where it was this code.
func handedRead() (reading, bool) {
	data := crossed(menuRead)
	if data == nil {
		return reading{}, false
	}
	code := menuCode()
	head := len(pickled(code, nil)) - len("e.") // what comes before the data
	if code == "" || len(data) < head+len("e.") {
		return reading{}, false
	}
	payload, found := data[head:len(data)-len("e.")], handedReading{}
	if !bytes.Equal(data, pickled(code, payload)) || json.Unmarshal(payload, &found) != nil {
		return reading{}, false
	}
	return reading{seats: found.Seats, cells: found.Cells, standing: found.Standing, past: found.Past, handoff: found.Handoff,
		switches: found.Switches}, true
}

// pickled is [code, data] as Python's pickle.dumps writes it at protocol 3, which Python's
// warm.handed loads and finds another code's.
func pickled(code string, data []byte) []byte {
	out := binary.LittleEndian.AppendUint32([]byte("\x80\x03](X"), uint32(len(code)))
	out = binary.LittleEndian.AppendUint32(append(append(out, code...), 'B'), uint32(len(data)))
	return append(append(out, data...), "e."...)
}

// menuCode is the code a read is made and drawn in, this program, as Python's menu.CODE is its
// source: a read crosses only to the same.  "" where it cannot be read, as off Linux.
func menuCode() string {
	program, err := os.Open("/proc/self/exe")
	if err != nil {
		return ""
	}
	defer program.Close()
	sum := sha256.New()
	if _, err := io.Copy(sum, program); err != nil {
		return ""
	}
	return hex.EncodeToString(sum.Sum(nil))
}
