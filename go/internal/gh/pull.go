package gh

import (
	"errors"
	"fmt"
	"regexp"
	"strings"

	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// PullURL is a pull request's address: its owner, repository and number.
var PullURL = regexp.MustCompile(`^https://github\.com/([^/\s]+)/([^/\s]+)/pull/([0-9]+)/?$`)

// A Pull is a pull request as GitHub describes it.
type Pull struct {
	Owner, Name, Number string
	Title, Body, Author string
	State, Base, Head   string
}

// API is where the REST API keeps this pull request's repository.
func (p *Pull) API() string { return "repos/" + p.Owner + "/" + p.Name }

// View is the pull request at url, Python's pr_view, its state, base and head from one read: a
// state from another read beside that head could name a merge of a commit that never merged.
// ErrPython where Go cannot say what gh answered; any other error is why it could not be read.
func View(url string) (*Pull, error) {
	parts := PullURL.FindStringSubmatch(url)
	if parts == nil {
		return nil, fmt.Errorf("--review-pr needs a GitHub PR URL (got %s)", url)
	}
	pull := &Pull{Owner: parts[1], Name: parts[2], Number: parts[3], Author: "?"}
	value, why, err := JSON(run.Runs(), "pr", "view", url, "--json", "number,title,body,author,url,isDraft")
	if err != nil {
		return nil, err
	}
	data, _ := value.(*run.Object)
	if data == nil {
		return nil, fmt.Errorf("gh pr view %s failed: %s", url, why)
	}
	pull.Title, pull.Body = data.Str("title"), data.Str("body")
	if author := data.Dict("author"); author != nil && author.Truthy("login") {
		pull.Author = author.Str("login")
	}
	value, why, err = JSON(run.Runs(), "api", pull.API()+"/pulls/"+pull.Number)
	if err != nil {
		return nil, err
	}
	current, _ := value.(*run.Object)
	var head *run.Object
	if current != nil {
		head = current.Dict("head")
	}
	if head == nil || !head.Truthy("sha") {
		return nil, errors.New("cannot read the PR: " + why)
	}
	pull.Head = head.Str("sha")
	if base := current.Dict("base"); base != nil {
		pull.Base = base.Str("ref")
	}
	pull.State = strings.ToUpper(current.Str("state"))
	switch {
	case current.Truthy("merged"):
		pull.State = "MERGED"
	case pull.State == "":
		pull.State = "?"
	case pull.State == "OPEN":
		if pull.Head, err = BranchTip(head); err != nil {
			return nil, err
		}
	}
	return pull, nil
}

// BranchTip is an open pull request's head as git has it: its branch moves the moment a push
// succeeds, where GitHub's own read of it can show the head from before a push for seconds.
func BranchTip(head *run.Object) (string, error) {
	ref := "refs/heads/" + head.Str("ref")
	code, said := 1, "GitHub names no head repository"
	if repo := head.Dict("repo"); repo != nil && repo.Truthy("clone_url") {
		var err error
		if code, said, err = (gitcall.Git{}).Out("ls-remote", "--", repo.Str("clone_url"), ref); err != nil {
			return "", err
		}
	}
	if code == 0 {
		for _, line := range strings.Split(said, "\n") {
			if sha, found := strings.CutSuffix(line, "\t"+ref); found {
				return sha, nil
			}
		}
		said = "no " + ref
	}
	return "", errors.New("cannot read the PR head from git: " + said)
}

// ByViewer is whether author is this host's GitHub login, the account ak posts with, Python's
// by_viewer: unknown is nobody's.
func ByViewer(author string) bool {
	if author == "" || author == "?" {
		return false
	}
	value, _, err := JSON(run.Runs(), "api", "user")
	viewer, _ := value.(*run.Object)
	return err == nil && viewer != nil && viewer.Truthy("login") && strings.EqualFold(viewer.Str("login"), author)
}
