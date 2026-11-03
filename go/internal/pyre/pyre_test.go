package pyre

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"unicode/utf8"
)

// a match as tests/test_go_pattern_cases.py writes Python's: its span in characters, its named
// groups null where they took no part
type match struct {
	Fixture string             `json:"fixture"`
	Row     *int               `json:"row"`
	Span    [2]int             `json:"span"`
	Groups  map[string]*string `json:"groups"`
}

// Every pattern Python's watch.screen compiles from a manifest, searched over each row of every
// screen fixture and, one of several rows, its whole text, matches here as Python's matched.
func TestEveryManifestPatternMatchesAsPythonsDoes(t *testing.T) {
	read, err := os.ReadFile("testdata/cases.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases struct {
		Fixtures []string
		Patterns []struct {
			Harness, Key, Pattern, Flags string
			Matches                      []match
		}
	}
	if err := json.Unmarshal(read, &cases); err != nil {
		t.Fatal(err)
	}
	texts := map[string]string{}
	for _, name := range cases.Fixtures {
		text, err := os.ReadFile(filepath.Join("..", "..", "..", "tests", "fixtures", name))
		if err != nil {
			t.Fatal(err)
		}
		texts[name] = string(text)
	}
	for _, each := range cases.Patterns {
		var flags Flag
		if strings.Contains(each.Flags, "i") {
			flags |= IgnoreCase
		}
		if strings.Contains(each.Flags, "m") {
			flags |= Multiline
		}
		compiled, err := Compile(each.Pattern, flags)
		if err != nil {
			t.Errorf("%s %s: %v", each.Harness, each.Key, err)
			continue
		}
		var found []match
		for _, name := range cases.Fixtures {
			searched := func(row *int, text string) {
				if at := compiled.Find(text); at != nil {
					groups := map[string]*string{}
					for _, name := range compiled.engine.GetGroupNames() {
						if _, numbered := strconv.Atoi(name); numbered == nil {
							continue
						}
						if taken, ok := at.Group(name); ok {
							groups[name] = &taken
						} else {
							groups[name] = nil
						}
					}
					span := [2]int{utf8.RuneCountInString(text[:at.Start]), utf8.RuneCountInString(text[:at.End])}
					found = append(found, match{name, row, span, groups})
				}
			}
			if flags&Multiline != 0 {
				searched(nil, texts[name])
			}
			for at, row := range strings.Split(texts[name], "\n") {
				searched(&at, row)
			}
		}
		if !reflect.DeepEqual(found, each.Matches) {
			for at := range max(len(found), len(each.Matches)) {
				var got, want any
				if at < len(found) {
					got = found[at]
				}
				if at < len(each.Matches) {
					want = each.Matches[at]
				}
				if !reflect.DeepEqual(got, want) {
					t.Errorf("%s %s: Go found %s where Python found %s", each.Harness, each.Key, shown(got), shown(want))
					break
				}
			}
		}
	}
}

func shown(found any) string {
	said, _ := json.Marshal(found)
	return string(said)
}

// What Python says that no manifest says yet: each found as Python's re.search finds it ("" none).
func TestPythonsSyntaxAndClasses(t *testing.T) {
	for _, each := range []struct{ pattern, text, found string }{
		{`x{,2}`, "xxx", "xx"},
		{`\bé`, "aé é", "é"},
		{`\w`, "́", ""},
		{`(?P<a>x)(?P=a)`, "yxx", "xx"},
		{`a\Z`, "a\n", ""},
		{`a$`, "a\n", "a"},
		{`[]a]+`, "b]a", "]a"},
		{`[^]a]`, "]ab", "b"},
		{`[x\S]+`, " x\x1cé ", "x"},
		{`[[]`, "a[", "["},
		{`\s+`, "a\x1c b", "\x1c "},
		{`^❯\s+x$`, "❯\u00a0x", "❯\u00a0x"},
		{`^\w+$`, "héllo_٣", "héllo_٣"},
		{`^[\w-]+$`, "hé-llo", "hé-llo"},
		{`^\d$`, "٣", "٣"},
		{`^\S$`, "é", "é"},
		{`^\S$`, "\u00a0", ""},
	} {
		compiled, err := Compile(each.pattern, 0)
		if err != nil {
			t.Errorf("%s: %v", each.pattern, err)
		} else if found := compiled.FindString(each.text); found != each.found {
			t.Errorf("%s on %q found %q, not %q", each.pattern, each.text, found, each.found)
		}
	}
	if at := must(Compile(`\bé`, 0)).Find("aé é"); at.Start != 4 || at.End != 6 {
		t.Errorf("é found at bytes %d to %d, not 4 to 6", at.Start, at.End)
	}
	if _, err := Compile(`[^\S]`, 0); err == nil {
		t.Error(`[^\S] compiled, though no class here can say it`)
	}
}

func must(compiled *Regexp, err error) *Regexp {
	if err != nil {
		panic(err)
	}
	return compiled
}
