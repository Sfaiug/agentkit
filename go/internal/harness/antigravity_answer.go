package harness

import (
	"bytes"
	"encoding/binary"
	"errors"
	"io/fs"
	"os"
	"slices"
	"strings"
	"unicode/utf8"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/sqlite"
)

// agyAnswer is the `steps.step_type` of an answer, agy's planner response (antigravity.py `MODEL`).
const agyAnswer = 15

// An agyAnswered is the model and effort of the generation that made a conversation's latest
// answer, and when that answer was done.
type agyAnswered struct {
	model, effort string
	at            float64
}

// antigravityStored is the reconciled plugin of a record whose launcher gave it that conversation:
// its last answer read from its store once, for the whole listing, a store landing or growing
// while it waits to publish the word the next listing's; no answer where it has no store, nor for
// a record owning another conversation by the time it is asked.  False where the store is there
// and Go cannot read it: Python's look reads that as no answer and leaves the seat on its old
// model, so Go hands the seat over before anything is written.
func antigravityStored(own plugin, conversation, path string) (plugin, bool) {
	if _, err := os.Stat(path); errors.Is(err, fs.ErrNotExist) {
		return own, true
	}
	answered, known := antigravityAnswered(path)
	own.answer = func(current *run.Object) (any, any, any, bool) {
		if answered == nil || current.Str("id_source") != "launcher" || current.Str("conversation") != conversation {
			return nil, nil, nil, false
		}
		return answered.model, answered.effort, run.Float(answered.at), true
	}
	return own, known
}

// antigravityAnswered is what the store at that path says its latest answer ran on, read as
// antigravity.py `answered_model` reads it: nil where it ties no generation to it.
func antigravityAnswered(path string) (*agyAnswered, bool) {
	conn, err := sqlite.Open(path, sqlite3.OPEN_READONLY)
	if err != nil {
		return nil, false
	}
	defer conn.Close()
	stmt, _, err := conn.Prepare("SELECT (SELECT metadata FROM steps WHERE step_type = ? ORDER BY idx DESC LIMIT 1)," +
		" (SELECT data FROM gen_metadata ORDER BY idx DESC LIMIT 1)")
	if err != nil {
		return nil, false
	}
	defer stmt.Close()
	row := make([]any, 2)
	if err := stmt.BindInt(1, agyAnswer); err != nil || !stmt.Step() || stmt.Columns(row...) != nil {
		return nil, false
	}
	// only a blob is a message: Python's `field` finds nothing in text or a number
	metadata, _ := row[0].([]byte)
	generation, _ := row[1].([]byte)
	var read agyReading
	execution, model := read.field(generation, 4), read.field(read.field(generation, 3), 28)
	answering := read.field(metadata, 12)
	at, dated := read.timestamp(read.field(metadata, 8))
	if read.wide { // Python reads a varint of any length
		return nil, false
	}
	if len(execution) == 0 || !bytes.Equal(execution, answering) || len(model) == 0 || !dated {
		return nil, true
	}
	if !utf8.Valid(model) { // Python replaces what is not UTF-8 otherwise than Go would
		return nil, false
	}
	levels, err := config.Efforts("antigravity", "")
	if err != nil {
		return nil, false
	}
	// folded as adapters/antigravity.sh's `models` folds `agy models`
	named := string(model)
	if cut := strings.LastIndex(named, "-"); cut > 0 && slices.Contains(levels, named[cut+1:]) {
		return &agyAnswered{named[:cut], named[cut+1:], at}, true
	}
	return &agyAnswered{named, "none", at}, true
}

// An agyReading reads agy's protocol buffers as antigravity.py does (`field`, `timestamp`,
// `varint`), noting a varint past 64 bits, which no message agy writes holds.
type agyReading struct{ wide bool }

// varint is the variable-length integer starting at `at`, and where the next field starts; false
// where the message ends inside it, or it is wide.
func (read *agyReading) varint(message []byte, at int) (uint64, int, bool) {
	value, size := binary.Uvarint(message[at:])
	read.wide = read.wide || size < 0
	return value, at + size, size > 0
}

// field is that length-delimited field of a protocol buffer message, nil where the message does
// not hold it whole.
func (read *agyReading) field(message []byte, number uint64) []byte {
	for at := 0; at < len(message); {
		key, next, whole := read.varint(message, at)
		if !whole {
			return nil
		}
		at = next
		switch key & 7 {
		case 2:
			size, next, whole := read.varint(message, at)
			if !whole || size > uint64(len(message)-next) {
				return nil
			}
			if at = next + int(size); key>>3 == number {
				return message[next:at]
			}
		case 0:
			if _, at, whole = read.varint(message, at); !whole {
				return nil
			}
		case 1:
			at += 8
		case 5:
			at += 4
		default:
			return nil
		}
	}
	return nil
}

// timestamp is a Timestamp's seconds (field 1) and nanoseconds (2, omitted when 0) as seconds,
// false where it does not read whole: a cut-off field is no date.
func (read *agyReading) timestamp(stamp []byte) (float64, bool) {
	fields := map[uint64]uint64{}
	for at := 0; at < len(stamp); {
		key, next, whole := read.varint(stamp, at)
		if _, twice := fields[key]; !whole || key != 1<<3 && key != 2<<3 || twice {
			return 0, false
		}
		if fields[key], at, whole = read.varint(stamp, next); !whole {
			return 0, false
		}
	}
	seconds, dated := fields[1<<3]
	if !dated || fields[2<<3] >= 1e9 {
		return 0, false
	}
	return float64(seconds) + float64(fields[2<<3])/1e9, true
}
