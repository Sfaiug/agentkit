package config

import (
	"fmt"
	"math"
	"math/big"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
)

// This reader walks a document as Python's tomllib does, rule by rule, so that it takes what
// tomllib takes and refuses the rest in tomllib's words at tomllib's place: a refusal reaches the
// owner as it stands, and these rules are what decide its words and where it stopped.

type table struct {
	values map[string]any
	keys   []string
}

type tableArray []*table

func newTable() *table { return &table{values: map[string]any{}} }

func (t *table) put(key string, value any) {
	if _, exists := t.values[key]; !exists {
		t.keys = append(t.keys, key)
	}
	t.values[key] = value
}

// get is the value under the key, nil where there is none or no table.
func (t *table) get(key string) any {
	if t == nil {
		return nil
	}
	return t.values[key]
}

// nest is the table behind the key, made where it is missing, the last of an array of tables
// where lists says so; false where a value stands in the way.
func (t *table) nest(key []string, lists bool) (*table, bool) {
	for _, part := range key {
		if _, exists := t.values[part]; !exists {
			t.put(part, newTable())
		}
		value := t.values[part]
		if rows, ok := value.(tableArray); ok && lists {
			value = rows[len(rows)-1]
		}
		next, ok := value.(*table)
		if !ok {
			return nil, false
		}
		t = next
	}
	return t, true
}

const (
	frozen   uint8 = 1 << iota // an inline table or array, which nothing may add to
	explicit                   // a nest made explicitly, which `[table]` may no longer open
)

// flagged holds the flags of one key and of the keys under it.
type flagged struct {
	own, recursive uint8
	nested         map[string]*flagged
}

func (f *flagged) under(key []string) *flagged {
	for _, part := range key {
		if f.nested == nil {
			f.nested = map[string]*flagged{}
		}
		if f.nested[part] == nil {
			f.nested[part] = &flagged{}
		}
		f = f.nested[part]
	}
	return f
}

func (f *flagged) set(key []string, flag uint8, recursive bool) {
	if recursive {
		f.under(key).recursive |= flag
	} else {
		f.under(key).own |= flag
	}
}

func (f *flagged) is(key []string, flag uint8) bool {
	if len(key) == 0 {
		return false // the document's root has no flags
	}
	for _, part := range key[:len(key)-1] {
		inner, ok := f.nested[part]
		if !ok {
			return false
		}
		if inner.recursive&flag != 0 {
			return true
		}
		f = inner
	}
	stem, ok := f.nested[key[len(key)-1]]
	return ok && (stem.own|stem.recursive)&flag != 0
}

func (f *flagged) unset(key []string) {
	for _, part := range key[:len(key)-1] {
		inner, ok := f.nested[part]
		if !ok {
			return
		}
		f = inner
	}
	delete(f.nested, key[len(key)-1])
}

type parser struct {
	text    string
	pos     int
	root    *table
	flags   flagged
	pending [][]string // keys a dotted key opened: explicit once the next header comes
}

const (
	inlineSpace = " \t"
	anySpace    = " \t\n"
	bareChars   = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
	hexDigits   = "0123456789abcdefABCDEF"
)

// problem is the error at pos, tomllib's coordinates after the message.
func (p *parser) problem(pos int, message string) error {
	if pos >= len(p.text) {
		return fmt.Errorf("%s (at end of document)", message)
	}
	line := strings.Count(p.text[:pos], "\n") + 1
	column := utf8.RuneCountInString(p.text[strings.LastIndex(p.text[:pos], "\n")+1:pos]) + 1
	return fmt.Errorf("%s (at line %d, column %d)", message, line, column)
}

func (p *parser) at(text string) bool { return strings.HasPrefix(p.text[p.pos:], text) }

func (p *parser) skip(chars string) {
	for p.pos < len(p.text) && strings.IndexByte(chars, p.text[p.pos]) >= 0 {
		p.pos++
	}
}

// illegal is whether no string or comment may hold the character; multiline strings take newlines.
func illegal(c byte, multiline bool) bool {
	return (c < 0x20 && c != '\t' && !(multiline && c == '\n')) || c == 0x7f
}

// until is where expect comes next, the end of the text for a comment, checking what lies before.
func (p *parser) until(expect string, multiline, required bool) (int, error) {
	end := strings.Index(p.text[p.pos:], expect)
	if end < 0 {
		end = len(p.text)
		if required {
			return 0, p.problem(end, "Expected "+commandhelp.Quote(expect))
		}
	} else {
		end += p.pos
	}
	for i := p.pos; i < end; i++ {
		if illegal(p.text[i], multiline) {
			return 0, p.problem(i, "Found invalid character "+commandhelp.Quote(string(rune(p.text[i]))))
		}
	}
	return end, nil
}

func (p *parser) comment() error {
	if !p.at("#") {
		return nil
	}
	p.pos++
	end, err := p.until("\n", false, false)
	p.pos = end
	return err
}

func (p *parser) arraySpace() error {
	for {
		before := p.pos
		p.skip(anySpace)
		if err := p.comment(); err != nil {
			return err
		}
		if p.pos == before {
			return nil
		}
	}
}

// TOML is why text is no TOML, nil where it is.
func TOML(text string) error {
	_, err := parseDocument(text)
	return err
}

func parseDocument(text string) (*table, error) {
	if !utf8.ValidString(text) {
		return nil, fmt.Errorf("config is not valid UTF-8")
	}
	p := parser{text: strings.ReplaceAll(text, "\r\n", "\n"), root: newTable()}
	var header []string
	for {
		p.skip(inlineSpace)
		if p.pos == len(p.text) {
			return p.root, nil
		}
		c := p.text[p.pos]
		if c == '\n' {
			p.pos++
			continue
		}
		var err error
		switch {
		case strings.IndexByte(bareChars+`"'`, c) >= 0:
			err = p.keyValue(header)
		case c == '[':
			for _, key := range p.pending {
				p.flags.set(key, explicit, false)
			}
			p.pending = nil
			if p.at("[[") {
				header, err = p.arrayHeader()
			} else {
				header, err = p.tableHeader()
			}
		case c != '#':
			err = p.problem(p.pos, "Invalid statement")
		}
		if err != nil {
			return nil, err
		}
		p.skip(inlineSpace)
		if err := p.comment(); err != nil {
			return nil, err
		}
		if p.pos == len(p.text) {
			return p.root, nil
		}
		if p.text[p.pos] != '\n' {
			return nil, p.problem(p.pos, "Expected newline or end of document after a statement")
		}
		p.pos++
	}
}

// keyTuple is a key as Python prints the tuple tomllib holds it in.
func keyTuple(key []string) string {
	parts := make([]string, len(key))
	for i, part := range key {
		parts[i] = commandhelp.Quote(part)
	}
	if len(parts) == 1 {
		return "(" + parts[0] + ",)"
	}
	return "(" + strings.Join(parts, ", ") + ")"
}

func (p *parser) tableHeader() ([]string, error) {
	p.pos++
	p.skip(inlineSpace)
	key, err := p.key()
	if err != nil {
		return nil, err
	}
	if p.flags.is(key, explicit) || p.flags.is(key, frozen) {
		return nil, p.problem(p.pos, "Cannot declare "+keyTuple(key)+" twice")
	}
	p.flags.set(key, explicit, false)
	if _, ok := p.root.nest(key, true); !ok {
		return nil, p.problem(p.pos, "Cannot overwrite a value")
	}
	if !p.at("]") {
		return nil, p.problem(p.pos, "Expected ']' at the end of a table declaration")
	}
	p.pos++
	return key, nil
}

func (p *parser) arrayHeader() ([]string, error) {
	p.pos += 2
	p.skip(inlineSpace)
	key, err := p.key()
	if err != nil {
		return nil, err
	}
	if p.flags.is(key, frozen) {
		return nil, p.problem(p.pos, "Cannot mutate immutable namespace "+keyTuple(key))
	}
	// a new row frees all under the key, and the key itself still takes no `[table]`
	p.flags.unset(key)
	p.flags.set(key, explicit, false)
	parent, ok := p.root.nest(key[:len(key)-1], true)
	stem := key[len(key)-1]
	var rows tableArray
	if ok {
		if value, exists := parent.values[stem]; exists {
			rows, ok = value.(tableArray)
		}
	}
	if !ok {
		return nil, p.problem(p.pos, "Cannot overwrite a value")
	}
	parent.put(stem, append(rows, newTable()))
	if !p.at("]]") {
		return nil, p.problem(p.pos, "Expected ']]' at the end of an array declaration")
	}
	p.pos += 2
	return key, nil
}

func (p *parser) keyValue(header []string) error {
	key, value, err := p.pair()
	if err != nil {
		return err
	}
	stem := key[len(key)-1]
	parent := slices.Concat(header, key[:len(key)-1])
	for i := 1; i < len(key); i++ {
		opened := slices.Concat(header, key[:i])
		if p.flags.is(opened, explicit) {
			return p.problem(p.pos, "Cannot redefine namespace "+keyTuple(opened))
		}
		p.pending = append(p.pending, opened)
	}
	if p.flags.is(parent, frozen) {
		return p.problem(p.pos, "Cannot mutate immutable namespace "+keyTuple(parent))
	}
	nest, ok := p.root.nest(parent, true)
	if !ok {
		return p.problem(p.pos, "Cannot overwrite a value")
	}
	if _, exists := nest.values[stem]; exists {
		return p.problem(p.pos, "Cannot overwrite a value")
	}
	if nestable(value) {
		p.flags.set(slices.Concat(header, key), frozen, true)
	}
	nest.put(stem, value)
	return nil
}

func nestable(value any) bool {
	switch value.(type) {
	case *table, []any:
		return true
	}
	return false
}

func (p *parser) pair() ([]string, any, error) {
	key, err := p.key()
	if err != nil {
		return nil, nil, err
	}
	if !p.at("=") {
		return nil, nil, p.problem(p.pos, "Expected '=' after a key in a key/value pair")
	}
	p.pos++
	p.skip(inlineSpace)
	value, err := p.value()
	return key, value, err
}

func (p *parser) key() ([]string, error) {
	var key []string
	for {
		part, err := p.keyPart()
		if err != nil {
			return nil, err
		}
		key = append(key, part)
		p.skip(inlineSpace)
		if !p.at(".") {
			return key, nil
		}
		p.pos++
		p.skip(inlineSpace)
	}
}

func (p *parser) keyPart() (string, error) {
	switch {
	case p.at("'"):
		return p.literal()
	case p.at(`"`):
		p.pos++
		return p.basic(false)
	}
	start := p.pos
	p.skip(bareChars)
	if p.pos == start {
		return "", p.problem(p.pos, "Invalid initial character for a key part")
	}
	return p.text[start:p.pos], nil
}

func (p *parser) literal() (string, error) {
	p.pos++
	start := p.pos
	end, err := p.until("'", false, true)
	if err != nil {
		return "", err
	}
	p.pos = end + 1
	return p.text[start:end], nil
}

func (p *parser) multiline(delimiter string) (string, error) {
	p.pos += 3
	if p.at("\n") {
		p.pos++
	}
	var text string
	var err error
	if delimiter == "'" {
		start := p.pos
		var end int
		if end, err = p.until("'''", true, true); err == nil {
			text = p.text[start:end]
			p.pos = end + 3
		}
	} else {
		text, err = p.basic(true)
	}
	if err != nil {
		return "", err
	}
	// a closing run of four or five quotes ends in one or two of the string's own
	for i := 0; i < 2 && p.at(delimiter); i++ {
		p.pos++
		text += delimiter
	}
	return text, nil
}

func (p *parser) basic(multiline bool) (string, error) {
	var out strings.Builder
	for {
		if p.pos >= len(p.text) {
			return "", p.problem(p.pos, "Unterminated string")
		}
		c := p.text[p.pos]
		switch {
		case c == '"':
			if !multiline {
				p.pos++
				return out.String(), nil
			}
			if p.at(`"""`) {
				p.pos += 3
				return out.String(), nil
			}
		case c == '\\':
			escaped, err := p.escape(multiline)
			if err != nil {
				return "", err
			}
			out.WriteString(escaped)
			continue
		case illegal(c, multiline):
			return "", p.problem(p.pos, "Illegal character "+commandhelp.Quote(string(rune(c))))
		}
		out.WriteByte(c)
		p.pos++
	}
}

func (p *parser) escape(multiline bool) (string, error) {
	_, size := utf8.DecodeRuneInString(p.text[p.pos+1:])
	id := p.text[p.pos+1 : p.pos+1+size]
	p.pos += 1 + max(size, 1) // the text's end is past it, as tomllib's two characters are
	switch {
	case multiline && (id == " " || id == "\t" || id == "\n"):
		if id != "\n" {
			p.skip(inlineSpace)
			if p.pos == len(p.text) {
				return "", nil
			}
			if p.text[p.pos] != '\n' {
				return "", p.problem(p.pos, `Unescaped '\' in a string`)
			}
			p.pos++
		}
		p.skip(anySpace)
		return "", nil
	case id == "u":
		return p.hex(4)
	case id == "U":
		return p.hex(8)
	}
	if index := strings.Index(`btnfr"\`, id); index >= 0 && id != "" {
		return string("\b\t\n\f\r\"\\"[index]), nil
	}
	return "", p.problem(p.pos, `Unescaped '\' in a string`)
}

func (p *parser) hex(length int) (string, error) {
	start := p.pos
	p.skip(hexDigits)
	if p.pos-start < length {
		return "", p.problem(start, "Invalid hex value")
	}
	p.pos = start + length
	code, _ := strconv.ParseUint(p.text[start:p.pos], 16, 64)
	if code > utf8.MaxRune || !utf8.ValidRune(rune(code)) {
		return "", p.problem(p.pos, "Escaped character is not a Unicode scalar value")
	}
	return string(rune(code)), nil
}

func (p *parser) array() (any, error) {
	p.pos++
	values := []any{}
	if err := p.arraySpace(); err != nil {
		return nil, err
	}
	for !p.at("]") {
		value, err := p.value()
		if err != nil {
			return nil, err
		}
		values = append(values, value)
		if err := p.arraySpace(); err != nil {
			return nil, err
		}
		if p.at("]") {
			break
		}
		if !p.at(",") {
			return nil, p.problem(p.pos, "Unclosed array")
		}
		p.pos++
		if err := p.arraySpace(); err != nil {
			return nil, err
		}
	}
	p.pos++
	return values, nil
}

func (p *parser) inline() (any, error) {
	p.pos++
	root := newTable()
	var flags flagged
	p.skip(inlineSpace)
	if p.at("}") {
		p.pos++
		return root, nil
	}
	for {
		key, value, err := p.pair()
		if err != nil {
			return nil, err
		}
		if flags.is(key, frozen) {
			return nil, p.problem(p.pos, "Cannot mutate immutable namespace "+keyTuple(key))
		}
		stem := key[len(key)-1]
		nest, ok := root.nest(key[:len(key)-1], false)
		if !ok {
			return nil, p.problem(p.pos, "Cannot overwrite a value")
		}
		if _, exists := nest.values[stem]; exists {
			return nil, p.problem(p.pos, "Duplicate inline table key "+commandhelp.Quote(stem))
		}
		nest.put(stem, value)
		p.skip(inlineSpace)
		if p.at("}") {
			p.pos++
			return root, nil
		}
		if !p.at(",") {
			return nil, p.problem(p.pos, "Unclosed inline table")
		}
		if nestable(value) {
			flags.set(key, frozen, true)
		}
		p.pos++
		p.skip(inlineSpace)
	}
}

const clock = `([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])(?:\.([0-9]{1,6})[0-9]*)?`

var (
	dateTime  = regexp.MustCompile(`^([0-9]{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])(?:[Tt ]` + clock + `(?:([Zz])|([+-])([01][0-9]|2[0-3]):([0-5][0-9]))?)?`)
	localTime = regexp.MustCompile(`^` + clock)
	number    = regexp.MustCompile(`^(?:0(?:x[0-9A-Fa-f](?:_?[0-9A-Fa-f])*|b[01](?:_?[01])*|o[0-7](?:_?[0-7])*)|[+-]?(?:0|[1-9](?:_?[0-9])*)((?:\.[0-9](?:_?[0-9])*)?(?:[eE][+-]?[0-9](?:_?[0-9])*)?))`)
)

func (p *parser) value() (any, error) {
	switch {
	case p.at(`"""`):
		return p.multiline(`"`)
	case p.at(`"`):
		p.pos++
		return p.basic(false)
	case p.at("'''"):
		return p.multiline("'")
	case p.at("'"):
		return p.literal()
	case p.at("true"):
		p.pos += 4
		return true, nil
	case p.at("false"):
		p.pos += 5
		return false, nil
	case p.at("["):
		return p.array()
	case p.at("{"):
		return p.inline()
	}
	rest := p.text[p.pos:]
	if match := dateTime.FindStringSubmatch(rest); match != nil {
		moment, ok := dated(match)
		if !ok {
			return nil, p.problem(p.pos, "Invalid date or datetime")
		}
		p.pos += len(match[0])
		return moment, nil
	}
	if match := localTime.FindStringSubmatch(rest); match != nil {
		p.pos += len(match[0])
		return timeOn(0, 1, 1, match[1:], time.UTC), nil
	}
	if match := number.FindStringSubmatch(rest); match != nil {
		p.pos += len(match[0])
		raw := strings.ReplaceAll(match[0], "_", "")
		if match[1] != "" {
			parsed, _ := strconv.ParseFloat(raw, 64) // past float64's range it is infinite, as Python's
			return parsed, nil
		}
		parsed, _ := new(big.Int).SetString(raw, 0)
		return parsed, nil
	}
	for _, sign := range []string{"", "+", "-"} {
		if strings.HasPrefix(rest, sign+"inf") || strings.HasPrefix(rest, sign+"nan") {
			p.pos += len(sign) + 3
			if strings.HasPrefix(rest, sign+"nan") {
				return math.NaN(), nil
			}
			if sign == "-" {
				return math.Inf(-1), nil
			}
			return math.Inf(1), nil
		}
	}
	return nil, p.problem(p.pos, "Invalid value")
}

// dated is what a date and time match holds; false where Python's date holds no such day.
func dated(match []string) (time.Time, bool) {
	year, _ := strconv.Atoi(match[1])
	month, _ := strconv.Atoi(match[2])
	day, _ := strconv.Atoi(match[3])
	zone := time.UTC
	if match[9] != "" {
		hours, _ := strconv.Atoi(match[10])
		minutes, _ := strconv.Atoi(match[11])
		offset := hours*3600 + minutes*60
		if match[9] == "-" {
			offset = -offset
		}
		zone = time.FixedZone("", offset)
	}
	moment := timeOn(year, month, day, match[4:8], zone)
	return moment, year >= 1 && moment.Day() == day
}

// timeOn is the day at a clock's hour, minute, second and fraction, none where they are empty.
func timeOn(year, month, day int, parts []string, zone *time.Location) time.Time {
	var at [3]int
	for i := range at {
		at[i], _ = strconv.Atoi(parts[i])
	}
	micros, _ := strconv.Atoi((parts[3] + "000000")[:6])
	return time.Date(year, time.Month(month), day, at[0], at[1], at[2], micros*1000, zone)
}
