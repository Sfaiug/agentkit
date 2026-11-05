package gitcall

import (
	"cmp"
	"fmt"
	"strings"

	"agentkit/internal/task"
)

// rulesRef is a project's default branch as last fetched, Python's config.RULES_REF.
const rulesRef = "refs/remotes/origin/HEAD"

// RulesTip is the commit rulesRef names in repo, "" for none or no repo: a clone that has not
// cached it asks origin first, as Python's launch_policy does, so no other branch's rules stand in.
func RulesTip(repo string) string {
	if repo == "" {
		return ""
	}
	g := Git{Repo: repo}
	tip, err := g.Try("rev-parse", "--verify", "--quiet", rulesRef)
	if err == nil && tip == "" {
		DefaultBase(repo) // read for what it caches: a default it cannot find leaves the rules unread
		tip, err = g.Try("rev-parse", "--verify", "--quiet", rulesRef)
	}
	if err != nil {
		return ""
	}
	return tip
}

// ContractRefusal is why no task may launch in repo, "" for none or a scratch task's repo "",
// Python's require_project_contract: a task cannot supply its own contract, so it is read from the
// default tip alone, before any run exists.
func ContractRefusal(repo string) string {
	if repo == "" {
		return ""
	}
	tip := cmp.Or(RulesTip(repo), rulesRef) // never "": `git show :AGENTS.md` reads the checkout's index
	var missing []string
	for _, line := range task.Contract {
		if _, declared := declaredAt(repo, tip, line.Key, nil); !declared {
			missing = append(missing, line.Key+": "+line.Meaning)
		}
	}
	if missing == nil {
		return ""
	}
	return fmt.Sprintf("%s/AGENTS.md on %s is missing %s.", repo, rulesRef, strings.Join(missing, "; "))
}

// Suite is the target's `tests:` command at ref, else the checkout's, "" for none: Python's
// declared_suite.  A change cannot loosen its own landing checks, so the checkout never stands in
// for a line ref declares, `none` among them.
func Suite(checkout, ref string) string {
	if ref != "" {
		if suite, declared := declaredAt(checkout, ref, "tests", nil); declared {
			return suite
		}
	}
	return Declared(checkout, "tests")
}

// declaredAt is DeclaredAt, and whether AGENTS.md at ref declares the key at all.
func declaredAt(repo, ref, key string, env []string) (string, bool) {
	text, err := Git{Repo: repo, Env: env}.Try("show", ref+":AGENTS.md")
	if err != nil {
		return "", false
	}
	return task.FrontDeclared(text, key)
}
