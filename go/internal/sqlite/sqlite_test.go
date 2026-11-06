package sqlite

import (
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// testdata/rows.db is Python's sqlite3 at a page of 512 bytes, so its tables span interior pages
// and a long text runs over overflow pages: table "kept" holds 300 rows, row i being
//
//	("k<i>", (-1)**i * i**7, or 2**63-1, -2**63 and 0 for the last three, i/4 where i%3 else NULL,
//	 "row <i> é", or 3000 x's for row 7, bytes([i%256]) * (i%5), NULL)
//
// under columns id (its primary key), n integer, f real, t text, b blob and `z"q` text, declared
// among comments and every way of quoting a name; "counted" an INTEGER PRIMARY KEY, "plain" one
// WITHOUT ROWID, and "grown" a column added after its first row.
const rows = "testdata/rows.db"

func TestRowsReadsEveryRowAsSQLiteKeptIt(t *testing.T) {
	var got [][]any
	if err := Rows(rows, "KEPT", []string{"n", "F", "t", "b", `z"q`}, func(row []any) { got = append(got, row) }); err != nil {
		t.Fatal(err)
	}
	if len(got) != 300 {
		t.Fatalf("%d rows", len(got))
	}
	for i, row := range got {
		n := int64(1 - 2*(i%2))
		for range 7 {
			n *= int64(i)
		}
		if i >= 297 {
			n = []int64{math.MaxInt64, math.MinInt64, 0}[i-297]
		}
		var f any
		if i%3 != 0 {
			f = float64(i) / 4
		}
		text := fmt.Sprintf("row %d é", i)
		if i == 7 {
			text = strings.Repeat("x", 3000)
		}
		if want := []any{n, f, text, bytes.Repeat([]byte{byte(i)}, i%5), nil}; !reflect.DeepEqual(row, want) {
			t.Fatalf("row %d: %#v, not %#v", i, row, want)
		}
	}
}

func TestRowsLeavesWhatItCannotReadAsSQLiteWould(t *testing.T) {
	for _, each := range []struct{ table, column string }{
		{"kept", "id"}, {"counted", "id"}, {"plain", "b"}, {"grown", "b"}, {"kept", "absent"}, {"absent", "n"},
	} {
		if err := Rows(rows, each.table, []string{each.column}, func([]any) {}); !errors.Is(err, ErrUnread) {
			t.Errorf("%s.%s: %v", each.table, each.column, err)
		}
	}
	if err := Rows(filepath.Join(t.TempDir(), "none.db"), "kept", []string{"n"}, func([]any) {}); !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("no file: %v", err)
	}
}

func TestRowsReadsNoFileAWriteIsGoingIntoOrCut(t *testing.T) {
	data, err := os.ReadFile(rows)
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	path := filepath.Join(dir, "rows.db")
	read := func() error { return Rows(path, "kept", []string{"n"}, func([]any) {}) }
	write := func(name string, data []byte) {
		if err := os.WriteFile(filepath.Join(dir, name), data, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	write("rows.db", data)
	write("rows.db-wal", nil) // a log every page has gone back from
	if err := read(); err != nil {
		t.Fatalf("a file at rest: %v", err)
	}
	for _, beside := range []string{"rows.db-wal", "rows.db-journal"} {
		write(beside, []byte("pages"))
		if err := read(); !errors.Is(err, ErrUnread) {
			t.Errorf("%s holding pages: %v", beside, err)
		}
		if err := os.Remove(filepath.Join(dir, beside)); err != nil {
			t.Fatal(err)
		}
	}
	write("rows.db", data[:len(data)/2])
	if err := read(); !errors.Is(err, ErrUnread) {
		t.Errorf("half a file: %v", err)
	}
}
