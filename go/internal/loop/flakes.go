package loop

// A test a landing check saw fail, then pass, on one tree is a sighting of its file, Python's
// land._flaked: the line keeps each in its `.flakes`, under `.flakes.lock`, with the tests a check
// confirmed red on a tree (`red`), which a later check passing them there makes sightings too.  A
// file seen on two trees within flakyWindow, whichever of its tests, gets one repair run of the
// target, owned by the member whose check saw it the second time, and holds it until a change
// editing the file merges or the window has passed: what its tests show meanwhile is that
// repair's.

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/gitcall"
	"agentkit/internal/handback"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// flakyWindow is how close two trees' sightings of a file get it a repair, and how long that repair
// holds the file, Python's land.FLAKY.
const flakyWindow = 7 * 24 * time.Hour

// testFile is the file a test is in: its name up to its first `::` (a pytest node) or `#` (a smoke
// block), all of it with neither.
func testFile(test string) string {
	file, _, _ := strings.Cut(test, "::")
	file, _, _ = strings.Cut(file, "#")
	return file
}

// flaked keeps what this member's check, its log at logPath, saw of the tests on the tree it
// checked, as selection gathered it.
func (s *narrowingStack) flaked(selection *checkSelection, logPath string) error {
	in := gitcall.Git{Repo: s.checkout.path}
	_, tree, err := (&repoPlace{wt: s.checkout.path}).identity()
	if err != nil {
		return err
	}
	turn := filepath.Join(run.Runs(), landingLine(s.record))
	held, err := lock.Wait(context.Background(), beside(turn, ".flakes.lock"))
	if err != nil {
		return err
	}
	defer held.Close()
	path, now := beside(turn, ".flakes"), clock()
	seen, repairs, kept, carried := readFlakes(path, now)
	if !carried {
		selection.handoff = true // the line is Python's before anything is written over
		return nil
	}
	logs, tests := map[string][]any{}, []string(nil) // each test seen, its red's log first
	sighted := func(test string, log ...any) {
		if _, ok := logs[test]; !ok {
			tests = append(tests, test)
		}
		logs[test] = log
	}
	for _, test := range selection.flaky {
		sighted(test)
	}
	reds := []any{}
	for _, red := range kept {
		ran, passed := selection.passed[red.Str("command")]
		var rest []any
		for _, test := range names(red.List("tests")) {
			if red.Str("tree") == tree && passed && (ran == nil || slices.Contains(ran, test)) {
				sighted(test, red.Get("log"))
			} else {
				rest = append(rest, test)
			}
		}
		if len(rest) > 0 {
			red = red.Copy()
			red.Set("tests", rest)
			reds = append(reds, red)
		}
	}
	if len(tests) == 0 && len(selection.reds) == 0 {
		return nil
	}
	shown, err := keepLog(logPath)
	if err != nil {
		return err
	}
	for _, red := range selection.reds {
		reds = append(reds, run.Fields("tree", tree, "command", red.Get("command"), "tests", red.Get("tests"), "at", now, "log", shown))
	}
	upstream := lineUpstream(s.record)
	ofFile := func(file string) func(*run.Object) bool {
		return func(sight *run.Object) bool { return testFile(sight.Str("test")) == file }
	}
	var files []string
	for _, test := range tests {
		if !slices.Contains(files, testFile(test)) {
			files = append(files, testFile(test))
		}
	}
	for _, file := range files {
		var hold *run.Object
		newest := 0.0
		for _, repair := range repairs {
			if at, _ := repair.Num("at"); repair.Str("file") == file && (hold == nil || at > newest) {
				hold, newest = repair, at
			}
		}
		if hold != nil {
			changed, _, err := in.Out("diff", "--quiet", hold.Str("sha"), upstream, "--", file)
			if err != nil {
				return err
			}
			if changed == 0 {
				seen = slices.DeleteFunc(seen, ofFile(file)) // the repair's
				continue
			}
		}
		repairs = slices.DeleteFunc(repairs, func(repair *run.Object) bool { return repair.Str("file") == file }) // released for good
		for _, test := range tests {
			if testFile(test) == file {
				seen = append(seen, run.Fields("test", test, "tree", tree, "at", now, "logs", append(slices.Clone(logs[test]), shown)))
			}
		}
		sights := slices.DeleteFunc(slices.Clone(seen), func(sight *run.Object) bool { return !ofFile(file)(sight) })
		trees, first := map[string]bool{}, now
		for _, sight := range sights {
			at, _ := sight.Num("at")
			trees[sight.Str("tree")], first = true, min(first, at)
		}
		if len(trees) < 2 {
			continue
		}
		tip, err := in.Must("rev-parse", upstream+"^{commit}")
		if err != nil {
			return err
		}
		// its first sight keys the repair: no run of an earlier hold answers for it
		name, err := handback.StartRepair(s.record, s.dir, run.Fields("command", file, "check", gitcall.Suite(s.checkout.path, tip)+"  # once",
			"sha", tip, "flaky", first, "text", flakyTestText(file, s.record.Str("repo"), upstream, sights)), launchForSeat, s.l.say)
		if err != nil {
			s.l.say("WARN no repair could start: " + err.Error()) // the line waits on no repair, unblamed
		}
		if name != "" {
			s.l.say(fmt.Sprintf("%s failed, then passed, on %d trees: repaired by %s", file, len(trees), name))
			seen = slices.DeleteFunc(seen, ofFile(file))
			repairs = append(repairs, run.Fields("file", file, "run", name, "at", now, "sha", tip))
		}
	}
	data := run.Line(run.Fields("red", reds, "seen", objects(seen), "repairs", objects(repairs)))
	if err := os.WriteFile(path+".new", []byte(data), 0o666); err != nil {
		return err
	}
	return os.Rename(path+".new", path)
}

// readFlakes is the sightings, repair holds and confirmed reds the line's `.flakes` at path keeps
// within flakyWindow of now, those Python kept by test before files among them; not carried where
// Python reads the file and Go cannot keep it.  One missing or holding no JSON keeps none, as to
// Python.
func readFlakes(path string, now float64) (seen, repairs, reds []*run.Object, carried bool) {
	kept, err := run.ReadJSON(path)
	if errors.Is(err, run.ErrLoneSurrogate) || errors.Is(err, run.ErrLimit) {
		return nil, nil, nil, false
	}
	kept = cmp.Or(kept, run.NewObject())
	sights, holds := slices.Clone(kept.List("seen")), slices.Clone(kept.List("repairs"))
	byTest := cmp.Or(kept.Dict("tests"), run.NewObject())
	for _, test := range byTest.Keys() {
		entry := cmp.Or(byTest.Dict(test), run.NewObject())
		for _, item := range entry.List("seen") {
			if sight, _ := item.(*run.Object); sight != nil {
				sights = append(sights, run.SetAll(run.Fields("test", test), pairs(sight)...))
			}
		}
		if hold := entry.Dict("repair"); hold != nil {
			holds = append(holds, run.SetAll(run.Fields("file", testFile(test)), pairs(hold)...))
		}
	}
	recent := func(items []any) (found []*run.Object) {
		for _, item := range items {
			if entry, _ := item.(*run.Object); entry != nil {
				if at, _ := entry.Num("at"); now-at < flakyWindow.Seconds() {
					found = append(found, entry)
				}
			}
		}
		return found
	}
	return recent(sights), recent(holds), recent(kept.List("red")), true
}

// keepLog is a copy of the check's log beside it, as a later check of the tree writes over it: the
// one that shows the sighting.
func keepLog(logPath string) (string, error) {
	from, err := os.Open(logPath)
	if err != nil {
		return "", err
	}
	defer from.Close()
	kept, err := os.CreateTemp(filepath.Dir(logPath), stem(logPath)+"-seen-*"+filepath.Ext(logPath))
	if err != nil {
		return "", err
	}
	defer kept.Close()
	_, err = io.Copy(kept, from)
	return kept.Name(), err
}

func objects(entries []*run.Object) []any {
	list := []any{}
	for _, entry := range entries {
		list = append(list, entry)
	}
	return list
}

// flakyTestText is what a flaky test file's repair is told, Python's prompts.flaky_test_text: the
// file, its repository, and each of its tests the line saw fail, then pass, on one tree, with the
// logs that show it each time.
func flakyTestText(file, repo, upstream string, sights []*run.Object) string {
	logs, tests, trees := map[string][]string{}, []string(nil), map[string]bool{}
	for _, sight := range sights {
		test := sight.Str("test")
		if _, ok := logs[test]; !ok {
			tests = append(tests, test)
		}
		logs[test] = append(logs[test], names(sight.List("logs"))...)
		trees[sight.Str("tree")] = true
	}
	var shown []string
	for _, test := range tests {
		each := "`" + test + "`:"
		for _, log := range logs[test] {
			each += "\n- " + log
		}
		shown = append(shown, each)
	}
	return fmt.Sprintf("`%s` in %s had a test fail and then pass on the same tree %d times within a week, on %d trees of %s: "+
		"each time the landing line ran it again. Each test, with the logs that show it:\n\n%s\n\n"+
		"Make `%s` deterministic without weakening what it checks: find why its tests fail only sometimes and remove that "+
		"cause, in the tests or in the code they test. Never make them retry, skip them or loosen what they assert.",
		file, repo, len(sights), len(trees), upstream, strings.Join(shown, "\n\n"), file)
}
