package tick

import (
	"fmt"
	"net/url"
	"strings"

	"agentkit/internal/gh"
	"agentkit/internal/gitcall"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// Incoming uses Python's one paginated search, then reads only PRs on owned checkouts and reviews
// each open head. Drafts, this account's own PRs and PRs outside those repositories owe no review.
func (t *ticking) incoming(me string) bool {
	checkouts, known := seat.Checkouts()
	if !known {
		return false
	}
	repos := map[string]string{}
	for _, checkout := range checkouts {
		origin, err := (gitcall.Git{Repo: checkout}).Try("remote", "get-url", "origin")
		if err != nil {
			return false
		}
		name := gitcall.OwnerName(origin)
		if owner, _, _ := strings.Cut(name, "/"); owner == strings.ToLower(me) {
			repos[incomingKey(origin, name)] = checkout
		}
	}
	if len(repos) == 0 {
		return true
	}
	value, why, err := gh.JSON(run.Runs(), "api", "--paginate", "search/issues", "-X", "GET", "-f",
		"q=is:pr is:open draft:false user:"+me+" -author:"+me, "-f", "per_page=100")
	if err != nil {
		return false
	}
	pages, ok := value.([]any)
	if !ok {
		t.log.line("WARN incoming PR discovery failed: " + why)
		return true
	}
	for _, page := range pages {
		answer, ok := page.(*run.Object)
		if !ok || answer.List("items") == nil {
			return false
		}
		for _, item := range answer.List("items") {
			found, ok := item.(*run.Object)
			if !ok {
				return false
			}
			pull := found.Dict("pull_request")
			if pull == nil || !pull.Truthy("html_url") || !found.Truthy("number") || found.Truthy("draft") {
				continue
			}
			if author := found.Dict("user"); author != nil && strings.EqualFold(author.Str("login"), me) {
				continue
			}
			address, err := url.Parse(pull.Str("html_url"))
			if err != nil {
				return false
			}
			parts := strings.Split(strings.Trim(address.Path, "/"), "/")
			if len(parts) < 2 {
				continue
			}
			name := strings.ToLower(strings.Join(parts[:2], "/"))
			checkout := repos[strings.ToLower(address.Hostname())+"/"+name]
			if checkout == "" {
				checkout = repos[name]
			}
			if checkout == "" {
				continue
			}
			value, why, err := gh.JSON(checkout, "api", fmt.Sprintf("repos/%s/pulls/%s", name, run.Text(found.Get("number"))))
			if err != nil {
				return false
			}
			pr, ok := value.(*run.Object)
			if !ok {
				t.log.line("WARN " + pull.Str("html_url") + ": PR discovery failed: " + why)
				continue
			}
			if pr.Str("state") == "open" && !pr.Truthy("draft") && pr.Truthy("html_url") &&
				pr.Dict("head") != nil && pr.Dict("head").Truthy("sha") &&
				(pr.Dict("user") == nil || pr.Dict("user").Str("login") != me) && !t.review(pr, me) {
				return false
			}
		}
	}
	return true
}

func incomingKey(origin, name string) string {
	if !strings.Contains(origin, "://") && strings.Contains(origin, "@") {
		_, origin, _ = strings.Cut(origin, "@")
		origin = "ssh://" + strings.Replace(origin, ":", "/", 1)
	}
	parsed, _ := url.Parse(origin)
	if parsed == nil || parsed.Hostname() == "" {
		return name // local origins follow the owner/name convention
	}
	host := strings.ToLower(parsed.Hostname())
	if host == "ssh.github.com" || host == "www.github.com" {
		host = "github.com"
	}
	return host + "/" + name
}
