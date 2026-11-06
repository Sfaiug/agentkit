// Package sqlite reads the rows of a table in a SQLite file another program keeps, as Python's
// sqlite3 reads them over a read-only connection: Go's standard library holds no SQLite, and ak
// only ever reads a harness's own store.  It reads a file at rest -- no write-ahead log or journal
// beside it holding pages the file lacks, and the file unchanged while it is read -- and only what
// the file format spells out plainly; anything else is ErrUnread, for the caller to leave to Python.
package sqlite

import (
	"encoding/binary"
	"errors"
	"fmt"
	"io/fs"
	"math"
	"os"
	"slices"
	"strings"
	"unicode/utf8"
)

// ErrUnread is a file Go does not read as SQLite would: one being written, or holding what this
// reader does not follow.
var ErrUnread = errors.New("not a SQLite file Go reads")

const (
	interior, leaf = 0x05, 0x0d // the kinds of page a table's tree is made of
	schemaPage     = 1          // sqlite_schema's root: type, name, tbl_name, rootpage, sql
	headerBytes    = 100        // the file's own header, ahead of page 1's
)

// Rows calls each with the named columns of every row of that table, in rowid order: nil, an
// int64, a float64, a string or a []byte, as the file stores it.  An error, which voids every row
// given, wraps fs.ErrNotExist where no file is there.
func Rows(path, table string, columns []string, each func(row []any)) error {
	before, err := settled(path)
	if err != nil {
		return err
	}
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()
	err = read(file, table, columns, each)
	if after, _ := settled(path); err == nil && after != before {
		return ErrUnread
	}
	return err
}

// A moment is what says a file moved: its size and when it was last written.
type moment struct{ size, written int64 }

// settled is the file's moment, while nothing beside it holds a write the file has not taken in.
func settled(path string) (moment, error) {
	info, err := os.Stat(path)
	if err == nil && !info.Mode().IsRegular() {
		err = fmt.Errorf("%s: %w", path, fs.ErrNotExist)
	}
	if err != nil {
		return moment{}, err
	}
	for _, beside := range []string{"-wal", "-journal"} {
		if other, err := os.Stat(path + beside); err == nil && other.Size() > 0 || err != nil && !errors.Is(err, fs.ErrNotExist) {
			return moment{}, ErrUnread
		}
	}
	return moment{info.Size(), info.ModTime().UnixNano()}, nil
}

func read(file *os.File, table string, columns []string, each func([]any)) error {
	db, err := open(file)
	if err != nil {
		return err
	}
	var root, sql any
	err = db.walk(schemaPage, func(values []any) error {
		if len(values) == 5 && values[0] == "table" {
			if name, _ := values[1].(string); strings.EqualFold(name, table) {
				root, sql = values[3], values[4]
			}
		}
		return nil
	})
	page, numbered := root.(int64)
	statement, _ := sql.(string)
	declares, plain := declared(statement)
	if err != nil || !numbered || page <= 0 || page > math.MaxUint32 || !plain {
		return ErrUnread
	}
	at := make([]int, len(columns))
	for i, name := range columns {
		// a primary key may be the rowid's alias, which the rowid holds and the record does not
		if at[i] = slices.IndexFunc(declares, func(each column) bool { return strings.EqualFold(each.name, name) }); at[i] < 0 || declares[at[i]].keyed {
			return ErrUnread
		}
	}
	return db.walk(uint32(page), func(values []any) error {
		row := make([]any, len(at))
		for i, column := range at {
			// a row written before its column was added holds no value for it: the default stands in
			if column >= len(values) {
				return ErrUnread
			}
			row[i] = values[column]
			// a real number with nothing after its point is kept as an integer, and read back a real
			if whole, ok := row[i].(int64); ok && declares[column].real {
				row[i] = float64(whole)
			}
			if text, ok := row[i].(string); ok && !utf8.ValidString(text) {
				return ErrUnread
			}
		}
		each(row)
		return nil
	})
}

type db struct {
	file   *os.File
	size   int             // bytes a page holds
	usable int             // of them, those not reserved at its end
	pages  uint32          // pages the file holds
	seen   map[uint32]bool // pages read so far: one read twice is a loop no sound file has
}

func open(file *os.File) (*db, error) {
	header := make([]byte, headerBytes)
	info, err := file.Stat()
	if _, read := file.ReadAt(header, 0); read != nil || err != nil || string(header[:16]) != "SQLite format 3\x00" {
		return nil, ErrUnread
	}
	size := int(binary.BigEndian.Uint16(header[16:]))
	if size == 1 {
		size = 65536
	}
	// a read version past 2, the write-ahead log's, is a format this reader does not know; text
	// in anything but UTF-8 would need converting
	if size < 512 || size&(size-1) != 0 || header[19] > 2 || size-int(header[20]) < 480 || binary.BigEndian.Uint32(header[56:]) != 1 {
		return nil, ErrUnread
	}
	return &db{file, size, size - int(header[20]), uint32(min(info.Size()/int64(size), math.MaxUint32)), map[uint32]bool{}}, nil
}

// page is page n's usable bytes, the first time it is asked for.
func (db *db) page(n uint32) ([]byte, error) {
	if n == 0 || n > db.pages || db.seen[n] {
		return nil, ErrUnread
	}
	db.seen[n] = true
	page := make([]byte, db.size)
	if _, err := db.file.ReadAt(page, int64(n-1)*int64(db.size)); err != nil {
		return nil, ErrUnread
	}
	return page[:db.usable], nil
}

// walk calls each with the values of every row of the table tree rooted at page n, in rowid order.
func (db *db) walk(n uint32, each func([]any) error) error {
	page, err := db.page(n)
	if err != nil {
		return err
	}
	at := 0
	if n == schemaPage {
		at = headerBytes
	}
	kind, cells, pointers := page[at], int(binary.BigEndian.Uint16(page[at+3:])), at+8
	if kind == interior {
		pointers += 4
	}
	if kind != interior && kind != leaf || pointers+2*cells > len(page) {
		return ErrUnread
	}
	for i := range cells {
		cell := page[min(len(page), int(binary.BigEndian.Uint16(page[pointers+2*i:]))):]
		if kind == interior {
			if len(cell) < 4 {
				return ErrUnread
			}
			if err := db.walk(binary.BigEndian.Uint32(cell), each); err != nil {
				return err
			}
			continue
		}
		size, sized := varint(cell)
		_, numbered := varint(cell[sized:])
		if sized == 0 || numbered == 0 {
			return ErrUnread
		}
		payload, err := db.payload(cell[sized+numbered:], size)
		if err != nil {
			return err
		}
		values, err := record(payload)
		if err != nil {
			return err
		}
		if err := each(values); err != nil {
			return err
		}
	}
	if kind == interior {
		return db.walk(binary.BigEndian.Uint32(page[at+8:]), each)
	}
	return nil
}

// payload is a leaf cell's whole payload of that size: what the page holds of it, then the rest
// from its chain of overflow pages.
func (db *db) payload(cell []byte, size uint64) ([]byte, error) {
	usable := uint64(db.usable)
	local := size
	if most := usable - 35; size > most {
		least := (usable-12)*32/255 - 23
		if local = least + (size-least)%(usable-4); local > most {
			local = least
		}
	}
	held := local // and the overflow page's number after it, where there is one
	if local < size {
		held += 4
	}
	if size > uint64(db.pages)*uint64(db.size) || uint64(len(cell)) < held {
		return nil, ErrUnread
	}
	out := append(make([]byte, 0, size), cell[:local]...)
	for next := cell[local:]; uint64(len(out)) < size; {
		page, err := db.page(binary.BigEndian.Uint32(next))
		if err != nil {
			return nil, err
		}
		out = append(out, page[4:4+min(usable-4, size-uint64(len(out)))]...)
		next = page
	}
	return out, nil
}

// record is the values a row's payload holds, each as its serial type says.
func record(payload []byte) ([]any, error) {
	header, n := varint(payload)
	if n == 0 || header < uint64(n) || header > uint64(len(payload)) {
		return nil, ErrUnread
	}
	body := payload[header:]
	var values []any
	for at := uint64(n); at < header; {
		kind, k := varint(payload[at:header])
		if k == 0 || kind == 10 || kind == 11 {
			return nil, ErrUnread
		}
		at += uint64(k)
		width := uint64(0)
		switch {
		case kind >= 12:
			width = (kind - 12) / 2
		case kind <= 7:
			width = []uint64{0, 1, 2, 3, 4, 6, 8, 8}[kind]
		}
		if uint64(len(body)) < width {
			return nil, ErrUnread
		}
		field := body[:width]
		body = body[width:]
		switch {
		case kind == 0:
			values = append(values, nil)
		case kind <= 6:
			var value int64
			for _, b := range field {
				value = value<<8 | int64(b)
			}
			shift := 64 - 8*width
			values = append(values, value<<shift>>shift)
		case kind == 7:
			values = append(values, math.Float64frombits(binary.BigEndian.Uint64(field)))
		case kind <= 9:
			values = append(values, int64(kind-8))
		case kind%2 == 0:
			values = append(values, field)
		default:
			values = append(values, string(field))
		}
	}
	return values, nil
}

// varint is SQLite's variable-length integer at the start of b and the bytes it takes, 0 where b
// ends inside it.
func varint(b []byte) (uint64, int) {
	var value uint64
	for i := 0; i < len(b) && i < 9; i++ {
		if i == 8 {
			return value<<8 | uint64(b[i]), 9
		}
		value = value<<7 | uint64(b[i]&0x7f)
		if b[i] < 0x80 {
			return value, i + 1
		}
	}
	return 0, 0
}

// A token is a word of SQL: a bare word or mark, or a quoted name with its quotes taken off.
type token struct {
	text   string
	quoted bool
}

// A column is one a table declares: its name, whether it is or may be the table's primary key, and
// whether its type gives it REAL affinity.
type column struct {
	name        string
	keyed, real bool
}

// declared is each column a CREATE TABLE statement declares, in order; false where its rows are
// not records in a tree of rowids, each with a value for every column: one WITHOUT ROWID, or with
// a generated column, kept nowhere or apart.
func declared(sql string) ([]column, bool) {
	tokens := tokenize(sql)
	open := slices.Index(tokens, token{"(", false})
	if open < 0 {
		return nil, false
	}
	var defs [][]token
	depth, start, end := 0, open+1, -1
	for i := open; i < len(tokens) && end < 0; i++ {
		switch tokens[i] {
		case token{"(", false}:
			depth++
		case token{")", false}:
			if depth--; depth == 0 {
				defs, end = append(defs, tokens[start:i]), i
			}
		case token{",", false}:
			if depth == 1 {
				defs, start = append(defs, tokens[start:i]), i+1
			}
		}
	}
	says := func(tokens []token, words ...string) bool {
		return slices.ContainsFunc(tokens, func(t token) bool {
			return !t.quoted && slices.ContainsFunc(words, func(word string) bool { return strings.EqualFold(t.text, word) })
		})
	}
	if end < 0 || says(tokens[end+1:], "ROWID") {
		return nil, false
	}
	var columns []column
	var primary []token // what a table constraint makes its primary key
	for _, def := range defs {
		switch {
		case len(def) == 0 || says(def[1:], "AS"):
			return nil, false
		case says(def[:1], "CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN"):
			if says(def, "PRIMARY") {
				primary = append(primary, def...)
			}
		default:
			// its type is the words up to its first constraint, read for affinity as SQLite reads it
			kind := ""
			for _, t := range def[1:] {
				if t.text == "(" || says([]token{t}, "CONSTRAINT", "PRIMARY", "NOT", "NULL", "UNIQUE", "CHECK", "DEFAULT", "COLLATE", "REFERENCES") {
					break
				}
				kind += strings.ToUpper(t.text) + " "
			}
			has := func(parts ...string) bool {
				return slices.ContainsFunc(parts, func(part string) bool { return strings.Contains(kind, part) })
			}
			columns = append(columns, column{def[0].text, says(def, "PRIMARY"), has("REAL", "FLOA", "DOUB") && !has("INT", "CHAR", "CLOB", "TEXT", "BLOB")})
		}
	}
	for i := range columns {
		columns[i].keyed = columns[i].keyed || slices.ContainsFunc(primary, func(t token) bool { return strings.EqualFold(t.text, columns[i].name) })
	}
	return columns, true
}

// tokenize splits SQL into its tokens, leaving out its spaces and comments.
func tokenize(sql string) []token {
	var tokens []token
	for at := 0; at < len(sql); {
		c := sql[at]
		switch {
		case strings.IndexByte(" \t\n\f\r", c) >= 0:
			at++
		case strings.HasPrefix(sql[at:], "--") || strings.HasPrefix(sql[at:], "/*"):
			ends := "*/"
			if c == '-' {
				ends = "\n"
			}
			if end := strings.Index(sql[at+2:], ends); end >= 0 {
				at += 2 + end + len(ends)
			} else {
				at = len(sql)
			}
		case strings.IndexByte("\"`'[", c) >= 0:
			closing := c
			if c == '[' {
				closing = ']'
			}
			var text strings.Builder
			for at++; at < len(sql); at++ {
				if sql[at] == closing {
					// a quote doubled inside is one quote; brackets take no such escape
					if closing == ']' || at+1 == len(sql) || sql[at+1] != closing {
						at++
						break
					}
					at++
				}
				text.WriteByte(sql[at])
			}
			tokens = append(tokens, token{text.String(), true})
		case word(c):
			start := at
			for at < len(sql) && word(sql[at]) {
				at++
			}
			tokens = append(tokens, token{sql[start:at], false})
		default:
			tokens = append(tokens, token{string(c), false})
			at++
		}
	}
	return tokens
}

// word is whether a byte can be part of a bare word: a letter, a digit, `_`, `$`, or any byte of a
// character past ASCII.
func word(c byte) bool {
	return c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == '$' || c >= 0x80
}
