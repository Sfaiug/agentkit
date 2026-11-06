package launch

import (
	"cmp"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// A rival is a run under way that looks like the change a launch builds: its id, seat ("" for
// nobody's), start (-Inf where its record holds none), title, the test files it shares, and the
// launch's task file where it was launched from that file.
type rival struct {
	id, seat, title, task string
	started               float64
	files                 []string
}

// rivals are the runs going in repo ("" for none) that look like the change the task at path
// builds, newest first, as Python's already_under_way finds them: a live run whose checks name a
// test file the task's checks name too, which the origin default tip lacks and which no three other
// jobs there ran unless both titles name it, or one launched from that very task file.  ErrPython
// where a record is Python's to read.
func rivals(repo, path, title string, cmds []string) ([]rival, error) {
	if repo == "" {
		return nil, nil
	}
	mine := absent(repo, testFiles(cmds))
	var ran map[string]map[string]bool // read once a file is shared
	var found []rival
	for _, dir := range run.Dirs() {
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return nil, ErrPython
		}
		if record == nil || !run.Active(record) || !run.ProcessActive(record) {
			continue
		}
		meta, theirs, named := copied(dir)
		if same, err := ours(repo, dir, record, meta); err != nil || !same {
			if err != nil {
				return nil, err
			}
			continue
		}
		other := cmp.Or(record.Str("title"), named, filepath.Base(dir))
		var shared []string
		for name := range testFiles(theirs) {
			if mine[name] {
				shared = append(shared, name)
			}
		}
		if len(shared) > 0 && ran == nil {
			if ran, err = jobs(repo); err != nil {
				return nil, err
			}
		}
		// a check job after job runs whatever they change says nothing about the work
		shared = slices.DeleteFunc(shared, func(name string) bool {
			others := 0
			for job := range ran[name] {
				if job != title && job != other {
					others++
				}
			}
			return !(titled(title, name) && titled(other, name) || others < 3)
		})
		launched := ""
		if from := record.Str("task_file"); from != "" && config.Absolute(from) == path {
			launched = path
		}
		if len(shared) == 0 && launched == "" {
			continue
		}
		slices.Sort(shared)
		started, dated := record.Num("started_at")
		if !dated {
			started = math.Inf(-1)
		}
		found = append(found, rival{filepath.Base(dir), run.Seat(record), other, launched, started, shared})
	}
	slices.SortFunc(found, func(a, b rival) int {
		return cmp.Or(cmp.Compare(b.started, a.started), strings.Compare(b.id, a.id))
	})
	return found, nil
}

// underWayRefusal is why a launch is refused for the runs found, named by the newest; a seat may
// not start a second run regardless (SeatRefusal).
func underWayRefusal(found []rival, seated bool) string {
	first := found[0]
	detail := strings.Join(first.files, ", ")
	if detail == "" {
		detail = "task file " + first.task
	}
	if len(found) > 1 {
		detail += fmt.Sprintf(" and %d more", len(found)-1)
	}
	started := "??:??"
	if !math.IsInf(first.started, -1) {
		seconds, part := math.Modf(first.started)
		started = time.Unix(int64(seconds), int64(part*1e9)).Format("15:04")
	}
	advice := "wait for it"
	if !seated {
		advice += ", or add --anyway to start a second run"
	}
	return fmt.Sprintf(`this looks already under way: %s (%s, started %s, "%s") shares %s; %s`,
		first.id, cmp.Or(first.seat, "nobody's"), started, first.title, detail, advice)
}

// jobs are, for each test file, the jobs in repo whose checks name it and whose titles do not: a
// job is a title, so relaunches of one count once, and one whose title names the file changes
// what it checks.
func jobs(repo string) (map[string]map[string]bool, error) {
	ran := map[string]map[string]bool{}
	for _, dir := range run.Dirs() {
		record, _ := run.Read(dir)
		meta, cmds, named := copied(dir)
		if record == nil || cmds == nil {
			continue
		}
		if same, err := ours(repo, dir, record, meta); err != nil || !same {
			if err != nil {
				return nil, err
			}
			continue
		}
		job := cmp.Or(record.Str("title"), named)
		for name := range testFiles(cmds) {
			if !titled(job, name) {
				if ran[name] == nil {
					ran[name] = map[string]bool{}
				}
				ran[name][job] = true
			}
		}
	}
	return ran, nil
}

// copied is a run's own copy of its task as Python's parse_task and done_when read it: its front
// matter, checks and title, no checks where it does not read.
func copied(dir string) (map[string]string, []string, string) {
	path := filepath.Join(dir, "task.md")
	meta, cmds, err := task.Read(path)
	data, unread := os.ReadFile(path)
	if err != nil || unread != nil {
		return nil, nil, ""
	}
	return meta, cmds, task.Title(task.Text(data), "task")
}

// ours is whether a run works in repo: where its record says, else, for a receipt from before it
// built its worktree, where its task's `repo:` names.
func ours(repo, dir string, record *run.Object, meta map[string]string) (bool, error) {
	if where := record.Str("repo"); where != "" {
		return config.Absolute(where) == repo, nil
	}
	if meta["repo"] == "" {
		return false, nil
	}
	own := filepath.Join(dir, "task.md")
	found, _, err := checkout(meta, own, own)
	return found == repo, err
}

// absent are the files the origin default tip lacks, every one where the tip cannot be read or git
// never answered: an existing guard says nothing about which change a run builds.  A partial clone
// may hold their paths but not their blobs, and no lookup may fetch.
func absent(repo string, files map[string]bool) map[string]bool {
	git := gitcall.Git{Repo: repo, Env: []string{"GIT_NO_LAZY_FETCH=1"}}
	kept := map[string]bool{}
	for name := range files {
		held, err := git.Try("--literal-pathspecs", "ls-tree", "-z", "--full-tree", "refs/remotes/origin/HEAD^{commit}", "--", name)
		if err != nil {
			return files
		}
		if held == "" {
			kept[name] = true
		}
	}
	return kept
}

// testFiles are the done-when tokens naming a test file, quotes stripped: one whose own name looks
// like a test, so a shared runner such as `bash tests/smoke.sh` names none, and no glob.
func testFiles(cmds []string) map[string]bool {
	found := map[string]bool{}
	for _, command := range cmds {
		for _, token := range strings.Fields(command) {
			name := strings.Trim(token, `"'`)
			stem, base := split(name)
			if name != "" && !strings.ContainsAny(name, "*?[") && (strings.HasPrefix(stem, "test_") || strings.HasSuffix(base, "_test")) {
				found[name] = true
			}
		}
	}
	return found
}

var titleWords = regexp.MustCompile(`[a-z0-9]+`)

// titled is whether a title names what the test file checks: a word of the file's own name, or
// one of three or more letters with a plain ending added (invoice and invoices, round and
// rounding); any longer prefix would read `allow` as naming test_all.py.
func titled(title, file string) bool {
	_, base := split(file)
	for _, word := range titleWords.FindAllString(strings.ToLower(title), -1) {
		for _, part := range titleWords.FindAllString(strings.ToLower(base), -1) {
			short, long := word, part
			if len(part) < len(word) {
				short, long = part, word
			}
			if part != "test" && (long == short || len(short) >= 3 && strings.HasPrefix(long, short) &&
				slices.Contains([]string{"s", "es", "d", "ed", "ing"}, long[len(short):])) {
				return true
			}
		}
	}
	return false
}

// split is a file name's last part, and that part without its extension.
func split(name string) (string, string) {
	stem := name[strings.LastIndexByte(name, '/')+1:]
	if dot := strings.LastIndexByte(stem, '.'); dot >= 0 {
		return stem, stem[:dot]
	}
	return stem, stem
}
