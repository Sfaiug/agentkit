package config

import (
	"fmt"
	"math"
	"math/big"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

type table struct {
	values                   map[string]any
	keys                     []string
	declared, dotted, frozen bool
}

type tableArray []*table

func newTable() *table { return &table{values: map[string]any{}} }

func (t *table) put(key string, value any) {
	if _, exists := t.values[key]; !exists {
		t.keys = append(t.keys, key)
	}
	t.values[key] = value
}

func (t *table) child(key string, dotted bool) (*table, bool) {
	if t.frozen {
		return nil, false
	}
	value, exists := t.values[key]
	if !exists {
		child := newTable()
		child.dotted = dotted
		t.put(key, child)
		return child, true
	}
	switch child := value.(type) {
	case *table:
		return child, !child.frozen
	case tableArray:
		return child[len(child)-1], true
	}
	return nil, false
}

func (t *table) assign(keys []string, value any) bool {
	for _, key := range keys[:len(keys)-1] {
		var ok bool
		t, ok = t.child(key, true)
		if !ok {
			return false
		}
	}
	key := keys[len(keys)-1]
	if _, exists := t.values[key]; exists || t.frozen {
		return false
	}
	t.put(key, value)
	return true
}

func (t *table) section(keys []string, array bool) (*table, bool) {
	for _, key := range keys[:len(keys)-1] {
		var ok bool
		t, ok = t.child(key, false)
		if !ok {
			return nil, false
		}
	}
	key := keys[len(keys)-1]
	value, exists := t.values[key]
	if array {
		var rows tableArray
		if exists {
			var ok bool
			rows, ok = value.(tableArray)
			if !ok {
				return nil, false
			}
		}
		child := newTable()
		child.declared = true
		t.put(key, append(rows, child))
		return child, true
	}
	if !exists {
		value = newTable()
		t.put(key, value)
	}
	child, ok := value.(*table)
	if !ok || child.declared || child.dotted || child.frozen {
		return nil, false
	}
	child.declared = true
	return child, true
}

func (t *table) freeze() {
	t.frozen = true
	for _, value := range t.values {
		if child, ok := value.(*table); ok {
			child.freeze()
		}
	}
}

type parser struct {
	text string
	pos  int
}

func (p *parser) problem(message string) error {
	line := strings.Count(p.text[:p.pos], "\n") + 1
	column := utf8.RuneCountInString(p.text[strings.LastIndex(p.text[:p.pos], "\n")+1:p.pos]) + 1
	return fmt.Errorf("%s (at line %d, column %d)", message, line, column)
}

func (p *parser) take(text string) bool {
	if !strings.HasPrefix(p.text[p.pos:], text) {
		return false
	}
	p.pos += len(text)
	return true
}

func (p *parser) space(newlines bool) {
	for p.pos < len(p.text) {
		switch p.text[p.pos] {
		case ' ', '\t':
			p.pos++
		case '\n':
			if !newlines {
				return
			}
			p.pos++
		case '#':
			for p.pos < len(p.text) && p.text[p.pos] != '\n' {
				p.pos++
			}
		default:
			return
		}
	}
}

func syntax(text string) error {
	_, err := parseDocument(text)
	return err
}

func parseDocument(text string) (*table, error) {
	if !utf8.ValidString(text) {
		return nil, fmt.Errorf("config is not valid UTF-8")
	}
	p := parser{text: text}
	for i, c := range text {
		if (c < 0x20 && c != '\t' && c != '\r' && c != '\n') || c == 0x7f || (c == '\r' && !strings.HasPrefix(text[i:], "\r\n")) {
			p.pos = i
			return nil, p.problem("Invalid character")
		}
	}
	p.text = strings.ReplaceAll(text, "\r\n", "\n")
	root := newTable()
	current := root
	for p.space(true); p.pos < len(p.text); p.space(true) {
		if p.take("[") {
			array := p.take("[")
			keys, err := p.key()
			if err != nil {
				return nil, err
			}
			if !p.take("]") || (array && !p.take("]")) {
				return nil, p.problem("Expected ']' at the end of a table declaration")
			}
			var ok bool
			current, ok = root.section(keys, array)
			if !ok {
				return nil, p.problem("Cannot declare a table twice or overwrite a value")
			}
		} else if err := p.pair(current); err != nil {
			return nil, err
		}
		p.space(false)
		if p.pos < len(p.text) && !p.take("\n") {
			return nil, p.problem("Expected newline or end of document after a statement")
		}
	}
	return root, nil
}

func (p *parser) key() ([]string, error) {
	var keys []string
	for {
		p.space(false)
		var key string
		if p.pos < len(p.text) && (p.text[p.pos] == '\'' || p.text[p.pos] == '"') {
			var err error
			key, err = p.quoted(false)
			if err != nil {
				return nil, err
			}
		} else {
			start := p.pos
			for p.pos < len(p.text) && strings.ContainsRune("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-", rune(p.text[p.pos])) {
				p.pos++
			}
			if p.pos == start {
				return nil, p.problem("Invalid initial character for a key part")
			}
			key = p.text[start:p.pos]
		}
		keys = append(keys, key)
		p.space(false)
		if !p.take(".") {
			return keys, nil
		}
	}
}

func (p *parser) pair(target *table) error {
	keys, err := p.key()
	if err != nil {
		return err
	}
	if !p.take("=") {
		return p.problem("Expected '=' after a key in a key/value pair")
	}
	p.space(false)
	value, err := p.value()
	if err != nil {
		return err
	}
	if !target.assign(keys, value) {
		return p.problem("Cannot overwrite a value")
	}
	return nil
}

var number = regexp.MustCompile(`^[+-]?(?:inf|nan|(?:0|[1-9](?:_?[0-9])*)(?:\.[0-9](?:_?[0-9])*)?(?:[eE][+-]?[0-9](?:_?[0-9])*)?)$|^0(?:x[0-9a-fA-F](?:_?[0-9a-fA-F])*|o[0-7](?:_?[0-7])*|b[01](?:_?[01])*)$`)

func (p *parser) value() (any, error) {
	if p.pos == len(p.text) {
		return nil, p.problem("Invalid value")
	}
	switch p.text[p.pos] {
	case '\'', '"':
		return p.quoted(true)
	case '[':
		p.pos++
		p.space(true)
		values := []any{}
		for !p.take("]") {
			value, err := p.value()
			if err != nil {
				return nil, err
			}
			values = append(values, value)
			p.space(true)
			if p.take("]") {
				return values, nil
			}
			if !p.take(",") {
				return nil, p.problem("Unclosed array")
			}
			p.space(true)
		}
		return values, nil
	case '{':
		p.pos++
		p.space(false)
		value := newTable()
		if !p.take("}") {
			for {
				if err := p.pair(value); err != nil {
					return nil, err
				}
				p.space(false)
				if p.take("}") {
					break
				}
				if !p.take(",") {
					return nil, p.problem("Unclosed inline table")
				}
			}
		}
		value.freeze()
		return value, nil
	}
	start := p.pos
	for p.pos < len(p.text) && !strings.ContainsRune(",]}#\n", rune(p.text[p.pos])) {
		p.pos++
	}
	value := strings.TrimSpace(p.text[start:p.pos])
	if value == "true" || value == "false" {
		return value == "true", nil
	}
	if number.MatchString(value) {
		raw := strings.ReplaceAll(value, "_", "")
		switch strings.TrimLeft(raw, "+-") {
		case "nan":
			return math.NaN(), nil
		case "inf":
			if raw[0] == '-' {
				return math.Inf(-1), nil
			}
			return math.Inf(1), nil
		}
		base := 10
		if strings.HasPrefix(raw, "0x") || strings.HasPrefix(raw, "0o") || strings.HasPrefix(raw, "0b") {
			base = 0
		} else if strings.ContainsAny(raw, ".eE") {
			parsed, err := strconv.ParseFloat(raw, 64)
			if err != nil && !math.IsInf(parsed, 0) {
				return nil, p.problem("Invalid value")
			}
			return parsed, nil
		}
		parsed, ok := new(big.Int).SetString(raw, base)
		if ok {
			return parsed, nil
		}
	}
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05.999999999", "2006-01-02", "15:04:05.999999999"} {
		if parsed, err := time.Parse(layout, strings.ReplaceAll(strings.ToUpper(value), " ", "T")); err == nil {
			return parsed, nil
		}
	}
	p.pos = start
	return nil, p.problem("Invalid value")
}

func (p *parser) quoted(multiline bool) (string, error) {
	quote := p.text[p.pos : p.pos+1]
	delimiter := quote
	if multiline && strings.HasPrefix(p.text[p.pos:], strings.Repeat(quote, 3)) {
		delimiter = strings.Repeat(quote, 3)
	}
	p.pos += len(delimiter)
	if len(delimiter) == 3 {
		p.take("\n")
	}
	var out strings.Builder
	for p.pos < len(p.text) {
		if p.take(delimiter) {
			if len(delimiter) == 3 {
				for i := 0; i < 2 && p.take(quote); i++ {
					out.WriteString(quote)
				}
			}
			return out.String(), nil
		}
		c := p.text[p.pos]
		if (c < 0x20 && c != '\t' && !(len(delimiter) == 3 && c == '\n')) || c == 0x7f {
			return "", p.problem("Illegal character in string")
		}
		p.pos++
		if quote != `"` || c != '\\' {
			out.WriteByte(c)
			continue
		}
		if len(delimiter) == 3 && p.pos < len(p.text) && strings.ContainsRune(" \t\n", rune(p.text[p.pos])) {
			for p.pos < len(p.text) && strings.ContainsRune(" \t", rune(p.text[p.pos])) {
				p.pos++
			}
			if !p.take("\n") {
				return "", p.problem("Unescaped '\\' in a string")
			}
			for p.pos < len(p.text) && strings.ContainsRune(" \t\n", rune(p.text[p.pos])) {
				p.pos++
			}
			continue
		}
		if p.pos == len(p.text) {
			break
		}
		escape := p.text[p.pos]
		p.pos++
		if index := strings.IndexByte("btnfr\"\\", escape); index >= 0 {
			out.WriteByte("\b\t\n\f\r\"\\"[index])
			continue
		}
		count := 0
		if escape == 'u' {
			count = 4
		} else if escape == 'U' {
			count = 8
		}
		if count == 0 || p.pos+count > len(p.text) {
			return "", p.problem("Unescaped '\\' in a string")
		}
		code, err := strconv.ParseUint(p.text[p.pos:p.pos+count], 16, 32)
		if err != nil {
			return "", p.problem("Invalid hex value")
		}
		if code > utf8.MaxRune || !utf8.ValidRune(rune(code)) {
			return "", p.problem("Escaped character is not a Unicode scalar value")
		}
		out.WriteRune(rune(code))
		p.pos += count
	}
	return "", p.problem("Unterminated string")
}
