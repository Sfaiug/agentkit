package config

import (
	"maps"
	"regexp"
	"slices"
	"strings"
	"unicode"
	"unicode/utf8"
)

// ModelName is the full name every screen shows the configured model by (config.model_name): what
// its harness runs it as, named by ModelLabel off the entry's own label where it has one, else its
// id; the name itself where it is no entry or names no id of its own.
func ModelName(name string, models map[string]Model) string {
	model, listed := models[name]
	if !listed || model.ID == "" || model.ID == "default" {
		return name
	}
	return ModelLabel(model.Harness, model.ID, model.Label)
}

var trailingDate = regexp.MustCompile(`-[0-9]{8}$`)

// ModelLabel is what every screen calls the model a harness runs as id and lists as said
// (config.model_label): its manifest's catalog label for that id, else its name and number read
// off said, else the id. A provider's prefix and a trailing date are no part of that name, and the
// rest is Spoken: a harness runs other makers' models too, and `acme-nova-7-1` is `Nova 7.1`
// whichever runs it.
func ModelLabel(harness, id, said string) string {
	catalog, _ := Tree(harness, "catalog")
	if entry, ok := catalog[id].(map[string]any); ok {
		if label, ok := entry["label"].(string); ok && label != "" {
			return label
		}
	}
	if said == "" {
		said = id
	}
	return Spoken(trailingDate.ReplaceAllString(said[strings.LastIndexByte(said, '/')+1:], ""))
}

// Spoken is name as ak says a model's, a seat's (ModelLabel) or a board's release
// (config.spoken of config.families, config.release_label): without its maker's family word, the
// first manifest's `family`, by harness name, it opens with, unless only numbers follow. A hyphen
// is a space, between two numbers a point, and a word in small letters opens with a capital: where
// the family word is `Acme`, `acme-nova-7-1` is `Nova 7.1`, `ACME-7.2-Vega` is `7.2 Vega` and
// `acme-7` is `Acme 7`.
func Spoken(name string) string {
	found, _ := manifests()
	for _, harness := range slices.Sorted(maps.Keys(found)) {
		family, _ := found[harness].get("family").(string)
		if n := len(family); n > 0 && len(name) >= n && strings.EqualFold(name[:n], family) &&
			(len(name) == n || name[n] == '-' || name[n] == ' ') {
			if rest := name[min(n+1, len(name)):]; strings.Trim(rest, "0123456789.- ") == "" {
				name = family + name[n:]
			} else {
				name = rest
			}
			break
		}
	}
	spelled := []byte(name)
	for i := 1; i+1 < len(spelled); i++ {
		if spelled[i] == '-' && isDigit(name[i-1]) && isDigit(name[i+1]) {
			spelled[i] = '.'
		}
	}
	words := strings.Fields(strings.ReplaceAll(string(spelled), "-", " "))
	for i, word := range words {
		if strings.ToLower(word) == word && strings.ToUpper(word) != word {
			first, size := utf8.DecodeRuneInString(word)
			words[i] = string(unicode.ToUpper(first)) + word[size:]
		}
	}
	return strings.Join(words, " ")
}

func isDigit(b byte) bool { return '0' <= b && b <= '9' }

// ModelAt is how every screen names model `name` at its effort `key` (RoleEfforts, else
// `effort`) in `models`, a seat's as it runs them (config.model_at): its full name, then that
// effort, alone where it is none.
func ModelAt(name, key string, models map[string]Model) string {
	efforts := models[name].Efforts
	effort, set := efforts[key]
	if !set {
		effort = efforts["effort"]
	}
	if effort == "" || effort == "none" {
		return ModelName(name, models)
	}
	return ModelName(name, models) + " " + effort
}
