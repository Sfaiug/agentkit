package seat

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/hooks"
	"agentkit/internal/run"
)

// The canonical rulebook is shared by a seat's launch and its prompt hook.

const (
	rulesRef = "refs/remotes/origin/HEAD"
	NameLine = "This seat is unnamed. Before your turn ends, name it with `ak orch rename --auto " +
		"<name>`: the shortest possible name, at most three words, saying what the work is."
)

var universal = strings.NewReplacer("\r\n", "\n", "\r", "\n")

func ownFile(kind, name string) string {
	return filepath.Join(config.Home(), "state", config.SeatFileNames(name)[kind])
}

func rstrip(text string) string { return strings.TrimRightFunc(text, config.Space) }

func digest(data []byte) string { return hooks.RulebookDigest(data) }

// Rulebook is what the seat's rulebook holds if it opens now (config.seat_rulebook): ak's rules at
// its project's numbers, else this host's, then this host's own, each read as Python reads text;
// the AGENTS.md of the project its record files it under, as on that project's default branch; an
// unnamed seat's instruction to name itself; and, last, where the conversations it moved from are.
func Rulebook(name string) (string, error) { return rulebook(name, nil) }

func rulebook(name string, project *string) (string, error) {
	shipped, err := os.ReadFile(filepath.Join(config.Repo(), "orchestrator.md"))
	if err != nil {
		return "", err
	}
	local, err := os.ReadFile(filepath.Join(config.Home(), "rules.md"))
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return "", err
	}
	record, err := run.ReadJSON(ownFile("session", name))
	if errors.Is(err, run.ErrLoneSurrogate) {
		return "", err
	}
	repo := ""
	if record != nil {
		repo = record.Str("repo")
	}
	if project != nil {
		repo = *project
	}
	body := universal.Replace(string(shipped))
	if repo == "" {
		body = config.InForce(body)
	} else { // at the numbers its project's front matter sets, Python's rulebook_text(repo)
		numbers, err := run.LaunchPolicy(repo)
		if err != nil {
			return "", err
		}
		body = config.InForceAt(body, numbers)
	}
	if strings.TrimFunc(string(local), config.Space) != "" {
		body = rstrip(body) + "\n\n" + universal.Replace(string(local))
	}
	if repo != "" {
		if project := gitcall.AgentsBody(repo, rulesRef); project != "" {
			body = fmt.Sprintf("%s\n\n# The project's AGENTS.md\n\nThe rules of %s, the project this session is filed under, "+
				"as on its default branch: its workers get the same.\n\n%s\n", rstrip(body), filepath.Base(repo), project)
		}
	}
	if record == nil {
		return body, nil
	}
	if record.Truthy("unnamed") {
		body = namingItself(body)
	}
	// where, not what: a harness may take its rulebook as one argument, which Linux caps at 128 KiB
	handed := ownFile("handover", name)
	if info, err := os.Stat(handed); err == nil && info.Mode().IsRegular() {
		body = fmt.Sprintf("%s\n\n# Where this seat's work stands\n\nThis seat moved to you from another model under the same name. "+
			"Its runs go on and report to you (`ak run status`), and its plan is `ak plan`. What was said in its conversation so "+
			"far, oldest first, is in %s: read its end before anything else.\n", rstrip(body), handed)
	}
	return body, nil
}

// namingItself is a rulebook with an unnamed seat's instruction to name itself.
func namingItself(body string) string {
	return rstrip(body) + "\n\n" + NameLine + "\n"
}
