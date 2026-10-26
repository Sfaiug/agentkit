// Package plan owns a seat's plan: one line per outcome with the check that proves it, in
// Python ak's file `~/.agentkit/state/plan-<seat>.md`, read and written under the seat's lock,
// and ticked only where its check passes on the project's default branch.
package plan

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
)

// a line as `ak plan add` writes it, eye lines (`your eye`, the owner's to judge live) among them:
//
//   - [ ] each session sees its project · check: `python3 tests/test_x.py` · ~/code/acme#0123456789ab · written 2026-10-02 12:40 on 0123456789ab
var format = regexp.MustCompile(`^- \[(?P<mark>[ x])\] (?P<what>.+?) · (?:check: ` + "`(?P<check>[^`]+)`" +
	`|your eye) · (?P<project>.+?)(?P<deferred> · deferred)? · written (?P<when>\d{4}-\d\d-\d\d \d\d:\d\d)` +
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
	text = strings.TrimSpace(text)
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

func seatFile(kind, name, ext string) string {
	return filepath.Join(config.Home(), "state", kind+"-"+name+"."+ext)
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
		file, err := lock(ctx, seatFile("notify", current, "lock"))
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
		file, err := lock(ctx, seatFile("verify", current, "lock"))
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
	names := []string{current}
	for _, record := range config.SeatFiles() {
		old := strings.TrimSuffix(strings.TrimPrefix(filepath.Base(record), "session-"), ".json")
		if now, _, _ := config.ResolveSession(old); old != current && now == current {
			names = append(names, old)
		}
	}
	found, newest := seatFile("plan", current, "md"), int64(-1)
	for _, each := range names {
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
	var listed []string
	err := held(ctx, name, func(current string) error {
		lines, err := read(current)
		for _, line := range lines {
			if line = strings.TrimSpace(line); strings.HasPrefix(line, "- [") {
				listed = append(listed, line)
			}
		}
		return err
	})
	return listed, err
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
	env, err := environ(nil)
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
				if on, err = defaultBranch(ctx, repo, root); err != nil {
					return err
				}
			}
			branches[line.Project] = on
		}
		if on == nil {
			continue // its checkout is not on this host
		}
		results[line.bare] = line.ticked("")
		if on.passes(ctx, line.Check) {
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
