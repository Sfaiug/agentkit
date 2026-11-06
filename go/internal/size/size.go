// Package size counts a change as its first review reads it, Python's diff_lines with added_only
// and reviewed_lines, and refuses one past the first review's ceiling, Python's
// first_review_refusal: one count for the gate before a first review, `ak hand-in done` and a
// seat's own pull request.
package size

import (
	"fmt"
	"maps"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"unicode"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
)

// movedBlock is the alphanumeric characters a moved block holds at least, as git's own moved-line
// detection asks before it calls lines moved.
const movedBlock = 20

var patchName = map[string]*regexp.Regexp{
	"---": regexp.MustCompile(`(?m)^--- (.*?)\t?$`),
	"+++": regexp.MustCompile(`(?m)^\+\+\+ (.*?)\t?$`),
}

// Refusal is the sentence refusing what, the change from where head left base, where the lines it
// adds less those moved unchanged are more than limit, "" where they are not.
func Refusal(g gitcall.Git, what, base, head string, limit config.Lines) (string, error) {
	most, limited := limit.Most()
	if !limited {
		return "", nil
	}
	lines, err := Added(g, base, head)
	if err != nil || lines <= most {
		return "", err
	}
	_, moved, err := Reviewed(g, base, head)
	if err != nil || lines-moved <= most {
		return "", err
	}
	said := ""
	if moved > 0 {
		said = fmt.Sprintf(", %d of them moved unchanged from lines it deletes", moved)
	}
	return fmt.Sprintf("%s adds %d lines%s (generated files aside; deletions never count): a first review takes at most %d; split it", what, lines, said, most), nil
}

// generated is which of names git marks linguist-generated in base's tree, read from there so
// a change cannot leave its own lines out by marking them generated.
func generated(g gitcall.Git, base string, names []string) (map[string]bool, error) {
	found := map[string]bool{}
	if len(names) == 0 {
		return found, nil
	}
	tmp, err := os.MkdirTemp("", "ak-index-")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(tmp)
	// older Git has no check-attr --source; a private index reads the same tree
	private := gitcall.Git{Repo: g.Repo, Env: append(slices.Clone(g.Env), "GIT_INDEX_FILE="+filepath.Join(tmp, "index")), Cap: g.Cap}
	if _, err := private.Must("read-tree", base); err != nil {
		return nil, err
	}
	said, err := private.Must(append([]string{"check-attr", "--cached", "-z", "linguist-generated", "--"}, names...)...)
	if err != nil {
		return nil, err
	}
	fields := strings.Split(said, "\x00")
	if len(fields) < 3*len(names) {
		return nil, fmt.Errorf("git did not report generated attributes for the diff")
	}
	for i, name := range names {
		if value := strings.ToLower(fields[3*i+2]); value == "set" || value == "true" {
			found[name] = true
		}
	}
	return found, nil
}

// Added is the text lines the diff from where head left base adds, generated files aside:
// nothing deleted counts, Python's diff_lines with added_only.
func Added(g gitcall.Git, base, head string) (int, error) {
	said, err := g.Must("diff", "--numstat", "-z", "--find-renames", "--diff-filter=d", base+"..."+head)
	if err != nil {
		return 0, err
	}
	fields := strings.Split(said, "\x00")
	added := map[string]int{}
	var names []string
	for i := 0; i < len(fields); i++ {
		parts := strings.SplitN(fields[i], "\t", 3)
		if len(parts) < 3 {
			continue
		}
		name := parts[2]
		if name == "" && i+2 < len(fields) {
			name = fields[i+2] // the old name; a renamed file counts under its new one
			i += 2
		}
		if count, err := strconv.Atoi(parts[0]); err == nil {
			added[name] = count
			names = append(names, name)
		}
	}
	skip, err := generated(g, base, names)
	if err != nil {
		return 0, err
	}
	total := 0
	for name, count := range added {
		if !skip[name] {
			total += count
		}
	}
	return total, nil
}

// sideName is the path a patch's file header gives the side mark names, "" for /dev/null.
func sideName(header, mark, prefix string) string {
	found := patchName[mark].FindStringSubmatch(header)
	if found == nil {
		return ""
	}
	name := found[1]
	if strings.HasPrefix(name, `"`) {
		if unquoted, err := strconv.Unquote(name); err == nil {
			name = unquoted
		}
	}
	if !strings.HasPrefix(name, prefix) {
		return ""
	}
	return name[len(prefix):]
}

// windows is, for each position of a file's lines, the run of lines from it that first holds
// movedBlock alphanumerics, "" where the lines end first or the line itself holds none: a run of
// punctuation-only lines builds no window of its own.
func windows(lines []string) ([]string, []int) {
	keys, lengths := make([]string, len(lines)), make([]int, len(lines))
	counts := make([]int, len(lines))
	for at, line := range lines {
		for _, c := range line {
			if unicode.IsLetter(c) || unicode.IsNumber(c) {
				counts[at]++
			}
		}
	}
	end, held := 0, 0
	for start := range lines {
		for end < len(lines) && held < movedBlock {
			held += counts[end]
			end++
		}
		if counts[start] > 0 && held >= movedBlock {
			keys[start] = strings.Join(lines[start:end], "\n")
			lengths[start] = end - start
		}
		held -= counts[start]
	}
	return keys, lengths
}

// Reviewed is the added lines from where head left base that a reviewer reads, each as its text
// with whitespace collapsed, counted, and how many it need not read, Python's reviewed_lines: the
// blocks moved unchanged, whitespace aside, from lines the same diff deletes, each deleted line
// paired once, each key's positions consumed in order, so the walk grows with the diff's size.
func Reviewed(g gitcall.Git, base, head string) (map[string]int, int, error) {
	diff, err := g.Try("-c", "core.quotePath=false", "diff", "-U0", "--find-renames", "--no-color", "--no-ext-diff", "--no-textconv",
		"--src-prefix=a/", "--dst-prefix=b/", "--submodule=short", base+"..."+head)
	if err != nil {
		return nil, 0, err
	}
	added, deleted := map[string][]string{}, map[string][]string{}
	for _, chunk := range strings.Split("\n"+diff, "\ndiff --git ")[1:] {
		header, body, _ := strings.Cut(chunk, "\n@@")
		lines := strings.Split(body, "\n")
		pick := func(mark byte) []string {
			kept := []string{}
			for _, line := range lines {
				if len(line) > 0 && line[0] == mark {
					kept = append(kept, strings.Join(strings.FieldsFunc(line[1:], config.Space), " "))
				}
			}
			return kept
		}
		if name := sideName(header, "+++", "b/"); name != "" {
			added[name] = pick('+')
		}
		if name := sideName(header, "---", "a/"); name != "" {
			deleted[name] = pick('-')
		}
	}
	skipNew, err := generated(g, base, slices.Sorted(maps.Keys(added)))
	if err != nil {
		return nil, 0, err
	}
	skipOld, err := generated(g, base, slices.Sorted(maps.Keys(deleted)))
	if err != nil {
		return nil, 0, err
	}
	type position struct {
		file string
		at   int
	}
	where := map[string][]position{}
	used := map[string]map[int]bool{}
	for _, name := range slices.Sorted(maps.Keys(deleted)) {
		if skipOld[name] {
			continue
		}
		used[name] = map[int]bool{}
		keys, _ := windows(deleted[name])
		for at, key := range keys {
			if key != "" {
				where[key] = append(where[key], position{name, at})
			}
		}
	}
	cursor, read := map[string]int{}, map[string]int{}
	carried := 0
	for _, name := range slices.Sorted(maps.Keys(added)) {
		if skipNew[name] {
			continue
		}
		lines := added[name]
		keys, sizes := windows(lines)
		for i := 0; i < len(lines); {
			key, length := keys[i], 0
			var candidates []position
			if key != "" {
				candidates = where[key]
			}
			at := cursor[key]
			for at < len(candidates) {
				place := candidates[at]
				source, held := deleted[place.file], used[place.file]
				length = 0
				for i+length < len(lines) && place.at+length < len(source) && !held[place.at+length] && source[place.at+length] == lines[i+length] {
					length++
				}
				at++
				if length >= sizes[i] {
					for n := place.at; n < place.at+length; n++ {
						held[n] = true
					}
					break
				}
				length = 0 // a deleted block paired already, or cut by one: never again
			}
			if key != "" {
				cursor[key] = at
			}
			if length > 0 {
				carried += length
				i += length
			} else {
				read[lines[i]]++
				i++
			}
		}
	}
	return read, carried, nil
}
