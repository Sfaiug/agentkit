package cli

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/handin"
	"agentkit/internal/harness"
	"agentkit/internal/loop"
	"agentkit/internal/notify"
	"agentkit/internal/pick"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/task"
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
	"- conversation.md: its whole conversation as its harness keeps it, oldest first. The user side",
	"  holds ak's lines as well as the owner's: only owner/ says which words are the owner's.",
	"- plan.md: its plan, `- [x]` a line done and `- [ ]` one open.",
	"- runs/: each run it launched: its title, state, whether it merged, its PR and its task.",
	"",
	"Read each message of the owner's where it stands in the conversation: a \"yes\" or \"the second",
	"one\" takes what the seat proposed just before. A gap is something the owner asked to be built or",
	"changed that no done plan line and no merged run delivered, or a question or a request to explain",
	"that no reply of the seat's answered. Only a later message of the owner's drops or changes an",
	"ask; the seat's replies never do.",
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
	name, found, err := ownerGaps(args[0], errOut)
	switch {
	case errors.Is(err, errLeft):
		return notImplemented(errOut, "orch check")
	case errors.Is(err, worker.ErrInterrupted):
		fmt.Fprintf(errOut, "\nak orch: %s\n", err)
		return 130
	case err != nil:
		fmt.Fprintf(errOut, "ak orch: %s\n", err)
		return 2
	case len(found) == 0:
		fmt.Fprintf(out, "%s: its work holds everything its owner asked\n", name)
		return 0
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
	return 1
}

// ownerWords is one message or answer of the owner's: when, their words, and the file of the
// workspace that shows them.
type ownerWords struct {
	at           float64
	words, shown string
}

// ownerGaps is the seat's name and the findings of one model's turn over what the seat was asked
// and did that quote a message or answer of its owner's word for word (done_check.gaps): whether
// a quote is the owner's is decided here, never by the model.  errLeft is a case Python carries.
func ownerGaps(seat string, errOut io.Writer) (string, []*run.Object, error) {
	if err := config.Check(); err != nil {
		return "", nil, err
	}
	name, record, err := config.ResolveSession(seat)
	if err != nil {
		return "", nil, err
	}
	conversation, messages, err := notify.OwnerMessages(name)
	if err != nil {
		return "", nil, errLeft
	}
	if conversation == "" {
		return "", nil, fmt.Errorf("no seat named %s whose conversation ak can read", name)
	}
	said, cards, known, err := harness.Answered(config.SeatHarness(name), record)
	if !known {
		return "", nil, errLeft
	} else if err != nil {
		return "", nil, fmt.Errorf("could not check %s: %w", name, err)
	}
	var owner []ownerWords
	for _, message := range messages {
		owner = append(owner, ownerWords{message.At, message.Text, message.Text})
	}
	for _, card := range cards {
		owner = append(owner, ownerWords{card.At, card.Answer, cardShown(card)})
	}
	slices.SortStableFunc(owner, func(a, b ownerWords) int { return cmp.Compare(a.at, b.at) })
	if len(owner) == 0 {
		return name, nil, nil // asked nothing, so nothing is missing
	}
	model, err := checker(name, record)
	if err != nil {
		return "", nil, err
	}
	files, err := checkFiles(name, owner, said)
	if err != nil {
		return "", nil, err
	}
	fmt.Fprintf(errOut, "ak orch check: %s reads what %s was asked and did\n", model, name)
	tmp, err := os.MkdirTemp(filepath.Join(config.Home(), "tmp"), "check-"+name+"-")
	if err != nil {
		return "", nil, err
	}
	defer os.RemoveAll(tmp)
	workspace, into := filepath.Join(tmp, "workspace"), filepath.Join(tmp, "out")
	for relative, text := range files {
		path := filepath.Join(workspace, filepath.FromSlash(relative))
		if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
			return "", nil, err
		}
		if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
			return "", nil, err
		}
	}
	// an existing role, the reviewer's of a workspace, whose hand-in takes findings and refuses a
	// quote its file does not hold
	ask := strings.NewReplacer("{name}", name, "{workspace}", workspace).Replace(checkAsk)
	var expired *worker.LoginExpired
	switch _, _, err := worker.Turn(model, "reviewer-scratch", ask, workspace, into, "", worker.Given{}, errOut); {
	case errors.Is(err, worker.ErrPython):
		return "", nil, errLeft
	case errors.Is(err, worker.ErrInterrupted), errors.As(err, &expired):
		return "", nil, err
	case err != nil && !errors.Is(err, worker.ErrSilent):
		return "", nil, fmt.Errorf("could not check %s: %w", name, err)
	}
	review, _ := handin.Read(filepath.Join(into, handin.File))
	if review == nil || !review.Done() {
		return "", nil, fmt.Errorf("%s could not check %s: its turn did not end in `ak hand-in done`", model, name)
	}
	var found []*run.Object
	for _, row := range review.Of("finding") {
		quote := row.Dict("evidence").Str("quote")
		if strings.TrimFunc(quote, config.Space) != "" && slices.ContainsFunc(owner, func(each ownerWords) bool {
			return strings.Contains(each.words, quote)
		}) {
			found = append(found, row)
		}
	}
	return name, found, nil
}

// checkFiles is the checking turn's workspace, each file by its path there: the owner's words a
// file each, the seat's conversation, its plan and each run it launched.  errLeft where Go does
// not read the runs as Python does.
func checkFiles(name string, owner []ownerWords, said []harness.Turn) (map[string]string, error) {
	files := map[string]string{}
	for n, each := range owner {
		files[fmt.Sprintf("owner/%d.md", n+1)] = each.shown
	}
	var conversation, planned strings.Builder
	for _, turn := range said {
		fmt.Fprintf(&conversation, "**%s:** %s\n\n", turn.Who, turn.Text)
	}
	lines, err := plan.Lines(name)
	if err != nil {
		return nil, err
	}
	for _, line := range lines {
		planned.WriteString(line + "\n")
	}
	files["conversation.md"], files["plan.md"] = conversation.String(), planned.String()
	var unread error
	if !run.Every(func(dir string, state *run.Object) bool {
		if run.Seat(state) != name {
			return true
		}
		taskText := ""
		if info, err := os.Stat(filepath.Join(dir, "task.md")); err == nil && info.Mode().IsRegular() {
			data, err := os.ReadFile(filepath.Join(dir, "task.md"))
			if unread = err; err != nil {
				return false
			}
			taskText = task.Text([]byte(gitcall.Decoded(string(data))))
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
			return nil, fmt.Errorf("could not check %s: %w", name, unread)
		}
		return nil, errLeft
	}
	return files, nil
}

// checker is the model that checks the seat's work: `[done_check] model`, else the reviewer a
// run of that seat's would draw now.  errLeft where Python draws it or runs its turn.
func checker(name string, record map[string]any) (string, error) {
	model, err := config.DoneCheckModel()
	if err == nil && model == "" {
		model, err = readyReviewer(name, record)
	}
	if err != nil {
		return "", err
	}
	entry, err := config.ModelNamed(model)
	if err != nil {
		return "", err
	}
	if _, err := worker.Adapter(entry); errors.Is(err, worker.ErrPython) {
		return "", errLeft
	}
	return model, nil
}

// readyReviewer is the first of the seat's reviewers, else its workers, that a pick draws now.
func readyReviewer(name string, record map[string]any) (string, error) {
	bound, err := config.BindSeat(record)
	if err != nil {
		return "", errLeft
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
		return "", errLeft
	}
	order, ok := loop.ReadyOrder(rules, true)
	if !ok {
		return "", errLeft
	}
	if len(order) == 0 {
		return "", fmt.Errorf("none of %s's reviewers can run now", name)
	}
	return order[0], nil
}

// cardShown is an answer's file: the question and choices the seat wrote, then the owner's answer.
func cardShown(card harness.Card) string {
	shown := "The seat asked on its question card: " + card.Question + "\n"
	for _, choice := range card.Choices {
		shown += "- " + choice.Label + ": " + choice.Description + "\n"
	}
	return shown + "\nThe owner answered:\n" + card.Answer + "\n"
}
