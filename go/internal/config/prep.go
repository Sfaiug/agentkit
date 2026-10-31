package config

import (
	"fmt"
	"os"
	"slices"
	"strings"
)

// A PrepTable is a manifest's `[prep]`, for the login a call is on and a seat's folder: what its
// harness must find answered before it starts.
type PrepTable struct {
	// File holds the answers; Usual is the usual login's, on a named login with a file of its own.
	File, Usual string
	// Reads are other files the harness starts on, which nothing is answered in.
	Reads []string
	// Links are what a named login's home links from the usual login's.
	Links   []string
	Answers []Answer
}

// An Answer is one value File must hold: the keys leading to it, and whether it gives way to
// anything File already holds there.
type Answer struct {
	Path    []string
	Value   any // a string or a bool
	Default bool
}

// Prep is the harness's `[prep]` table for a seat in folder, false where its manifest has none.
func Prep(harness, folder string) (PrepTable, bool, error) {
	manifests, err := manifests()
	root := manifests[harness]
	prep, _ := root.get("prep").(*table)
	file, _ := prep.get("file").(string)
	if err != nil || file == "" {
		return PrepTable{}, false, err
	}
	found := PrepTable{File: Expand(file), Links: words(root, "prep", "links")}
	if own, _ := prep.get("account").(string); own != "" && os.Getenv("AGENTKIT_ACCOUNT") != "" {
		found.Usual = found.File
		found.File = strings.ReplaceAll(Expand(own), "{home}", loginHome(root))
	}
	for _, path := range words(root, "prep", "reads") {
		found.Reads = append(found.Reads, Expand(path))
	}
	answers, _ := prep.get("answers").(*table)
	defaults, _ := prep.get("defaults").(*table)
	if err := found.add(answers, nil, folder, false); err != nil {
		return PrepTable{}, false, fmt.Errorf("adapter manifest %s.toml: %w", harness, err)
	}
	if err := found.add(defaults, nil, folder, true); err != nil {
		return PrepTable{}, false, fmt.Errorf("adapter manifest %s.toml: %w", harness, err)
	}
	return found, true, nil
}

// add appends what block holds, under path, in the table's order.
func (prep *PrepTable) add(block *table, path []string, folder string, fallback bool) error {
	if block == nil {
		return nil
	}
	for _, key := range block.keys {
		at := append(slices.Clone(path), strings.ReplaceAll(key, "{folder}", folder))
		switch value := block.values[key].(type) {
		case *table:
			if err := prep.add(value, at, folder, fallback); err != nil {
				return err
			}
		case bool, string:
			prep.Answers = append(prep.Answers, Answer{at, value, fallback})
		default:
			return fmt.Errorf("[prep] %s is neither a string nor a boolean", key)
		}
	}
	return nil
}
