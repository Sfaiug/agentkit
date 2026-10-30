package run

import (
	"bytes"
	"errors"
	"fmt"
	"math"
	"math/big"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"unicode/utf16"
	"unicode/utf8"

	"agentkit/internal/config"
)

// A record is read as Python's json module reads one.  Values are nil, bool, Number, string,
// []any and *Object.

// A Number is a JSON number's text: Python's int or float, NaN and Infinity among them.
type Number string

// An Object is a JSON object as Python keeps one: keys in the order they came, a repeated
// key's last value at its first place.
type Object struct {
	keys   []string
	values map[string]any
}

func NewObject() *Object {
	return &Object{values: map[string]any{}}
}

func (o *Object) Get(key string) any {
	return o.values[key]
}

func (o *Object) Has(key string) bool {
	_, ok := o.values[key]
	return ok
}

// Keys is the object's keys in the order they came.
func (o *Object) Keys() []string {
	return slices.Clone(o.keys)
}

// Set puts a value under the key, an int or float64 as the JSON number it is.
func (o *Object) Set(key string, value any) {
	switch given := value.(type) {
	case int:
		value = Number(strconv.Itoa(given))
	case float64:
		value = Float(given)
	}
	if _, ok := o.values[key]; !ok {
		o.keys = append(o.keys, key)
	}
	o.values[key] = value
}

// Delete removes the key, if the object holds it.
func (o *Object) Delete(key string) {
	if _, ok := o.values[key]; ok {
		delete(o.values, key)
		o.keys = slices.DeleteFunc(o.keys, func(held string) bool { return held == key })
	}
}

// Copy is a shallow copy: what a listing changes for display, never the record read.
func (o *Object) Copy() *Object {
	copied := &Object{append([]string(nil), o.keys...), make(map[string]any, len(o.values))}
	for key, value := range o.values {
		copied.values[key] = value
	}
	return copied
}

// Str is the key's string, "" for anything else.
func (o *Object) Str(key string) string {
	text, _ := o.values[key].(string)
	return text
}

// Num is the key's number; a bool is no number.
func (o *Object) Num(key string) (float64, bool) {
	return Num(o.values[key])
}

// Int is the key's number where it is a JSON integer, as Python reads one as an int.
func (o *Object) Int(key string) (int, bool) {
	text, ok := o.values[key].(Number)
	if !ok || strings.ContainsAny(string(text), ".eEIN") {
		return 0, false
	}
	parsed, err := strconv.Atoi(string(text))
	return parsed, err == nil
}

// Dict is the key's object, nil for anything else.
func (o *Object) Dict(key string) *Object {
	found, _ := o.values[key].(*Object)
	return found
}

// List is the key's list, nil for anything else.
func (o *Object) List(key string) []any {
	found, _ := o.values[key].([]any)
	return found
}

// Truthy is whether Python reads the key's value as true.
func (o *Object) Truthy(key string) bool {
	return truthy(o.values[key])
}

// Num is a JSON number's value; a bool is no number.
func Num(value any) (float64, bool) {
	text, ok := value.(Number)
	if !ok {
		return 0, false
	}
	switch text {
	case "NaN":
		return math.NaN(), true
	case "Infinity":
		return math.Inf(1), true
	case "-Infinity":
		return math.Inf(-1), true
	}
	parsed, _ := strconv.ParseFloat(string(text), 64) // past its range: infinite or 0, as to Python
	return parsed, true
}

// integral is whether Python reads the number as an int.
func integral(value Number) bool {
	return !strings.ContainsAny(string(value), ".eEIN")
}

// Float is a number as Python's repr writes a float.
func Float(value float64) Number {
	switch {
	case math.IsNaN(value):
		return "NaN"
	case math.IsInf(value, 1):
		return "Infinity"
	case math.IsInf(value, -1):
		return "-Infinity"
	}
	text := strconv.FormatFloat(value, 'e', -1, 64)
	if exponent, _ := strconv.Atoi(text[strings.IndexByte(text, 'e')+1:]); exponent < -4 || exponent >= 16 {
		return Number(text)
	}
	text = strconv.FormatFloat(value, 'f', -1, 64)
	if !strings.Contains(text, ".") {
		text += ".0"
	}
	return Number(text)
}

// written is a number as json.dumps writes what Python read of it: an int's digits, a
// float's repr.
func written(value Number) string {
	if integral(value) {
		whole, _ := new(big.Int).SetString(string(value), 10)
		return whole.String() // -0 is 0
	}
	parsed, _ := Num(value)
	return string(Float(parsed))
}

func truthy(value any) bool {
	switch value := value.(type) {
	case nil:
		return false
	case bool:
		return value
	case string:
		return value != ""
	case Number:
		parsed, _ := Num(value)
		return parsed != 0
	case []any:
		return len(value) > 0
	case *Object:
		return len(value.keys) > 0
	}
	return true
}

// Equal is Python's == between two JSON values: numbers by value, true as 1, objects
// whatever the order of their keys.
func Equal(a, b any) bool {
	if x, ok := numeric(a); ok {
		y, ok := numeric(b)
		return ok && x == y
	}
	switch a := a.(type) {
	case nil:
		return b == nil
	case string:
		text, ok := b.(string)
		return ok && a == text
	case []any:
		list, ok := b.([]any)
		if !ok || len(list) != len(a) {
			return false
		}
		for i := range a {
			if !Equal(a[i], list[i]) {
				return false
			}
		}
		return true
	case *Object:
		object, ok := b.(*Object)
		if !ok || len(object.keys) != len(a.keys) {
			return false
		}
		for key, value := range a.values {
			if other, ok := object.values[key]; !ok || !Equal(value, other) {
				return false
			}
		}
		return true
	}
	return false
}

// numeric is a number or a bool as the number Python compares it as.
func numeric(value any) (float64, bool) {
	if flag, ok := value.(bool); ok {
		if flag {
			return 1, true
		}
		return 0, true
	}
	return Num(value)
}

// ErrLoneSurrogate is a \ud800-\udfff escape that is not half of a pair: Python reads it, and
// a Go string cannot keep it.
var ErrLoneSurrogate = errors.New("a lone surrogate")

// ErrLimit is JSON that Python reads or refuses as the limits it runs under say: an int longer
// than the config.MinDigits every PYTHONINTMAXSTRDIGITS lets it convert, or nesting deeper
// than maxDepth.
var ErrLimit = errors.New("past a limit Python runs under")

// Decode reads one JSON value as Python's json.loads does, NaN and Infinity numbers among
// what it reads, and refuses what it refuses in its words.  Text that is not UTF-8 is
// unreadable, as it is to Python.
func Decode(data []byte) (any, error) {
	return decode(&parser{data: data})
}

// DecodeLimited reads one JSON value as Decode does, and answers ErrLimit where Python's limits
// decide whether it reads the value.
func DecodeLimited(data []byte) (any, error) {
	return decode(&parser{data: data, limited: true})
}

// DecodeShown reads one JSON value as DecodeLimited does, for what Go only reads and shows: a
// lone surrogate, which Python reads and its print cannot write, is U+FFFD.
func DecodeShown(data []byte) (any, error) {
	return decode(&parser{data: data, limited: true, shown: true})
}

func decode(p *parser) (any, error) {
	if !utf8.Valid(p.data) {
		return nil, fmt.Errorf("not UTF-8")
	}
	if bytes.HasPrefix(p.data, []byte("\ufeff")) {
		return nil, p.fail("Unexpected UTF-8 BOM (decode using utf-8-sig)", 0)
	}
	value, err := p.value(0)
	if err != nil {
		return nil, err
	}
	if p.space(); p.at < len(p.data) {
		return nil, p.fail("Extra data", p.at)
	}
	return value, nil
}

type parser struct {
	data    []byte
	at      int
	limited bool // ErrLimit where Python's limits decide
	shown   bool // a lone surrogate as U+FFFD
}

var numberRe = regexp.MustCompile(`^(-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][-+]?[0-9]+)?|NaN|-?Infinity)`)

// maxDepth is the deepest nesting a limited read takes: Python's json recurses once a level, and
// before 3.12 the 1000 frames of its recursion limit, ak's own among them, end it short of 1000.
const maxDepth = 500

func (p *parser) space() {
	for p.at < len(p.data) && strings.IndexByte(" \t\n\r", p.data[p.at]) >= 0 {
		p.at++
	}
}

// fail is the message as Python's JSONDecodeError says it of the byte at: its line, column and
// place in characters.
func (p *parser) fail(message string, at int) error {
	before := p.data[:at]
	line := bytes.LastIndexByte(before, '\n')
	return fmt.Errorf("%s: line %d column %d (char %d)", message, bytes.Count(before, []byte("\n"))+1,
		utf8.RuneCount(before[line+1:])+1, utf8.RuneCount(before))
}

// after reads what follows an object's or array's item: its closing bracket, true, or a comma
// and the space before the next item, a trailing one refused as Python 3.13 refuses it.
func (p *parser) after(closing, kind string) (bool, error) {
	if p.space(); p.take(closing) {
		return true, nil
	}
	if !p.take(",") {
		return false, p.fail("Expecting ',' delimiter", p.at)
	}
	comma := p.at - 1
	if p.space(); p.take(closing) {
		return false, p.fail("Illegal trailing comma before end of "+kind, comma)
	}
	return false, nil
}

// take moves past the word if it comes next.
func (p *parser) take(word string) bool {
	if bytes.HasPrefix(p.data[p.at:], []byte(word)) {
		p.at += len(word)
		return true
	}
	return false
}

func (p *parser) value(depth int) (any, error) {
	if p.limited && depth > maxDepth {
		return nil, ErrLimit
	}
	p.space()
	switch {
	case p.take("{"):
		object := NewObject()
		if p.space(); p.take("}") {
			return object, nil
		}
		for {
			if p.at == len(p.data) || p.data[p.at] != '"' {
				return nil, p.fail("Expecting property name enclosed in double quotes", p.at)
			}
			key, err := p.text()
			if err != nil {
				return nil, err
			}
			if p.space(); !p.take(":") {
				return nil, p.fail("Expecting ':' delimiter", p.at)
			}
			value, err := p.value(depth + 1)
			if err != nil {
				return nil, err
			}
			object.Set(key, value)
			if closed, err := p.after("}", "object"); err != nil {
				return nil, err
			} else if closed {
				return object, nil
			}
		}
	case p.take("["):
		list := []any{}
		if p.space(); p.take("]") {
			return list, nil
		}
		for {
			value, err := p.value(depth + 1)
			if err != nil {
				return nil, err
			}
			list = append(list, value)
			if closed, err := p.after("]", "array"); err != nil {
				return nil, err
			} else if closed {
				return list, nil
			}
		}
	case p.at < len(p.data) && p.data[p.at] == '"':
		return p.text()
	case p.take("true"):
		return true, nil
	case p.take("false"):
		return false, nil
	case p.take("null"):
		return nil, nil
	}
	found := numberRe.Find(p.data[p.at:])
	digits := len(strings.TrimPrefix(string(found), "-"))
	switch {
	case found == nil:
		return nil, p.fail("Expecting value", p.at)
	case p.limited && integral(Number(found)) && digits > config.MinDigits:
		return nil, ErrLimit
	case integral(Number(found)) && digits > config.MaxDigits:
		return nil, fmt.Errorf("Exceeds the limit (%d digits) for integer string conversion: value has %d digits; use sys.set_int_max_str_digits() to increase the limit", config.MaxDigits, digits)
	}
	p.at += len(found)
	return Number(found), nil
}

// text reads a string from its opening quote.
func (p *parser) text() (string, error) {
	start := p.at
	p.at++
	var out []byte
	for {
		if p.at == len(p.data) {
			return "", p.fail("Unterminated string starting at", start)
		}
		c := p.data[p.at]
		p.at++
		switch {
		case c == '"':
			return string(out), nil
		case c < ' ':
			return "", p.fail("Invalid control character at", p.at-1)
		case c != '\\':
			out = append(out, c)
		case p.at == len(p.data):
			return "", p.fail("Unterminated string starting at", start)
		case strings.IndexByte(`"\/bfnrt`, p.data[p.at]) >= 0:
			out = append(out, "\"\\/\b\f\n\r\t"[strings.IndexByte(`"\/bfnrt`, p.data[p.at])])
			p.at++
		case p.data[p.at] != 'u':
			return "", p.fail(`Invalid \escape`, p.at-1)
		default:
			r, err := p.unit()
			if err != nil {
				return "", err
			}
			// a high surrogate pairs with a low one right after it, where Python looks for one
			if next := p.at; r >= 0xd800 && r < 0xdc00 && p.at+6 < len(p.data) && bytes.HasPrefix(p.data[p.at:], []byte(`\u`)) {
				p.at++
				low, err := p.unit()
				if err != nil {
					return "", err
				}
				if low >= 0xdc00 && low <= 0xdfff {
					r = utf16.DecodeRune(r, low)
				} else {
					p.at = next
				}
			}
			if utf16.IsSurrogate(r) && !p.shown {
				return "", ErrLoneSurrogate
			}
			out = utf8.AppendRune(out, r)
		}
	}
}

// unit reads a \u escape's four hex digits from its u, which Python refuses where they end the
// text, a quote still owed.
func (p *parser) unit() (rune, error) {
	u := p.at
	if p.at += 5; p.at >= len(p.data) {
		return 0, p.fail(`Invalid \uXXXX escape`, u)
	}
	parsed, err := strconv.ParseUint(string(p.data[u+1:p.at]), 16, 16)
	if err != nil {
		return 0, p.fail(`Invalid \uXXXX escape`, u)
	}
	return rune(parsed), nil
}

// Encode writes a value as Python's json.dumps(value, indent=2) writes what it read: two-space
// indents, `": "` between key and value, every character past ASCII escaped.
func Encode(value any) string {
	var out strings.Builder
	encode(&out, value, ",", "\n")
	return out.String()
}

// Line writes a value as Python's json.dumps(value) writes what it read: on one line, `", "`
// between items and `": "` between key and value, every character past ASCII escaped.
func Line(value any) string {
	var out strings.Builder
	encode(&out, value, ", ", "")
	return out.String()
}

// encode writes the value with comma between items, each on a line of its own two spaces past
// newline's indent where newline breaks the line.
func encode(out *strings.Builder, value any, comma, newline string) {
	inner := newline
	if newline != "" {
		inner += "  "
	}
	switch value := value.(type) {
	case nil:
		out.WriteString("null")
	case bool:
		out.WriteString(strconv.FormatBool(value))
	case Number:
		out.WriteString(written(value))
	case string:
		out.WriteString(quote(value))
	case []any:
		if len(value) == 0 {
			out.WriteString("[]")
			return
		}
		out.WriteString("[")
		for i, item := range value {
			if i > 0 {
				out.WriteString(comma)
			}
			out.WriteString(inner)
			encode(out, item, comma, inner)
		}
		out.WriteString(newline + "]")
	case *Object:
		if len(value.keys) == 0 {
			out.WriteString("{}")
			return
		}
		out.WriteString("{")
		for i, key := range value.keys {
			if i > 0 {
				out.WriteString(comma)
			}
			out.WriteString(inner + quote(key) + ": ")
			encode(out, value.values[key], comma, inner)
		}
		out.WriteString(newline + "}")
	}
}

// quote is the string as json.dumps writes it, every character past ASCII escaped; a byte of
// a path no UTF-8 holds is the surrogate Python reads it as (os.fsdecode).
func quote(text string) string {
	var out strings.Builder
	out.WriteByte('"')
	for len(text) > 0 {
		r, size := utf8.DecodeRuneInString(text)
		if r == utf8.RuneError && size == 1 {
			r = 0xdc00 | rune(text[0])
		}
		text = text[size:]
		switch {
		case r == '"' || r == '\\':
			out.WriteString(`\` + string(r))
		case r == '\n':
			out.WriteString(`\n`)
		case r == '\r':
			out.WriteString(`\r`)
		case r == '\t':
			out.WriteString(`\t`)
		case r == '\b':
			out.WriteString(`\b`)
		case r == '\f':
			out.WriteString(`\f`)
		case r >= ' ' && r <= '~':
			out.WriteRune(r)
		case r > 0xffff:
			high, low := utf16.EncodeRune(r)
			fmt.Fprintf(&out, `\u%04x\u%04x`, high, low)
		default:
			fmt.Fprintf(&out, `\u%04x`, r)
		}
	}
	out.WriteByte('"')
	return out.String()
}
