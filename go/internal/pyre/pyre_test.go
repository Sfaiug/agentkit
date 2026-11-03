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
// screen fixture and, under re.M, its whole text, matches here as Python's matched; and every letter
// ignoring case takes for more than its own upper and lower case is found as Python finds it.
func TestEveryManifestPatternMatchesAsPythonsDoes(t *testing.T) {
	read, err := os.ReadFile("testdata/cases.json")
	if err != nil {
		t.Fatal(err)
	}
	type pattern struct {
		Harness, Key, Pattern, Flags, Found string
		Matches                             []match
	}
	var cases struct {
		Fixtures []string
		Patterns []pattern
		Cased    struct {
			Letters  string
			Patterns []pattern
		}
	}
	if err := json.Unmarshal(read, &cases); err != nil {
		t.Fatal(err)
	}
	compile := func(each pattern) *Regexp {
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
		}
		return compiled
	}
	for _, each := range cases.Patterns {
		compiled := compile(each)
		if compiled == nil {
			continue
		}
		want := map[string][]match{}
		for _, found := range each.Matches {
			want[found.Fixture] = append(want[found.Fixture], found)
		}
		for _, name := range cases.Fixtures {
			text, err := os.ReadFile(filepath.Join("..", "..", "..", "tests", "fixtures", name))
			if err != nil {
				t.Fatal(err)
			}
			// the whole text is row null, read only where re.M reads rows together, then each
			// row, split on newlines alone
			type part struct {
				row  *int
				text string
			}
			var parts []part
			if strings.Contains(each.Flags, "m") {
				parts = append(parts, part{nil, string(text)})
			}
			for line, row := range strings.Split(string(text), "\n") {
				parts = append(parts, part{&line, row})
			}
			var found []match
			for _, part := range parts {
				if at := compiled.Find(part.text); at != nil {
					span := [2]int{utf8.RuneCountInString(part.text[:at.Start]), utf8.RuneCountInString(part.text[:at.End])}
					found = append(found, match{name, part.row, span, groups(compiled, at)})
				}
			}
			if !reflect.DeepEqual(found, want[name]) {
				t.Errorf("%s %s in %s: Go found %s where Python found %s", each.Harness, each.Key, name, shown(found), shown(want[name]))
			}
		}
	}
	for _, each := range cases.Cased.Patterns {
		if compiled := compile(each); compiled != nil {
			found := ""
			for _, letter := range cases.Cased.Letters {
				if compiled.MatchString(string(letter)) {
					found += string(letter)
				}
			}
			if found != each.Found {
				t.Errorf("%s (%s) found %s where Python found %s", each.Pattern, each.Flags, found, each.Found)
			}
		}
	}
}

// groups is each named group of the pattern and what it took in that match, nil for none.
func groups(compiled *Regexp, at *Match) map[string]*string {
	named := map[string]*string{}
	for _, name := range compiled.engine.GetGroupNames() {
		if _, numbered := strconv.Atoi(name); numbered != nil {
			if taken, ok := at.Group(name); ok {
				named[name] = &taken
			} else {
				named[name] = nil
			}
		}
	}
	return named
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
		{`(?i:s)s`, "ſſ ſs", "ſs"},
		{`(?i)x(?-i:s)`, "Xſ XS Xs", "Xs"},
		{`(?i)(?P<s>s)`, "ſ", "ſ"},
		{`(?i)\x73`, "ſ", "ſ"},
		{`[\x41-\x43]+`, "ABCD", "ABC"},
		{`(?i)[À-Þ]`, "÷×", "×"},
		{`[\141]`, "La", "a"},
		{`(?i)\163`, "ſ", "ſ"},
		{`(?i)[\163]`, "ſ", "ſ"},
		{`(a)\1`, "aa a\x01", "aa"},
		{`\0`, "x\x00", "\x00"},
		{`[\1]`, "\x01", "\x01"},
		{`(?i)(?P<s>a)(?(s)b|c)`, "ac ab", "ab"},
		{`(?i)(?P<state>s)?(?(state)b|c)`, "ſb", "ſb"},
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
	for _, refused := range []string{`[a-`, `[abc-`, `(?(s`} {
		if _, err := Compile(refused, 0); err == nil {
			t.Errorf("%s compiled, though Python refuses it", refused)
		}
	}
}

func must(compiled *Regexp, err error) *Regexp {
	if err != nil {
		panic(err)
	}
	return compiled
}
