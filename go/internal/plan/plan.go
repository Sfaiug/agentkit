// Package plan owns a seat's plan: one line per outcome with the check that proves it, in
// Python ak's file `~/.agentkit/state/plan-<seat>.md`, read and written under the seat's lock,
// and ticked only where its check passes on the project's default branch.
package plan

import (
	"cmp"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/lock"
)

// a line as `ak plan add` writes it, eye lines (`your eye`, the owner's to judge live) among them,
// its stamp in any decimal digits, as Python's `\d` reads them:
//
//   - [ ] each session sees its project · check: `python3 tests/test_x.py` · ~/code/acme#0123456789ab · written 2026-10-02 12:40 on 0123456789ab
var format = regexp.MustCompile(`^- \[(?P<mark>[ x])\] (?P<what>.+?) · (?:check: ` + "`(?P<check>[^`]+)`" +
	`|your eye) · (?P<project>.+?)(?P<deferred> · deferred)? · written (?P<when>\p{Nd}{4}-\p{Nd}{2}-\p{Nd}{2} \p{Nd}{2}:\p{Nd}{2})` +
	`(?: on (?P<base>[0-9a-f]{7,40}))?(?: · done (?P<done>.+))?$`)

// the done a check's proof stamps: the commit it passed on
var passedOn = regexp.MustCompile(`^[0-9a-f]{7,40}(?: |$)`)

// An entry is one plan line in that format; an eye line has no Check.
type entry struct {
	Mark, What, Check, Project, When, Base, Done string
	Deferred                                     bool
	bare                                         string // the words a tick never changes: no box, no done
}

// parse reads a plan line, its surrounding space aside; false for any other line.
func parse(text string) (entry, bool) {
	text = strings.TrimFunc(text, config.Space)
	at := format.FindStringSubmatchIndex(text)
	if at == nil {
		return entry{}, false
	}
	group := func(name string) string {
		i := 2 * format.SubexpIndex(name)
		if at[i] < 0 {
			return ""
		}
		return text[at[i]:at[i+1]]
	}
	line := entry{Mark: group("mark"), What: group("what"), Check: group("check"), Project: group("project"),
		When: group("when"), Base: group("base"), Done: group("done"), Deferred: group("deferred") != ""}
	end := len(text)
	if done := at[2*format.SubexpIndex("done")]; done >= 0 {
		end = done - len(" · done ")
	}
	line.bare = text[len("- [ ] "):end]
	return line, true
}

// proven is a check line ticked with the commit its check passed on: done for good.
func (l entry) proven() bool {
	return l.Mark == "x" && passedOn.MatchString(l.Done)
}

// ticked is the line open, or done on commit (`<sha12> <subject>`) where one is given.
func (l entry) ticked(commit string) string {
	if commit == "" {
		return "- [ ] " + l.bare
	}
	return "- [x] " + l.bare + " · done " + commit
}

// added is the line `ak plan add` writes, open and the seat's own.
func added(what, check, project, when, base string) entry {
	bare := what + " · check: `" + check + "` · " + project + " · written " + when
	if base != "" {
		bare += " on " + base
	}
	return entry{bare: bare}
}

func seatFile(kind, name, ext string) string {
	return filepath.Join(config.Home(), "state", kind+"-"+name+"."+ext)
}

// hold holds path's lock, as Python ak's writers take it, until the file closes; a stop ends
// the wait.
func hold(ctx context.Context, path string) (*os.File, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	return lock.Wait(ctx, path)
}

// held runs fn holding the seat's lock, the one Python ak's plan writers take
// (`notify.session_lock`), with the name the seat goes by now: a rename taken while it waited
// for the lock is followed.
func held(ctx context.Context, name string, fn func(current string) error) error {
	for {
		current, _, err := config.ResolveSession(name)
		if err != nil {
			return err
		}
		file, err := hold(ctx, seatFile("notify", current, "lock"))
		if err != nil {
			return err
		}
		now, _, err := config.ResolveSession(name)
		if err == nil && now == current {
			defer file.Close()
			return fn(current)
		}
		file.Close()
		if err != nil {
			return err
		}
	}
}

// verifying runs fn as the seat's one verification at a time, so a later one starts from the
// plan the last one left.  Its lock is a seat file a rename moves, under the seat's lock: the
// file held must be the one the seat's name reaches then, never one a rename replaced.
func verifying(ctx context.Context, name string, fn func() error) error {
	for {
		current, _, err := config.ResolveSession(name)
		if err != nil {
			return err
		}
		file, err := hold(ctx, seatFile("verify", current, "lock"))
		if err != nil {
			return err
		}
		same := false
		err = held(ctx, name, func(now string) error {
			reached, err := os.Stat(seatFile("verify", now, "lock"))
			mine, mineErr := file.Stat()
			same = err == nil && mineErr == nil && os.SameFile(reached, mine)
			return nil
		})
		if err == nil && same {
			defer file.Close()
			return fn()
		}
		file.Close()
		if err != nil {
			return err
		}
	}
}

// path is the seat's plan: of the files under its name and every name renamed into it, the
// one written last, since a renamed seat still writes under the name it was launched with.
// One nothing can look at is an error: an unread plan proves nothing done.
func path(current string) (string, error) {
	found, newest := seatFile("plan", current, "md"), int64(-1)
	for _, each := range names(current) {
		plan := seatFile("plan", each, "md")
		info, err := os.Stat(plan)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return "", fmt.Errorf("cannot read the plan %s: %w", plan, err)
		}
		if info.ModTime().UnixNano() > newest {
			found, newest = plan, info.ModTime().UnixNano()
		}
	}
	return found, nil
}

// names are the names a seat goes by: the one it has now, then every name renamed into it.
func names(current string) []string {
	every := []string{current}
	for _, record := range config.SeatFiles() {
		old := strings.TrimSuffix(strings.TrimPrefix(filepath.Base(record), "session-"), ".json")
		if now, _, _ := config.ResolveSession(old); old != current && now == current {
			every = append(every, old)
		}
	}
	return every
}

// reachedLive is whether the seat's own ssh reached the live host this turn: since the turn's
// start hooks/seat-state.sh writes in its stop file.  Both are under the name its harness was
// launched with, which a rename leaves behind: of every name the seat had, the one holding the
// newest turn is its running launch's, so an earlier launch's reach never counts.
func reachedLive(current string) bool {
	launched, turn := "", 0.0
	for _, each := range names(current) {
		var stop map[string]any
		data, err := os.ReadFile(seatFile("stop", each, "json"))
		if err != nil || json.Unmarshal(data, &stop) != nil {
			continue
		}
		if at, ok := stop["turn"].(float64); ok && (launched == "" || at > turn || at == turn && each > launched) {
			launched, turn = each, at
		}
	}
	if launched == "" {
		return false
	}
	data, err := os.ReadFile(seatFile("live", launched, "txt"))
	reached, failed := strconv.ParseFloat(strings.TrimSpace(string(data)), 64)
	return err == nil && failed == nil && reached >= turn
}

// read is the plan's lines: none without a plan.
func read(current string) ([]string, error) {
	plan, err := path(current)
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(plan)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err == nil && !utf8.Valid(data) {
		err = fmt.Errorf("not UTF-8")
	}
	if err != nil {
		return nil, fmt.Errorf("cannot read the plan %s: %w", plan, err)
	}
	return config.SplitLines(string(data)), nil
}

func write(current string, lines []string) error {
	plan, err := path(current)
	if err != nil {
		return err
	}
	fresh := plan + ".new"
	if err := os.WriteFile(fresh, []byte(strings.Join(lines, "\n")+"\n"), 0o600); err != nil {
		return err
	}
	return os.Rename(fresh, plan)
}

// List proves the seat's plan (`verify`), then is its box lines, as a listing numbers them.
func List(ctx context.Context, name string) ([]string, error) {
	if err := verifying(ctx, name, func() error { return verify(ctx, name) }); err != nil {
		return nil, err
	}
	var box []string
	err := held(ctx, name, func(current string) error {
		lines, err := read(current)
		for _, at := range listed(lines) {
			box = append(box, strings.TrimFunc(lines[at], config.Space))
		}
		return err
	})
	return box, err
}

// listed is where the plan's box lines are, in the order a listing numbers them from 1.
func listed(lines []string) (at []int) {
	for i, line := range lines {
		if strings.HasPrefix(strings.TrimLeftFunc(line, config.Space), "- [") {
			at = append(at, i)
		}
	}
	return at
}

// verify runs each open check line's check on its project's default branch as fetched now and
// ticks those that pass there, naming the commit; a line ticked by hand that nothing proved
// opens again.  The checks run outside the plan's lock, and the results go onto the plan as it
// reads after them, each onto its own line, so a line added meanwhile stays.
func verify(ctx context.Context, name string) error {
	var snapshot []string
	if err := held(ctx, name, func(current string) (err error) {
		snapshot, err = read(current)
		return err
	}); err != nil {
		return err
	}
	env, err := environ()
	if err != nil {
		return err
	}
	results, branches := map[string]string{}, map[string]*branch{}
	for _, text := range snapshot {
		line, ok := parse(text)
		if _, done := results[line.bare]; !ok || line.Check == "" || line.proven() || done {
			continue // lines alike are one check, run once
		}
		on, seen := branches[line.Project]
		if !seen {
			if repo, root := place(line.Project, env); repo != "" {
				if on, err = defaultBranch(ctx, repo, root, "", env); err != nil {
					return err
				}
			}
			branches[line.Project] = on
		}
		if on == nil {
			continue // its checkout is not on this host
		}
		passed := false
		on.checkout(ctx, func(tree string) (err error) {
			// the repository the line recorded, in the very tree it runs in
			if holds(on.clean, tree, on.root, "HEAD") {
				passed, err = on.passes(ctx, tree, line.Check)
			}
			return err
		})
		results[line.bare] = line.ticked("")
		if passed {
			results[line.bare] = line.ticked(on.commit)
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
	}
	return held(ctx, name, func(current string) error {
		present, err := read(current)
		changed := false
		for i, text := range present {
			if line, ok := parse(text); ok && line.Check != "" && results[line.bare] != "" {
				present[i], changed = results[line.bare], true
			}
		}
		if err != nil || !changed { // a plan that lost those lines is never written over
			return err
		}
		return write(current, present)
	})
}

// Add appends an open line to the seat's plan, or keeps the open line already holding this check
// in this project, and is that line.  The check runs on a clean checkout of the project's default
// branch first and must fail there, the line naming the commit it failed on, or prove nothing;
// in a turn whose own ssh reached the live host, one that passes is written done on that commit.
func Add(ctx context.Context, name, repo, what, check string) (string, error) {
	what, check = config.Fold(what), strings.TrimFunc(check, config.Space)
	if err := holdsCheckout(check, repo); err != nil {
		return "", err
	}
	env, err := environ()
	if err != nil {
		return "", err
	}
	on, err := defaultBranch(ctx, repo, "", "", env)
	if err != nil {
		return "", err
	}
	passed, found := false, ""
	if err := on.checkout(ctx, func(tree string) (err error) {
		found = rootOf(on.clean, tree)
		passed, err = on.passes(ctx, tree, check)
		return err
	}); err != nil {
		return "", err
	}
	base, done := strings.Fields(on.commit)[0], ""
	var line string
	err = held(ctx, name, func(current string) error {
		if passed {
			// The owner, 26 Oct 2026: in a turn whose own ssh reached the live host, work done
			// there proves itself, so a check already passing is written done on that commit
			// and a job finished in that one turn reads `done`.
			if !reachedLive(current) {
				return fmt.Errorf("this check already passes on %s's default branch, so it proves nothing; "+
					"write one that fails until the work is done", filepath.Base(repo))
			}
			base, done = "", base
		}
		where := named(repo, found)
		if strings.Contains(where, "·") {
			return fmt.Errorf("%s: a project a line names holds no `·`", where)
		}
		lines, err := read(current)
		if err != nil {
			return err
		}
		for i, text := range lines {
			if old, ok := parse(text); ok && old.Check == check && old.Project == where && !old.proven() {
				// the open line already holding this check here is kept, the seat's own
				line = added(old.What, check, where, old.When, old.Base).ticked(done)
				if line == strings.TrimFunc(text, config.Space) {
					return nil
				}
				return write(current, slices.Replace(lines, i, i+1, line))
			}
		}
		line = added(what, check, where, time.Now().Format("2006-01-02 15:04"), base).ticked(done)
		return write(current, append(lines, line))
	})
	return line, err
}

// Check puts check in place of plan line number's check, the line open again and the seat's
// own, since no run has the new check, and is that line.  The number is ASCII digits, read as
// Python's int reads them.  The check must fail where the line's check did: on the commit the
// line names, the code before the work, however long ago the work landed.  A line naming none
// takes it unproven: nothing recorded where its check failed, and a missing proof never blocks.
// The check runs outside the plan's lock; the line is replaced only while it reads as it did.
func Check(ctx context.Context, name, number, check string) (string, error) {
	number, check = cmp.Or(strings.TrimLeft(number, "0"), "0"), strings.TrimFunc(check, config.Space)
	var line string
	if err := held(ctx, name, func(current string) error {
		lines, err := read(current)
		if err != nil {
			return err
		}
		box := listed(lines)
		if n, err := strconv.Atoi(number); err == nil && n >= 1 && n <= len(box) {
			line = strings.TrimFunc(lines[box[n-1]], config.Space)
			return nil
		}
		return fmt.Errorf("no plan line %s; `ak plan` lists them", number)
	}); err != nil {
		return "", err
	}
	old, ok := parse(line)
	if !ok || old.Check == "" {
		return "", errors.New("only a check line takes another check")
	}
	env, err := environ()
	if err != nil {
		return "", err
	}
	repo, _ := place(old.Project, env)
	if repo != "" {
		if err := holdsCheckout(check, repo); err != nil {
			return "", err
		}
	}
	if old.Base != "" {
		if repo == "" {
			return "", fmt.Errorf("this host has no checkout of %s", old.Project)
		}
		on, err := defaultBranch(ctx, repo, "", old.Base, env)
		if err != nil {
			return "", err
		}
		passed := false
		if err := on.checkout(ctx, func(tree string) (err error) {
			passed, err = on.passes(ctx, tree, check)
			return err
		}); err != nil {
			return "", err
		}
		if passed {
			return "", fmt.Errorf("this check already passes on %s, the commit line %s names, so it proves nothing; "+
				"write one that fails until the work is done", old.Base, number)
		}
	}
	fresh := added(old.What, check, old.Project, old.When, old.Base).ticked("")
	return fresh, held(ctx, name, func(current string) error {
		lines, err := read(current)
		if err != nil {
			return err
		}
		for i, text := range lines {
			if strings.TrimFunc(text, config.Space) == line {
				lines[i] = text[:len(text)-len(strings.TrimLeftFunc(text, config.Space))] + fresh
				return write(current, lines)
			}
		}
		return fmt.Errorf("plan line %s changed while its new check ran; run `ak plan check` again", number)
	})
}
