package loop

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
	"agentkit/internal/run"
)

// movedBlock is the alphanumeric characters a moved block holds at least, as git's own moved-line
// detection asks before it calls lines moved.
const movedBlock = 20

var patchName = map[string]*regexp.Regexp{
	"---": regexp.MustCompile(`(?m)^--- (.*?)\t?$`),
	"+++": regexp.MustCompile(`(?m)^\+\+\+ (.*?)\t?$`),
}

// worked refuses a change past the first review's ceiling before its checks.
func (r *repoPlace) worked(l *loop) error { return r.firstReviewCeiling(l) }

func (r *repoPlace) beforeReview(l *loop) error { return r.firstReviewCeiling(l) }

// firstReviewCeiling ends the run blocked with `split it` where its first review would read more
// than `review_lines` added lines, before the reviewer reads a line; the branch it keeps holds the
// work for the pieces.  Only a change's first review: once a review of it handed in a verdict, in
// this run or one it was launched `from:`, a later one reviews whatever the fix left.
func (r *repoPlace) firstReviewCeiling(l *loop) error {
	if record, _ := run.Read(l.dir); record != nil && run.ChangeReviewed(record) {
		return nil
	}
	if err := r.commitLeftovers(l); err != nil {
		return err
	}
	if err := r.followTarget(l); err != nil {
		return err
	}
	lines, err := r.addedLines()
	if err != nil {
		return err
	}
	carried, err := r.carriedLines()
	if err != nil {
		return err
	}
	most, limited := l.reviewLines.Most()
	if !limited || lines-carried <= most {
		return nil
	}
	moved := ""
	if carried > 0 {
		moved = fmt.Sprintf(", %d of them moved unchanged from lines it deletes", carried)
	}
	branch := r.branch
	if branch == "" {
		branch = "its branch"
	}
	why := fmt.Sprintf("The change on %s adds %d lines%s (generated files aside; deletions never count): a first review takes at most %d; split it", branch, lines, moved, most)
	return &blocked{why, "## Blocked\n\n" + why}
}

// generated is which of names git marks linguist-generated in the base's tree, read from there so
// a change cannot leave its own lines out by marking them generated.
func (r *repoPlace) generated(names []string) (map[string]bool, error) {
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
	private := r.git("GIT_INDEX_FILE=" + filepath.Join(tmp, "index"))
	if _, err := private.Must("read-tree", r.baseSHA); err != nil {
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

// addedLines is the text lines the diff from where HEAD left base adds, generated files aside:
// nothing deleted counts, Python's diff_lines with added_only.
func (r *repoPlace) addedLines() (int, error) {
	said, err := r.git().Must("diff", "--numstat", "-z", "--find-renames", "--diff-filter=d", r.baseSHA+"...HEAD")
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
	skip, err := r.generated(names)
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

// carriedLines is the added lines a reviewer need not read, Python's carried_lines: the blocks
// moved unchanged, whitespace aside, from lines the same diff deletes, each deleted line paired
// once, each key's positions consumed in order, so the walk grows with the diff's size.
func (r *repoPlace) carriedLines() (int, error) {
	diff, err := r.git().Try("-c", "core.quotePath=false", "diff", "-U0", "--find-renames", "--no-color", "--no-ext-diff", "--no-textconv",
		"--src-prefix=a/", "--dst-prefix=b/", "--submodule=short", r.baseSHA+"...HEAD")
	if err != nil {
		return 0, err
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
	skipNew, err := r.generated(slices.Sorted(maps.Keys(added)))
	if err != nil {
		return 0, err
	}
	skipOld, err := r.generated(slices.Sorted(maps.Keys(deleted)))
	if err != nil {
		return 0, err
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
	cursor := map[string]int{}
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
				i++
			}
		}
	}
	return carried, nil
}

// numbersOf is the first review's ceiling the run holds to (run.Policy), ak's default where that
// does not read.
func numbersOf(record *run.Object) config.Lines {
	numbers, err := run.Policy(record)
	if err != nil {
		return config.AtMost(config.DefaultReviewLines)
	}
	return numbers.ReviewLines
}
