package tick

import (
	"fmt"
	"slices"
	"strings"

	"agentkit/internal/gitcall"
)

// revertSchema is what a broken live release's seat is told instead of a revert where its diff
// changes a schema (watch.REVERT_SCHEMA).
const revertSchema = "Live health fails; no revert: a schema change cannot be undone by a code revert."

// revertLine is after_merge_revert from the broken release it picked to where its revert starts:
// the line the release's seat is told instead of a break.  A code revert cannot undo a schema
// change, so a diff from the release's first parent touching a `migrations` or `alembic`
// directory, or a `.sql` file, is named instead; any other is reverted (revertRun).  A parent the
// checkout lacks is fetched, from origin, else the pull request's repository; where neither gives
// it, or the diff cannot be read, that is said and "" told.
func revertLine(each *merge, say func(string)) (string, error) {
	g, parent := gitcall.Git{Repo: each.record.Str("repo")}, each.sha+"^"
	missing, _, err := g.Out("cat-file", "-e", parent)
	if err != nil {
		return "", err
	}
	if missing != 0 {
		shallow, err := g.Must("rev-parse", "--is-shallow-repository")
		if err != nil {
			return "", err
		}
		fetch := []string{"--no-tags"}
		if shallow == "true" {
			fetch = append(fetch, "--deepen=1")
		}
		code, why, err := g.Fetch(append(fetch, "origin", each.sha)...)
		if err == nil && code != 0 {
			host, owner, name := pullRepo(each.pr)
			code, why, err = g.Fetch(append(fetch, "https://"+host+"/"+owner+"/"+name+".git", each.sha)...)
		}
		if err != nil {
			return "", err
		}
		if code != 0 {
			say(fmt.Sprintf("WARN cannot fetch run %s's release for a revert: %s", each.name, why))
			return "", nil
		}
	}
	code, paths, err := g.Out("diff", "--name-only", "--no-renames", "-z", parent, each.sha)
	if err != nil {
		return "", err
	}
	if code != 0 {
		say(fmt.Sprintf("WARN cannot inspect run %s's release for a revert: %s", each.name, paths))
		return "", nil
	}
	for _, path := range strings.Split(paths, "\x00") {
		parts := strings.Split(path, "/")
		name := parts[len(parts)-1]
		dot := strings.LastIndex(name, ".") // a suffix as Python's Path has one: never a whole name
		if slices.Contains(parts, "migrations") || slices.Contains(parts, "alembic") || dot > 0 && strings.ToLower(name[dot:]) == ".sql" {
			return revertSchema, nil
		}
	}
	return revertRun(each, say)
}
