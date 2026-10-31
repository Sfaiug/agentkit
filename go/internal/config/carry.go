package config

import (
	"fmt"
	"math"
	"math/big"
	"regexp"
	"strings"
)

var bareKey = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

// Carry is the usual login's TOML settings text with each value a named login's own text holds
// and it lacks carried in, at the top or in a table both hold, as Python's share_settings writes
// it: one top-level key a line, a table inline.  False where it lacks nothing, and the text stays
// as written; an error where either is not TOML, or a value is one Go writes no TOML for.
func Carry(usual, own string) (string, bool, error) {
	shared, err := parseDocument(usual)
	if err != nil {
		return "", false, err
	}
	theirs, err := parseDocument(own)
	if err != nil || !fill(shared, theirs) {
		return "", false, err
	}
	var text strings.Builder
	for _, key := range shared.keys {
		value, err := tomlValue(shared.values[key])
		if err != nil {
			return "", false, err
		}
		fmt.Fprintf(&text, "%s = %s\n", tomlKey(key), value)
	}
	// what Python's json.dumps writes for a string may still be no TOML
	_, err = parseDocument(text.String())
	return text.String(), err == nil, err
}

// TOML is why text is no TOML, nil where it is.
func TOML(text string) error {
	return syntax(text)
}

// fill puts each of own's values shared lacks into shared, tables both hold filled in turn.
func fill(shared, own *table) (changed bool) {
	for _, key := range own.keys {
		mine, theirs := shared.values[key], own.values[key]
		if mine == nil {
			shared.put(key, theirs)
			changed = true
		} else if mine, ok := mine.(*table); ok {
			if theirs, ok := theirs.(*table); ok {
				changed = fill(mine, theirs) || changed
			}
		}
	}
	return changed
}

func tomlKey(key string) string {
	if bareKey.MatchString(key) {
		return key
	}
	return jsonString(key)
}

// tomlValue is a value as Python's _toml_value writes what tomllib read of it.
func tomlValue(value any) (string, error) {
	var items []any
	switch value := value.(type) {
	case bool:
		return fmt.Sprint(value), nil
	case *big.Int:
		return value.String(), nil
	case float64:
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return "", fmt.Errorf("cannot write %s: not a TOML number", valueRepr(value))
		}
		return valueRepr(value), nil
	case string:
		return jsonString(value), nil
	case []any:
		items = value
	case tableArray:
		for _, row := range value {
			items = append(items, row)
		}
	case *table:
		parts := make([]string, len(value.keys))
		for i, key := range value.keys {
			item, err := tomlValue(value.values[key])
			if err != nil {
				return "", err
			}
			parts[i] = tomlKey(key) + " = " + item
		}
		return "{" + strings.Join(parts, ", ") + "}", nil
	default:
		// a date or a time, whose kind and offset Go's reading does not keep as Python's does
		return "", fmt.Errorf("cannot write %v: the Go build writes no TOML date or time", value)
	}
	parts := make([]string, len(items))
	for i, item := range items {
		text, err := tomlValue(item)
		if err != nil {
			return "", err
		}
		parts[i] = text
	}
	return "[" + strings.Join(parts, ", ") + "]", nil
}

// jsonString is text as Python's json.dumps(text, ensure_ascii=False) writes it.
func jsonString(text string) string {
	var out strings.Builder
	out.WriteByte('"')
	for _, r := range text {
		switch r {
		case '"', '\\':
			out.WriteString(`\` + string(r))
		case '\n':
			out.WriteString(`\n`)
		case '\r':
			out.WriteString(`\r`)
		case '\t':
			out.WriteString(`\t`)
		case '\b':
			out.WriteString(`\b`)
		case '\f':
			out.WriteString(`\f`)
		default:
			if r < ' ' {
				fmt.Fprintf(&out, `\u%04x`, r)
			} else {
				out.WriteRune(r)
			}
		}
	}
	out.WriteByte('"')
	return out.String()
}
