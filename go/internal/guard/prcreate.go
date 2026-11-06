package guard

import (
	"cmp"
	"fmt"
	"maps"
	"os"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/seat"
	"agentkit/internal/size"
)

// rulesRef is a project's default branch as last fetched, Python's config.RULES_REF.
const rulesRef = "refs/remotes/origin/HEAD"

// `gh pr create`'s options, as gh reads them: the letters of its short switches, its long ones, and
// those that take a value (-R/--repo among them), each short name by its long one.  A call holding
// any other -- help, or one a later gh adds -- runs unmeasured: what that option makes of the next
// word cannot be told.
const prCreateLetters = "defw"

var (
	prCreateSwitches = []string{"--draft", "--dry-run", "--editor", "--fill", "--fill-first", "--fill-verbose", "--no-maintainer-edit", "--web"}
	prCreateValued   = map[string]string{"-a": "--assignee", "-B": "--base", "-b": "--body", "-F": "--body-file", "-H": "--head",
		"-l": "--label", "-m": "--milestone", "-p": "--project", "-R": "--repo", "-r": "--reviewer", "-T": "--template", "-t": "--title",
		"--recover": "--recover"}
)

// prCreateOptions is the value gh reads for each valued option a `gh pr create` call gives, by its
// long name, the last one, and false where the call holds an option not known here.  A value rides
// in its option's word (`--base=x`, `-Bx`, `-B=x`, `-fBx` after switches; `-t=` is an empty title)
// or is the next word, whatever that reads like (`--title --base=x` is a title).  A switch may
// carry its own value (`--fill=true`, `-f=false`), which ends its word.
func prCreateOptions(args []string) (map[string]string, bool) {
	found := map[string]string{}
	for at := 0; at < len(args) && args[at] != "--"; at++ {
		word := args[at]
		var name, value string
		var attached bool
		switch {
		case strings.HasPrefix(word, "--"):
			if name, value, attached = strings.Cut(word, "="); slices.Contains(prCreateSwitches, name) {
				continue
			}
		case strings.HasPrefix(word, "-") && word != "-":
			rest := strings.TrimLeft(word[1:], prCreateLetters)
			if rest == "" || rest[0] == '=' {
				continue
			}
			name, value, attached = "-"+rest[:1], strings.TrimPrefix(rest[1:], "="), rest[1:] != ""
		default:
			continue // `pr`, `create`
		}
		if name = cmp.Or(prCreateValued[name], name); !slices.Contains(slices.Collect(maps.Values(prCreateValued)), name) {
			return nil, false
		}
		if !attached {
			if at++; at == len(args) {
				return nil, false
			}
			value = args[at]
		}
		found[name] = value
	}
	return found, true
}

// prCreateRefusal is why the seat may not open this pull request, Python's pr_create_refusal: its
// branch adds more lines than the seat builds, as the review gate counts and limits them
// (size.Seat, with the project's numbers), against the PR's base, so no PR is left open to close.
// It reads --base/-B (else the default branch, origin/HEAD) and --head/-H (else the branch checked
// out).  What it cannot measure runs and meets the gate: an option it does not know, a checkout of
// no project ak knows, a repository named by --repo/-R or GH_REPO (which one gh means hangs on its
// host settings, not on the checkout), a base with no `origin/` ref here, and a head that is no
// local branch -- a fork's `owner:branch`, or a detached HEAD.
func prCreateRefusal(args []string) (string, error) {
	options, known := prCreateOptions(args)
	if !known || options["--repo"] != "" || os.Getenv("GH_REPO") != "" {
		return "", nil
	}
	top, err := gitcall.Git{}.Try("rev-parse", "--show-toplevel")
	project := seat.CheckoutOf(top)
	if err != nil || project == "" {
		return "", err
	}
	git := gitcall.Git{Repo: top}
	branch := options["--head"]
	if branch == "" {
		if branch, err = git.Try("symbolic-ref", "--short", "-q", "HEAD"); err != nil || branch == "" {
			return "", err
		}
	}
	target, head := rulesRef, "refs/heads/"+branch
	if base := options["--base"]; base != "" {
		target = "refs/remotes/origin/" + base
	}
	for _, ref := range []string{target, head} {
		if found, err := git.Try("rev-parse", "--verify", "--quiet", ref); err != nil || found == "" {
			return "", err
		}
	}
	// the project's numbers as Python's config.policy reads them: from its default branch's tip,
	// the host's where it has none, and origin is never asked
	tip, _ := gitcall.Git{Repo: project}.Try("rev-parse", "--verify", "--quiet", rulesRef)
	numbers, err := config.HostNumbers()
	if tip != "" {
		numbers, err = config.ProjectNumbers(project, func(key string) string { return gitcall.DeclaredAt(project, tip, key) })
	}
	if err != nil {
		return "", err
	}
	counted, over, err := size.Seat(git, target, head, numbers.SeatLines)
	if err != nil || !over {
		return "", err
	}
	most, _ := numbers.SeatLines.Most()
	way := fmt.Sprintf("Write it as a task; `from: %s` keeps what was built.", branch)
	if numbers.ReviewLines == config.AtMost(0) {
		way = "Split it into smaller PRs."
	}
	return fmt.Sprintf("ak refused `gh pr create`: %s adds %d lines (generated files and unchanged moves aside): "+
		"too big for the seat, which builds at most %d added lines. %s", branch, counted, most, way), nil
}
