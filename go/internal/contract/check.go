package contract

import (
	"cmp"
	"context"
	"crypto/rand"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/run"
	"agentkit/internal/usage"
	"agentkit/internal/worker"
)

// A target is a harness the check proves: its name, its manifest's `[check]` block, its model there on
// the provider config.toml runs that id on, else on its first model's, and the login it runs on,
// "" for the usual one.
type target struct {
	name    string
	block   map[string]any
	model   config.Model
	account string
}

// plan is each harness of names as the check proves it, its windows judged on snapshot, and false
// where the home or any is a case Python's: `models_off` naming a model, as a turn judges the
// config's model of the harness's name off (worker.Refused) where Python judges the `[check]`
// model itself; a harness running several providers' models, whose model is the config's choice
// of them (contract.selected_model); one whose turn Go does not run (worker.Adapter); or one whose
// provider a reading the check judges holds refused as Python keeps it (usage.Unread).
func plan(names []string, snapshot string) ([]target, bool) {
	if _, off, _ := config.ModelList(); len(off) > 0 {
		return nil, false
	}
	entries, _ := config.Entries()
	order, _ := config.EntryNames()
	var planned []target
	for _, name := range names {
		if providers, _ := config.Section(name, "providers"); len(providers) > 0 {
			return nil, false
		}
		block, _ := config.Section(name, "check")
		id, _ := block["model"].(string)
		effort, _ := block["effort"].(string)
		// the provider of the first model running that id on the harness, else of its first model
		provider := ""
		for _, same := range []bool{true, false} {
			for _, entry := range order {
				if provider == "" && entries[entry].Harness == name && (!same || entries[entry].ID == id) {
					provider = cmp.Or(entries[entry].Provider, name)
				}
			}
		}
		model := config.Model{Provider: cmp.Or(provider, name), ID: id, Harness: name, Efforts: map[string]string{"effort": effort}}
		account := login(model.Provider)
		if _, err := worker.Adapter(model, account); errors.Is(err, worker.ErrPython) {
			return nil, false
		}
		for _, path := range []string{snapshot, cache()} {
			if record, _ := providers(path).Get(model.Provider).(*run.Object); usage.Unread(record) {
				return nil, false
			}
		}
		planned = append(planned, target{name, block, model, account})
	}
	return planned, true
}

// A tally is the check's counts: harnesses passed, failed and skipped, the turns that proved
// something, and the harnesses installed here with their login.
type tally struct{ passed, failed, skipped, calls, installed int }

// check proves each harness, its turns in workspaces under root, its windows judged on snapshot,
// its lines to out, and what its turns left running to errOut: the counts, and whether ctx ended
// it first.
func check(ctx context.Context, targets []target, root, snapshot string, out, errOut io.Writer) (tally, bool) {
	var counts tally
	report := func(kind, name, message string) {
		label := strings.TrimSpace("3 " + name)
		fmt.Fprintf(out, "%s  %s: %s\n", kind, label, message)
		if failed := os.Getenv("AK_LIVE_FAILED"); failed != "" && (kind == "FAIL" || kind == "SKIP") {
			if kind == "SKIP" {
				failed += ".spent"
			}
			if file, err := os.OpenFile(failed, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666); err == nil {
				fmt.Fprintln(file, label)
				file.Close()
			}
		}
	}
	for _, each := range targets {
		if ctx.Err() != nil {
			return counts, true
		}
		kind, message, err := prove(ctx, each, root, snapshot, &counts, func(kind, message string) {
			report(kind, each.name, message)
		}, errOut)
		if errors.Is(err, worker.ErrInterrupted) || ctx.Err() != nil {
			return counts, true
		}
		if err != nil {
			kind, message = "FAIL", err.Error()
		}
		report(kind, each.name, message)
		switch kind {
		case "PASS":
			counts.passed++
		case "SKIP":
			counts.skipped++
		case "FAIL":
			counts.failed++
		}
	}
	if counts.installed == 0 {
		report("FAIL", "", "no harness here is installed with its login; the check needs one")
		counts.failed++
	}
	return counts, false
}

// prove is the verdict on one harness and why: not installed here with its login, a spent
// window, the first turn's refusal or what it missed, else the resumed turn's.  As the turns
// begin it reports what it checks.
func prove(ctx context.Context, h target, root, snapshot string, counts *tally, report func(kind, message string), errOut io.Writer) (string, string, error) {
	if why, broken := unavailable(h.name, h.account); broken {
		return "FAIL", why, nil
	} else if why != "" {
		return "NOT CHECKED", why, nil
	}
	counts.installed++
	effort, _ := h.block["effort"].(string)
	_, named := h.block["model"].(string)
	// config.toml's `default`, the harness's own model, is no model to prove the contract at
	if !named || strings.TrimFunc(h.model.ID, config.Space) == "" || strings.TrimFunc(effort, config.Space) == "" || h.model.ID == "default" {
		return "", "", errors.New("adapter .toml needs [check] with an explicit model and effort")
	}
	if when, spent := spentUntil(h.model, h.name, snapshot); spent {
		return "SKIP", "the " + h.model.Provider + " subscription window is spent until " + when, nil
	}
	workspace, first := filepath.Join(root, h.name, "workspace"), filepath.Join(root, h.name, "make")
	if err := os.MkdirAll(workspace, 0o777); err != nil {
		return "", "", err
	}
	self, _, err := config.Running()
	if err != nil {
		return "", "", err
	}
	filename := "hello-" + nonce() + ".txt"
	body := "Run: printf 'hello\\n' > " + filename + "\nRun: " + commandhelp.ShellJoin([]string{self}) +
		" hand-in done\nReply DONE.\n"
	report("CHECK", h.model.ID+" at "+effort)
	env := environ(h.account)
	word, undo, err := plant(h.name, env)
	if err != nil {
		return "", "", err
	}
	defer undo()
	// No build or review rules: both turns ask only what this contract proves.
	given := worker.Given{Context: ctx, Model: &h.model, Bare: true, Account: h.account, Env: []string{config.AccountEnv(h.account)}}
	code, session, err := worker.Turn(h.name, "executor-scratch", body, workspace, first, "", given, errOut)
	if err != nil {
		return "", "", err
	}
	if why, err := refusal(h.model, code, first, snapshot); why != "" || err != nil {
		return "SKIP", "was refused: " + why, err
	}
	answer := final(first)
	var missing []string
	if code != 0 {
		missing = append(missing, fmt.Sprintf("adapter exited %d", code))
	}
	if handin.Answer(filepath.Join(workspace, filename)) != "hello\n" {
		missing = append(missing, "file did not match the prompt")
	}
	if strings.TrimFunc(answer, config.Space) == "" {
		missing = append(missing, "final.md is empty")
	}
	if closing, found := handin.Read(filepath.Join(first, handin.File)); !found || !closing.Done() {
		missing = append(missing, "no checked hand-in done")
	}
	if strings.TrimFunc(handin.Answer(filepath.Join(first, "session_id")), config.Space) == "" {
		missing = append(missing, "no session_id")
	}
	if word != "" && strings.Contains(answer, word) {
		missing = append(missing, "read a file of its own beside the prompt: the box let "+
			strings.Join(unswitched(h.name, env), " or ")+" through")
	}
	if len(missing) > 0 {
		return "FAIL", strings.Join(missing, "; "), nil
	}
	counts.calls++
	// Recall must come from the resumed conversation, not a listing of the workspace.
	if err := os.Remove(filepath.Join(workspace, filename)); err != nil {
		return "", "", err
	}
	recall := filepath.Join(root, h.name, "recall")
	code, _, err = worker.Turn(h.name, "executor-scratch", "What file did you just create? Reply with the filename only.\n", workspace, recall, session, given, errOut)
	if err != nil {
		return "", "", err
	}
	if why, err := refusal(h.model, code, recall, snapshot); why != "" || err != nil {
		return "SKIP", "resume was refused: " + why, err
	}
	if answer := final(recall); code != 0 || !recalled(answer, filename) {
		shown := []rune(answer)
		return "FAIL", fmt.Sprintf("resume exited %d; final.md = %s", code, commandhelp.Quote(string(shown[:min(len(shown), 120)]))), nil
	}
	counts.calls++
	return "PASS", "wrote the file, handed in done, returned final.md and session_id, resumed and recalled the file", nil
}

// nonce is eight random hex digits.
func nonce() string {
	var bytes [4]byte
	rand.Read(bytes[:])
	return fmt.Sprintf("%x", bytes)
}

// recalled is whether the reply names the file, bare, in backticks or as a Markdown link's text: a
// model may write a file it made as a link to it, which names the same file.
func recalled(final, filename string) bool {
	reply := strings.TrimFunc(final, config.Space)
	link, linked := strings.CutPrefix(reply, "["+filename+"](")
	return reply == filename || reply == "`"+filename+"`" ||
		linked && strings.HasSuffix(link, ")") && !strings.Contains(link[:len(link)-1], ")")
}

// final is the answer a turn left in out, as Python reads it.
func final(out string) string {
	return handin.Answer(filepath.Join(out, "final.md"))
}
