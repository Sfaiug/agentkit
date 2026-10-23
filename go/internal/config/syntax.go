package config

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

// Syntax is independent of the models and providers that later milestones load.
// In particular, help never calls it and this reader never creates a config file.
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
		case '\r', '\n':
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
	if !utf8.ValidString(text) {
		return fmt.Errorf("config is not valid UTF-8")
	}
	p := parser{text: text}
	for i, c := range text {
		if (c < 0x20 && c != '\t' && c != '\r' && c != '\n') || c == 0x7f || (c == '\r' && !strings.HasPrefix(text[i:], "\r\n")) {
			p.pos = i
			return p.problem("Invalid character")
		}
	}
	for p.space(true); p.pos < len(text); p.space(true) {
		if p.take("[") {
			array := p.take("[")
			if err := p.key(); err != nil {
				return err
			}
			if !p.take("]") || (array && !p.take("]")) {
				return p.problem("Expected ']' at the end of a table declaration")
			}
		} else {
			if err := p.pair(); err != nil {
				return err
			}
		}
		p.space(false)
		if p.pos < len(text) && !p.take("\r\n") && !p.take("\n") {
			return p.problem("Expected newline or end of document after a statement")
		}
	}
	return nil
}

func (p *parser) key() error {
	for {
		p.space(false)
		if p.pos < len(p.text) && (p.text[p.pos] == '\'' || p.text[p.pos] == '"') {
			if err := p.quoted(false); err != nil {
				return err
			}
		} else {
			start := p.pos
			for p.pos < len(p.text) && strings.ContainsRune("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-", rune(p.text[p.pos])) {
				p.pos++
			}
			if p.pos == start {
				return p.problem("Invalid initial character for a key part")
			}
		}
		p.space(false)
		if !p.take(".") {
			return nil
		}
	}
}

func (p *parser) pair() error {
	if err := p.key(); err != nil {
		return err
	}
	if !p.take("=") {
		return p.problem("Expected '=' after a key in a key/value pair")
	}
	p.space(false)
	return p.value()
}

var number = regexp.MustCompile(`^[+-]?(?:inf|nan|(?:0|[1-9](?:_?[0-9])*)(?:\.[0-9](?:_?[0-9])*)?(?:[eE][+-]?[0-9](?:_?[0-9])*)?)$|^0(?:x[0-9a-fA-F](?:_?[0-9a-fA-F])*|o[0-7](?:_?[0-7])*|b[01](?:_?[01])*)$`)

func (p *parser) value() error {
	if p.pos == len(p.text) {
		return p.problem("Invalid value")
	}
	switch p.text[p.pos] {
	case '\'', '"':
		return p.quoted(true)
	case '[':
		p.pos++
		p.space(true)
		for !p.take("]") {
			if err := p.value(); err != nil {
				return err
			}
			p.space(true)
			if p.take("]") {
				return nil
			}
			if !p.take(",") {
				return p.problem("Unclosed array")
			}
			p.space(true)
		}
		return nil
	case '{':
		p.pos++
		p.space(false)
		if p.take("}") {
			return nil
		}
		for {
			if err := p.pair(); err != nil {
				return err
			}
			p.space(false)
			if p.take("}") {
				return nil
			}
			if !p.take(",") {
				return p.problem("Unclosed inline table")
			}
		}
	}
	start := p.pos
	for p.pos < len(p.text) && !strings.ContainsRune(",]}#\r\n", rune(p.text[p.pos])) {
		p.pos++
	}
	value := strings.TrimSpace(p.text[start:p.pos])
	if value == "true" || value == "false" || number.MatchString(value) {
		return nil
	}
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05.999999999", "2006-01-02", "15:04:05.999999999"} {
		if _, err := time.Parse(layout, strings.ReplaceAll(strings.ToUpper(value), " ", "T")); err == nil {
			return nil
		}
	}
	p.pos = start
	return p.problem("Invalid value")
}

func (p *parser) quoted(multiline bool) error {
	quote := p.text[p.pos : p.pos+1]
	delimiter := quote
	if multiline && strings.HasPrefix(p.text[p.pos:], strings.Repeat(quote, 3)) {
		delimiter = strings.Repeat(quote, 3)
	}
	p.pos += len(delimiter)
	for p.pos < len(p.text) {
		if p.take(delimiter) {
			if len(delimiter) == 3 {
				for i := 0; i < 2 && p.take(quote); i++ {
				}
			}
			return nil
		}
		c := p.text[p.pos]
		if (c < 0x20 && c != '\t' && !(len(delimiter) == 3 && (c == '\n' || c == '\r'))) || c == 0x7f {
			return p.problem("Illegal character in string")
		}
		p.pos++
		if quote != `"` || c != '\\' {
			continue
		}
		if len(delimiter) == 3 && p.pos < len(p.text) && strings.ContainsRune(" \t\r\n", rune(p.text[p.pos])) {
			for p.pos < len(p.text) && strings.ContainsRune(" \t", rune(p.text[p.pos])) {
				p.pos++
			}
			if !p.take("\r\n") && !p.take("\n") {
				return p.problem("Unescaped '\\' in a string")
			}
			for p.pos < len(p.text) && strings.ContainsRune(" \t\r\n", rune(p.text[p.pos])) {
				p.pos++
			}
			continue
		}
		if p.pos == len(p.text) {
			break
		}
		escape := p.text[p.pos]
		p.pos++
		if strings.ContainsRune(`btnfr"\`, rune(escape)) {
			continue
		}
		count := 0
		if escape == 'u' {
			count = 4
		} else if escape == 'U' {
			count = 8
		}
		if count == 0 || p.pos+count > len(p.text) {
			return p.problem("Unescaped '\\' in a string")
		}
		for _, c := range p.text[p.pos : p.pos+count] {
			if !strings.ContainsRune("0123456789abcdefABCDEF", c) {
				return p.problem("Invalid hex value")
			}
		}
		code, _ := strconv.ParseUint(p.text[p.pos:p.pos+count], 16, 32)
		if code > utf8.MaxRune || !utf8.ValidRune(rune(code)) {
			return p.problem("Escaped character is not a Unicode scalar value")
		}
		p.pos += count
	}
	return p.problem("Unterminated string")
}
