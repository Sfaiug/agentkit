package harness

import (
	"math"
	"os"
	"path/filepath"
	"slices"
	"testing"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/run"
	"agentkit/internal/sqlite"
)

// An agyGeneration is one execution in agy's store: the model it ran on by agy's id, and when its
// answer was done, 0 for one that made none.
type agyGeneration struct {
	model string
	at    float64
}

func agyVarintOf(value uint64) []byte {
	var out []byte
	for ; value >= 0x80; value >>= 7 {
		out = append(out, byte(value)|0x80)
	}
	return append(out, byte(value))
}

func agyNested(field uint64, data []byte) []byte {
	return append(append(agyVarintOf(field<<3|2), agyVarintOf(uint64(len(data)))...), data...)
}

func agyStamp(field uint64, at float64) []byte {
	seconds, fraction := math.Modf(at)
	return agyNested(field, append(append(agyVarintOf(1<<3), agyVarintOf(uint64(seconds))...),
		append(agyVarintOf(2<<3), agyVarintOf(uint64(math.Round(fraction*1e9)))...)...))
}

// agyStore writes a conversation's store as agy 1.4.11 keeps one, as far as the columns read go:
// each generation's user input and answer, and its generation row, which names its model only
// while it is the newest.
func agyStore(t *testing.T, path string, generations ...agyGeneration) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	conn, err := sqlite.Open(path, sqlite3.OPEN_READWRITE|sqlite3.OPEN_CREATE)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	insert := func(query string, args ...any) {
		t.Helper()
		stmt, _, err := conn.Prepare(query)
		if err != nil {
			t.Fatal(err)
		}
		defer stmt.Close()
		for at, arg := range args {
			if data, isBlob := arg.([]byte); isBlob {
				err = stmt.BindBlob(at+1, data)
			} else {
				err = stmt.BindInt(at+1, arg.(int))
			}
			if err != nil {
				t.Fatal(err)
			}
		}
		if err := stmt.Exec(); err != nil {
			t.Fatal(err)
		}
	}
	insert("CREATE TABLE `steps` (`idx` integer,`step_type` integer NOT NULL DEFAULT 0,`metadata` blob,`step_payload` blob,PRIMARY KEY (`idx`))")
	insert("CREATE TABLE `gen_metadata` (`idx` integer,`data` blob,PRIMARY KEY (`idx`))")
	for n, each := range generations {
		execution := []byte{'r', byte('0' + n)}
		if each.at != 0 {
			made := agyStamp(1, each.at-60)
			insert("INSERT INTO steps (idx, step_type, metadata) VALUES (?, 14, ?)", 2*n, slices.Concat(made, agyNested(12, execution)))
			insert("INSERT INTO steps (idx, step_type, metadata) VALUES (?, 15, ?)", 2*n+1,
				slices.Concat(made, agyStamp(8, each.at), agyNested(12, execution)))
		}
		var named []byte
		if n == len(generations)-1 {
			named = agyNested(28, []byte(each.model))
		}
		insert("INSERT INTO gen_metadata (idx, data) VALUES (?, ?)", n, slices.Concat(agyNested(3, named), agyNested(4, execution)))
	}
}

func TestAntigravityReadsTheModelOfItsLatestAnswer(t *testing.T) {
	type read struct {
		model, effort, at any
		found             bool
	}
	for name, each := range map[string]struct {
		generations []agyGeneration
		want        read
	}{
		"the newest answer's generation": {[]agyGeneration{{"gemini-3.8-flash-high", 100}, {"gemini-4-argon-low", 200.5}},
			read{"gemini-4-argon", "low", run.Float(200.5), true}},
		"a model at no effort":            {[]agyGeneration{{"gpt-oss-120b", 100}}, read{"gpt-oss-120b", "none", run.Float(100), true}},
		"a newest generation that failed": {[]agyGeneration{{"gemini-3.8-flash-high", 100}, {"gemini-4-argon-low", 0}}, read{}},
		"no answer yet":                   {[]agyGeneration{{"gemini-4-argon-low", 0}}, read{}},
	} {
		t.Run(name, func(t *testing.T) {
			home := t.TempDir()
			t.Setenv("HOME", home)
			t.Setenv("USERPROFILE", home)
			agyStore(t, filepath.Join(home, ".gemini", "antigravity-cli", "conversations", "conv-acme.db"), each.generations...)
			record := run.Fields("conversation", "conv-acme", "id_source", "launcher")
			reader, ready := For("antigravity").Reconciled("acme", record)
			var got read
			got.model, got.effort, got.at, got.found = reader.LastAnswer(record)
			if !ready || got != each.want {
				t.Fatalf("ready=%v, %+v", ready, got)
			}
			// a record owning another conversation by the time it is asked has no answer of this one
			if _, _, _, found := reader.LastAnswer(run.Fields("conversation", "conv-other", "id_source", "launcher")); found {
				t.Fatal("another conversation's record read this store's answer")
			}
		})
	}
}

func TestAntigravityHandsOverAStoreItCannotRead(t *testing.T) {
	for name, write := range map[string]func(t *testing.T, path string){
		"not SQLite": func(t *testing.T, path string) {
			if err := os.WriteFile(path, []byte("pages"), 0o600); err != nil {
				t.Fatal(err)
			}
		},
		"a folder": func(t *testing.T, path string) {
			if err := os.Mkdir(path, 0o700); err != nil {
				t.Fatal(err)
			}
		},
	} {
		t.Run(name, func(t *testing.T) {
			home := t.TempDir()
			t.Setenv("HOME", home)
			t.Setenv("USERPROFILE", home)
			path := filepath.Join(home, ".gemini", "antigravity-cli", "conversations", "conv-acme.db")
			if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
				t.Fatal(err)
			}
			write(t, path)
			if _, ready := For("antigravity").Reconciled("acme", run.Fields("conversation", "conv-acme", "id_source", "launcher")); ready {
				t.Fatal("a store that cannot be read was read as holding no answer")
			}
		})
	}
}

func TestAntigravityReadsATimestampWholeOrNotAtAll(t *testing.T) {
	type read struct {
		at          float64
		dated, wide bool
	}
	for stamp, want := range map[string]read{
		"\x08\x05":                         {5, true, false},
		"\x10\x80\xca\xb5\xee\x01\x08\x05": {5.5, true, false}, // nanoseconds first
		"\x08\x05\x10\x00":                 {5, true, false},
		"":                                 {},
		"\x08":                             {}, // cut off
		"\x08\x05\x08\x06":                 {}, // seconds twice
		"\x18\x01":                         {}, // another field
		"\x10\x01":                         {}, // no seconds
		"\x08\x05\x10\x80\x94\xeb\xdc\x03": {}, // a whole second of nanoseconds
		// 2**64 seconds, which Python reads and Go hands over
		"\x08\x80\x80\x80\x80\x80\x80\x80\x80\x80\x02": {0, false, true},
	} {
		var reading agyReading
		var got read
		got.at, got.dated = reading.timestamp([]byte(stamp))
		if got.wide = reading.wide; got != want {
			t.Errorf("%q: %+v", stamp, got)
		}
	}
}
