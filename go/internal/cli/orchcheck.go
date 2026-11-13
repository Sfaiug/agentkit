package cli

import (
	"cmp"
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"syscall"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/fetch"
	"agentkit/internal/gitcall"
	"agentkit/internal/handin"
	"agentkit/internal/harness"
	"agentkit/internal/loop"
	"agentkit/internal/notify"
	"agentkit/internal/pick"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/task"
	"agentkit/internal/usage"
	"agentkit/internal/worker"
)

func init() { commands["orch check"] = orchCheck }

// checkAsk is what the checking model is asked (Python's done_check.ASK).
var checkAsk = strings.Join([]string{
	"# Does seat {name}'s work hold everything its owner asked of it?",
	"",
	"{workspace} holds the seat's record:",
	"- owner/: each message its owner wrote to it, and each answer they gave on its question",
	"  cards after the question and choices it wrote, a file each, oldest first from 1.md.",
	"- conversation.md: each conversation it had as its harness keeps it, oldest first, a `---`",
	"  line where one was left for the next. The user side holds ak's lines as well as the owner's:",
	"  only owner/ says which words are the owner's.",
	"- plan.md: its plan, `- [x]` a line done and `- [ ]` one open.",
	"- runs/: each run it launched: its title, state, whether it merged, its PR and its task.",
	"- pictures/: each picture of a screen it kept with `ak orch look`, an image or a text capture",
	"  of a terminal screen, as the screen was then, oldest first:",
	"{pictures}",
	"",
	"Read each message of the owner's where it stands in the conversation: a \"yes\" or \"the second",
	"one\" takes what the seat proposed just before. A gap is something the owner asked to be built or",
	"changed that no done plan line and no merged run delivered; a screen the owner will see that the",
	"work changed and no picture shows, quoting the ask that changed it; or a question or a request to",
	"explain that no reply of the seat's answered. Only a later message of the owner's drops or changes",
	"an ask; the seat's replies never do.",
	"",
	"Hand in each gap as `ak hand-in finding owner/N.md:LINE \"what the work does not hold\" \"why the",
	"owner needs it\" --quote \"the owner's words\"`, the words copied exactly from that message or",
	"answer. Here the quote is what makes a finding a gap, never a note: ak keeps each gap the owner's",
	"own words hold and drops every other. Then `ak hand-in done`, with gaps or with none.",
	"",
}, "\n")

// orchCheck answers `ak orch check SEAT` as Python's done_check.main does: does the seat's work
// hold everything its owner said to it?  Each gap is printed with the owner's words it rests on:
// exit 1 with one, 0 with none, and 2 where nothing could be checked.  A seat, a pick or a turn
// Go does not carry is left to Python before anything is written.
func orchCheck(args []string, out, errOut io.Writer) int {
	name, found, err := ownerGaps(context.Background(), args[0], errOut)
	switch {
	case errors.Is(err, errLeft):
		return notImplemented(errOut, "orch check")
	case errors.Is(err, worker.ErrInterrupted):
		fmt.Fprintf(errOut, "\nak orch: %s\n", err)
		return 130
	case err != nil:
		fmt.Fprintf(errOut, "ak orch: %s\n", err)
		return 2
	case told(out, name, found):
		return 1
	}
	return 0
}

// told prints what a done check of seat name found, each gap with the owner's words it rests on,
// and is whether it found one.
func told(out io.Writer, name string, found []*run.Object) bool {
	if len(found) == 0 {
		fmt.Fprintf(out, "%s: its work holds everything its owner asked\n", name)
		return false
	}
	plural := ""
	if len(found) > 1 {
		plural = "s"
	}
	fmt.Fprintf(out, "%s: %d thing%s its owner asked not in its work\n", name, len(found), plural)
	for _, row := range found {
		quote := strings.ReplaceAll(row.Dict("evidence").Str("quote"), "\n", "\n  ")
		fmt.Fprintf(out, "- %s\n  the owner: \"%s\"\n", run.Text(row.Get("what")), quote)
	}
	return true
}

// ownerGaps is the seat's name and the findings of one model's turn over what the seat was asked
// and did that quote a message or answer of its owner's word for word (done_check.gaps): whether
// a quote is the owner's is decided here, never by the model; ctx ending ends the turn.  errLeft is
// a case Python carries.
func ownerGaps(ctx context.Context, seat string, errOut io.Writer) (string, []*run.Object, error) {
	if err := config.Check(); err != nil {
		return "", nil, err
	}
	name, record, err := config.ResolveSession(seat)
	if err != nil {
		return "", nil, err
	}
	found, read, err := gaps(ctx, name, record, errOut)
	// what the check read is kept where it found no gap, and forgotten however else it ended, as
	// Python's `finally` does; a case Python carries writes nothing
	if !errors.Is(err, errLeft) {
		if kept := keep(name, read); kept != nil {
			err = fmt.Errorf("could not check %s: %w", name, kept)
		}
	}
	return name, found, err
}

// gaps is ownerGaps of a seat resolved, with the fingerprint of what a check that found no gap
// read ("" for any other end).
func gaps(ctx context.Context, name string, record map[string]any, errOut io.Writer) ([]*run.Object, string, error) {
	// a record a harness's reader reads loosely is read, as before: only the reader deciding whether
	// a check is owed, which ends a seat it reads as done, waits for one as strict as Python's
	had, err := notify.Conversations(name, false)
	if errors.Is(err, notify.ErrUnread) {
		return nil, "", errLeft
	} else if err != nil {
		return nil, "", fmt.Errorf("could not check %s: %w", name, err)
	}
	if len(had) == 0 || had[len(had)-1].Name == "" {
		return nil, "", fmt.Errorf("no seat named %s whose conversation ak can read", name)
	}
	said, owner, err := plan.OwnerWords(had)
	if errors.Is(err, notify.ErrUnread) {
		return nil, "", errLeft
	} else if err != nil {
		return nil, "", fmt.Errorf("could not check %s: %w", name, err)
	}
	// read with the seat's other records, as Python's check reads them, so one that cannot be read
	// stops the check whatever its owner said; one Go reads otherwise is Python's where it goes on
	pictures, err := keptPictures(name)
	switch {
	case err != nil && !errors.Is(err, errLeft):
		return nil, "", err
	case len(owner) == 0:
		return nil, "", nil // asked nothing, so nothing is missing
	case err != nil:
		return nil, "", err
	}
	lines, err := plan.Lines(name)
	if err != nil {
		return nil, "", err
	}
	// every record read, and every case Python carries settled, before the pick's meters or the
	// turn's folders are written
	files, err := checkFiles(name, owner, said, lines, pictures)
	if err != nil {
		return nil, "", err
	}
	var shown []string
	for _, each := range pictures {
		shown = append(shown, each.shown)
	}
	model, err := checker(name, record)
	if err != nil {
		return nil, "", err
	}
	fmt.Fprintf(errOut, "ak orch check: %s reads what %s was asked and did\n", model, name)
	if err := config.EnsureDirs(); err != nil {
		return nil, "", fmt.Errorf("could not check %s: %w", name, err)
	}
	tmp, err := os.MkdirTemp(filepath.Join(config.Home(), "tmp"), "check-"+name+"-")
	if err != nil {
		return nil, "", err
	}
	defer os.RemoveAll(tmp)
	workspace, into := filepath.Join(tmp, "workspace"), filepath.Join(tmp, "out")
	for relative, text := range files {
		path := filepath.Join(workspace, filepath.FromSlash(relative))
		if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
			return nil, "", err
		}
		if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
			return nil, "", err
		}
	}
	// an existing role, the reviewer's of a workspace, whose hand-in takes findings and refuses a
	// quote its file does not hold
	ask := strings.NewReplacer("{name}", name, "{workspace}", workspace,
		"{pictures}", cmp.Or(strings.Join(shown, "\n"), "  none kept")).Replace(checkAsk)
	var expired *worker.LoginExpired
	switch _, _, err := worker.Turn(model, "reviewer-scratch", ask, workspace, into, "", worker.Given{Context: ctx}, errOut); {
	case errors.Is(err, worker.ErrInterrupted), errors.As(err, &expired):
		return nil, "", err
	case err != nil && !errors.Is(err, worker.ErrSilent):
		return nil, "", fmt.Errorf("could not check %s: %w", name, err)
	}
	review, _ := handin.Read(filepath.Join(into, handin.File))
	if review == nil || !review.Done() {
		return nil, "", fmt.Errorf("%s could not check %s: its turn did not end in `ak hand-in done`", model, name)
	}
	var found []*run.Object
	for _, row := range review.Of("finding") {
		quote := row.Dict("evidence").Str("quote")
		if strings.TrimFunc(quote, config.Space) != "" && slices.ContainsFunc(owner, func(each plan.Said) bool {
			return strings.Contains(each.Words, quote)
		}) {
			found = append(found, row)
		}
	}
	if len(found) > 0 {
		return found, "", nil
	}
	return nil, plan.Fingerprint(owner, lines), nil
}

// keep keeps what a check that found no gap read, or with "" forgets what one kept
// (done_check.keep): under the seat's lock, which a rename takes too, so under the name the seat
// goes by now.  Of two checks of a seat at once, the one that ends last stands.
func keep(name, read string) error {
	if err := config.EnsureDirs(); err != nil {
		return err // as Python's session_lock makes them first
	}
	return notify.Held(context.Background(), name, func(current string) error {
		path := filepath.Join(config.Home(), "state", config.SeatFileNames(current)["checked"])
		if read == "" {
			if err := os.Remove(path); !errors.Is(err, fs.ErrNotExist) {
				return err
			}
			return nil
		}
		fresh := path + ".new"
		if err := os.WriteFile(fresh, []byte(read+"\n"), 0o666); err != nil {
			return err
		}
		return os.Rename(fresh, path)
	})
}

// checkFiles is the checking turn's workspace, each file by its path there: the owner's words a
// file each, each conversation of the seat's, its plan's lines, each picture it kept and each run
// it launched, read without writing anything.  errLeft where Go does not read the runs as Python
// does.
func checkFiles(name string, owner []plan.Said, said [][]harness.Turn, lines []string, pictures []picture) (map[string]string, error) {
	files := map[string]string{}
	for n, each := range owner {
		files[fmt.Sprintf("owner/%d.md", n+1)] = each.Shown
	}
	var conversations []string
	for _, turns := range said {
		var conversation strings.Builder
		for _, turn := range turns {
			fmt.Fprintf(&conversation, "**%s:** %s\n\n", turn.Who, turn.Text)
		}
		conversations = append(conversations, conversation.String())
	}
	var planned strings.Builder
	for _, line := range lines {
		planned.WriteString(line + "\n")
	}
	files["conversation.md"], files["plan.md"] = strings.Join(conversations, "---\n\n"), planned.String()
	for _, each := range pictures {
		files[each.path] = each.data
	}
	var unread error
	if !run.Every(func(dir string, state *run.Object) bool {
		// the seat it was launched from by its name now, as transitions.launched_session follows it
		launched := run.Launched(state)
		if launched == "" {
			return true
		}
		seat, _, err := config.ResolveSession(launched)
		if err != nil {
			unread = err // in the seat record's own words, as the seat's own is refused
			return false
		} else if seat != name {
			return true
		}
		taskText, err := runTask(filepath.Join(dir, "task.md"))
		if err != nil {
			unread = fmt.Errorf("could not check %s: %w", name, err)
			return false
		}
		merged, pr := "no", "none"
		if state.Truthy("merged") {
			merged = "yes"
		}
		if state.Truthy("pr") {
			pr = run.Text(state.Get("pr"))
		}
		files["runs/"+filepath.Base(dir)+".md"] = fmt.Sprintf("title: %s\nstate: %s\nmerged: %s\nPR: %s\n\n%s",
			run.Text(state.Get("title")), run.Text(state.Get("state")), merged, pr, taskText)
		return true
	}) {
		if unread != nil {
			return nil, unread
		}
		return nil, errLeft
	}
	return files, nil
}

// A picture is one of a screen the seat kept with `ak orch look`, as its done check is shown it:
// its path in the workspace, the bytes there and the line of the ask naming it.
type picture struct{ path, data, shown string }

// keptPictures is each picture the seat kept, oldest first (done_check.gaps): numbered in the
// workspace, never named, since a name the filesystem took leaves no room for more, its type
// kept for the reader and its name in the ask.  errLeft where Go does not read one as Python does,
// as a name holding U+FFFD, which a lone surrogate Python keeps in a name reads as in Go.
func keptPictures(name string) ([]picture, error) {
	var kept []picture
	read := true
	err := harness.Entries(filepath.Join(config.Home(), "state", config.SeatFileNames(name)["pictures"]), func(entry *run.Object) {
		at, timed := entry.Num("at")
		named, isName := entry.Get("name").(string)
		encoded, isData := entry.Get("data").(string)
		data, err := base64.StdEncoding.DecodeString(encoded)
		if !read || !timed || !isName || !isData || err != nil || strings.ContainsRune(named, '\ufffd') {
			read = false
			return
		}
		_, base := pythonPath(named)
		suffix := []rune(fetch.Extension(base))
		path := fmt.Sprintf("pictures/%d%s", len(kept)+1, string(suffix[:min(len(suffix), 16)]))
		kept = append(kept, picture{path, string(data), fmt.Sprintf("  - %s: %s, kept %s", path, named,
			time.Unix(int64(at), 0).Format("2006-01-02 15:04"))})
	})
	if err != nil {
		return nil, fmt.Errorf("could not check %s: %w", name, err)
	} else if !read {
		return nil, errLeft
	}
	return kept, nil
}

// runTask is a run's task as Python reads it beside the run: "" where Path.is_file says there is
// no file (missing, under a file or in a link loop, or no regular file), an error where it
// cannot tell.
func runTask(path string) (string, error) {
	info, err := os.Stat(path)
	var errno syscall.Errno
	if err == nil && !info.Mode().IsRegular() || errors.As(err, &errno) && slices.Contains([]syscall.Errno{syscall.ENOENT, syscall.ENOTDIR, syscall.EBADF, syscall.ELOOP}, errno) {
		return "", nil
	} else if err != nil {
		return "", err
	}
	data, err := os.ReadFile(path)
	return task.Text([]byte(gitcall.Decoded(string(data)))), err
}

// checker is the model that checks the seat's work: `[done_check] model`, else the reviewer a
// run of that seat's would draw now.  errLeft where Python draws it or runs its turn, settled
// before the draw writes the meters it reads (checking).
func checker(name string, record map[string]any) (string, error) {
	model, rules, err := checking(record)
	if err != nil || model != "" {
		return model, err
	}
	order, err := loop.ReadyOrder(rules, true)
	if err != nil {
		return "", fmt.Errorf("could not check %s: %w", name, err)
	}
	if len(order) == 0 {
		return "", fmt.Errorf("none of %s's reviewers can run now", name)
	}
	return order[0], nil
}

// goTurn is nil where Go runs that model's turn, errLeft where Python does.
func goTurn(model string) error {
	entry, err := config.ModelNamed(model)
	if err != nil {
		return err
	}
	if _, err := worker.Adapter(entry, ""); errors.Is(err, worker.ErrPython) {
		return errLeft
	}
	return nil
}

// checking is `[done_check] model`, else the rules the pick of a reviewer of the seat's, else of a
// worker, draws by, nothing drawn or asked: errLeft where Python draws the model or runs its turn.
func checking(record map[string]any) (string, *pick.Rules, error) {
	model, _, err := config.DoneCheck()
	if err != nil {
		return "", nil, err
	} else if model != "" {
		return model, nil, goTurn(model)
	}
	bound, err := config.BindSeat(record)
	if err != nil {
		return "", nil, errLeft
	}
	reviewers := bound.Reviewers
	if reviewers == nil {
		reviewers = bound.Workers
	}
	var listed []string
	for _, each := range reviewers {
		listed = append(listed, each.(string))
	}
	rules, ok := pick.Within(listed, nil)
	if !ok {
		return "", nil, errLeft
	}
	for _, each := range listed {
		if err := goTurn(each); err != nil {
			return "", nil, err
		}
	}
	if errors.Is(usage.Check(), usage.ErrPython) {
		return "", nil, errLeft
	}
	return "", rules, nil
}
