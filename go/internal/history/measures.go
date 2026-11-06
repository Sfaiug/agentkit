package history

import (
	"cmp"
	"os"
	"strings"

	"agentkit/internal/gitcall"
	"agentkit/internal/run"
	"agentkit/internal/size"
)

// measured is what Python's history_finish reads from git beside the ending, each nil where git
// cannot say: the files the run changed against its base, as JSON; the lines a merged change
// landed; and the bytes of the AGENTS.md its workers were handed, 0 for none.  Git is read in the
// run's checkout while it stands, else in its repository at the tip the record names.
func measured(record *run.Object) (files, lines, rules any) {
	worktree, base := record.Str("worktree"), record.Str("base_sha")
	info, err := os.Stat(worktree)
	present := worktree != "" && err == nil && info.IsDir()
	tip := cmp.Or(record.Str("delivery_sha"), cmp.Or(record.Dict("review"), run.NewObject()).Str("head_sha"))
	git, head := gitcall.Git{Repo: record.Str("repo")}, tip
	if present {
		git, head = gitcall.Git{Repo: worktree}, "HEAD"
	}
	if worktree != "" && base != "" && git.Repo != "" && head != "" {
		if said, err := git.Try("diff", "--name-only", "-z", "--no-renames", base+"..."+head); err == nil {
			names := []any{}
			for _, name := range strings.Split(said, "\x00") {
				if name != "" {
					names = append(names, name)
				}
			}
			files = run.Line(names)
		}
	}
	// a merge counts to the tip it recorded first, against the target's tip it recorded, whose
	// attributes say which files are generated, else its base
	if against := cmp.Or(record.Str("target_sha"), base); record.Truthy("merged") && against != "" && git.Repo != "" && head != "" {
		if counted, err := size.Lines(git, against, cmp.Or(tip, head)); err == nil {
			lines = counted
		}
	}
	if git.Repo != "" && base != "" {
		rules = rulesBytes(git, base)
	}
	return files, lines, rules
}

// rulesBytes is the size of AGENTS.md at rev as a checkout holds it, git's line-end conversion and
// filters applied: what a harness reads.  No file, or a link, whose text is a path, hands its
// workers no rules; nil where git cannot read it.
func rulesBytes(git gitcall.Git, rev string) any {
	listed, err := git.Must("ls-tree", rev, "--", "AGENTS.md")
	if err != nil {
		return nil
	}
	if listed == "" || strings.HasPrefix(listed, "120000 ") {
		return 0
	}
	code, read, _, err := git.Bytes("cat-file", "--filters", rev+":AGENTS.md")
	if err != nil || code != 0 {
		return nil
	}
	return len(read)
}
