package loop

import (
	"cmp"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/handin"
	"agentkit/internal/run"
	"agentkit/internal/worker"
)

var (
	attemptName = regexp.MustCompile(`^(.+)-attempt(\d+)$`)
	workerName  = regexp.MustCompile(`^(?:executor|(?:.+-)?fixer)(?:-|$)`)
)

// isDir is whether the path is a folder.
func isDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

// exists is whether anything stands at the path.
func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// roleBase is a role directory's name without its attempt.
func roleBase(name string) string {
	if found := attemptName.FindStringSubmatch(name); found != nil {
		return found[1]
	}
	return name
}

// lastAttempt is a role's last out directory in a round, "" before any, Python's attempt_dirs' last.
func lastAttempt(round, name string) string {
	latest, number := "", 0
	if isDir(filepath.Join(round, name)) {
		latest, number = filepath.Join(round, name), 1
	}
	entries, _ := os.ReadDir(round)
	for _, entry := range entries {
		if rest, found := strings.CutPrefix(entry.Name(), name+"-attempt"); found && entry.IsDir() {
			if n, err := strconv.Atoi(rest); err == nil && n > number {
				latest, number = filepath.Join(round, entry.Name()), n
			}
		}
	}
	return latest
}

// freeDir is `round/<name>`, or the next attempt beside it: no attempt overwrites another.
func freeDir(round, name string) string {
	out := filepath.Join(round, name)
	for n := 2; exists(out); n++ {
		out = filepath.Join(round, fmt.Sprintf("%s-attempt%d", name, n))
	}
	return out
}

// openTurn is how a role's latest attempt goes on where it never finished, Python's open_turn: a
// call that never spoke is a turn the host cut off, resumed on the conversation it recorded, else
// started afresh ("" where it finished, or never began).
func openTurn(round, name string) (kind, session string) {
	latest := latestTurn(round, name)
	if latest == "" {
		return "", ""
	}
	if spoke(latest) {
		submitted, _ := handin.Read(filepath.Join(latest, handin.File))
		if strings.HasPrefix(name, "reviewer") || submitted != nil && submitted.Closing() != nil {
			return "", ""
		}
	}
	if id := worker.Conversation(latest); id != "" {
		return "resume", id
	}
	return "fresh", ""
}

// newest is the base among names whose latest turn was last written, Python's max by mtime and
// name: a tie goes to the later turn's directory name (`executor-attempt2` over `executor-astra`),
// not its base's.
func newest(round string, names []string) string {
	found, latest, at := "", "", time.Time{}
	for _, name := range names {
		turn := latestTurn(round, name)
		info, err := os.Stat(turn)
		if err == nil && (found == "" || info.ModTime().After(at) || info.ModTime().Equal(at) && turn > latest) {
			found, latest, at = name, turn, info.ModTime()
		}
	}
	return found
}

// roleDirs is the round's role directories that take, by base name: a retry is its attempt's.
func roleDirs(round string, take func(fs.DirEntry) bool) []string {
	entries, _ := os.ReadDir(round)
	var names []string
	for _, entry := range entries {
		if entry.IsDir() && !strings.Contains(entry.Name(), "-retry") && take(entry) && !slices.Contains(names, roleBase(entry.Name())) {
			names = append(names, roleBase(entry.Name()))
		}
	}
	return names
}

// openReview is the reviewer attempt to go on with, and how, Python's open_review: a review that
// fell back to another model wrote under `reviewer-<model>`, so it is the newest reviewer directory
// of any name, which supersedes those before it even when it answered, as its verdict may still
// be pending.
func openReview(round string) (name, kind, session string) {
	name = newest(round, roleDirs(round, func(entry fs.DirEntry) bool { return strings.HasPrefix(entry.Name(), "reviewer") }))
	if name != "" {
		kind, session = openTurn(round, name)
	}
	return name, kind, session
}

// openWorker is the executor or fixer attempt to go on with, Python's open_worker: only the one
// written last, as a later attempt supersedes those before it even when it closed.
func openWorker(round string) (name, kind, session string) {
	if name = latestWorker(round); name == "" {
		return "", "", ""
	}
	if kind, session = openTurn(round, name); kind == "" {
		return "", "", ""
	}
	return name, kind, session
}

// latestWorker is the base of the round's executor or fixer written last, "" before any.
func latestWorker(round string) string {
	return newest(round, roleDirs(round, func(entry fs.DirEntry) bool {
		return !strings.HasPrefix(entry.Name(), "reviewer") && workerName.MatchString(entry.Name())
	}))
}

// reviewTurn is the round's latest reviewer turn on that session, unless it is since, Python's
// review_turn: one from before belongs to a review whose verdict is on the record.
func reviewTurn(round, session, since string) string {
	latest, at := "", time.Time{}
	entries, _ := os.ReadDir(round)
	for _, entry := range entries {
		path := filepath.Join(round, entry.Name())
		if !entry.IsDir() || !strings.HasPrefix(entry.Name(), "reviewer") || session == "" || worker.Conversation(path) != session {
			continue
		}
		if info, err := entry.Info(); err == nil && (latest == "" || !info.ModTime().Before(at)) {
			latest, at = path, info.ModTime()
		}
	}
	if latest == since {
		return ""
	}
	return latest
}

// hostEnded is the one sentence a resumed conversation is handed, Python's host_ended_prompt: it
// holds the task already, and is told the checkout was not tidied and the turn is the same one.
func hostEnded(record *run.Object) string {
	when, known := 0.0, false
	if deaths := record.List("deaths"); len(deaths) > 0 {
		if last, _ := deaths[len(deaths)-1].(*run.Object); last != nil {
			when, known = last.Num("at")
		}
	}
	if !known {
		when, known = record.Num("interrupted_at")
	}
	if !known {
		when = clock()
	}
	clock := time.Unix(int64(when), 0).Format("2006-01-02 15:04:05")
	return "Your process was ended by the host at " + clock + ", not by you; the worktree is exactly as you left it. Continue this turn and finish it; do not start over."
}

// An ask is one role's next turn in the round: what it is told, in which directory, on which
// conversation, the attempt it goes on from, the record file it inherits and what a person is shown.
type ask struct {
	body, out, session, cut, previous string
	shown                             *run.Object
}

// goOn is how the role's next turn goes on from what the round holds, the branches Python's
// execute and review share: a turn never finished resumes on its conversation, or starts anew on
// the whole of what it was told; any other is told body on session.
func (l *loop) goOn(name, word, body, session string) (ask, error) {
	round := l.roundDir()
	kind, sid := openTurn(round, name)
	turn := ask{body: body, out: freeDir(round, name), session: session}
	if kind == "" {
		return turn, nil
	}
	turn.cut = latestTurn(round, name)
	turn.session, turn.shown = sid, run.Fields("at", clock(), "role", word, "restarted", kind == "fresh")
	if kind == "fresh" {
		return turn, nil
	}
	record, err := run.Read(l.dir)
	if record == nil {
		return ask{}, cmp.Or(err, fmt.Errorf("%s: run.json cannot be read", l.id))
	}
	turn.body, turn.previous = hostEnded(record), filepath.Join(turn.cut, handin.File)
	return turn, nil
}

// notice puts on the record that the role goes on, for `ak run status` to say.
func (l *loop) notice(turn ask) error {
	if turn.shown == nil {
		return nil
	}
	return l.save(func(record *run.Object) { record.Set("resume_notice", turn.shown) })
}
