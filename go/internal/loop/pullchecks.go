package loop

import (
	"cmp"
	"errors"
	"fmt"
	"maps"
	"slices"
	"strings"
	"time"

	"agentkit/internal/gh"
	"agentkit/internal/run"
)

const (
	checksCap  = time.Hour // a check suite still running after an hour is not going to finish
	checksPoll = 10 * time.Second
	// classicChecks reads the classic protection rule through GraphQL, which needs no administration
	// access, where branch rules cover rulesets only.
	classicChecks = "query($owner:String!,$name:String!,$branch:String!){repository(owner:$owner,name:$name){ref(qualifiedName:$branch){branchProtectionRule{requiresStatusChecks requiredStatusChecks{context app{databaseId}}}}}}"
)

// A wanted is the checks a branch requires: each name's apps, "" for any.
type wanted map[string]map[string]bool

func (w wanted) add(name any, app string) error {
	text, _ := name.(string)
	if text == "" {
		return errors.New("required check has no name")
	}
	if w[text] == nil {
		w[text] = map[string]bool{}
	}
	w[text][app] = true
	return nil
}

// requiredOf is the checks a branch requires, ruleset and classic: why it cannot say otherwise.
func requiredOf(l *loop, pull *gh.Pull, target string) (wanted, string, error) {
	need := wanted{}
	endpoint := pull.API() + "/rules/branches/" + strings.ReplaceAll(escaped(target), "/", "%2F") + "?per_page=100"
	value, why, err := gh.JSON(l.dir, "api", "--paginate", endpoint)
	if err != nil {
		return nil, "", err
	}
	unread := func(why string) (wanted, string, error) {
		return nil, "cannot read required checks for " + target + ": " + why, nil
	}
	pages, ok := value.([]any)
	if !ok {
		return unread(cmp.Or(why, "invalid branch rules response"))
	}
	for _, page := range pages {
		rules, ok := page.([]any)
		if !ok {
			return unread("invalid branch rules response")
		}
		for _, each := range rules {
			rule, _ := each.(*run.Object)
			if rule == nil || rule.Str("type") != "required_status_checks" {
				continue
			}
			parameters := rule.Dict("parameters")
			if parameters == nil {
				return unread("invalid branch rules response")
			}
			for _, item := range parameters.List("required_status_checks") {
				check, _ := item.(*run.Object)
				if check == nil {
					return unread("required check has no name")
				}
				app := ""
				if check.Truthy("integration_id") {
					app = run.Text(check.Get("integration_id"))
				}
				if err := need.add(check.Get("context"), app); err != nil {
					return unread(err.Error())
				}
			}
		}
	}
	value, why, err = gh.JSON(l.dir, "api", "graphql", "-f", "query="+classicChecks, "-f", "owner="+pull.Owner, "-f", "name="+pull.Name, "-f", "branch=refs/heads/"+target)
	if err != nil {
		return nil, "", err
	}
	unclassic := func(why string) (wanted, string, error) {
		return nil, "cannot read classic required checks for " + target + ": " + why, nil
	}
	classic, _ := value.(*run.Object)
	if classic == nil || classic.Truthy("errors") {
		return unclassic(cmp.Or(why, "invalid classic protection response"))
	}
	protection := classic
	for _, key := range []string{"data", "repository", "ref"} {
		if protection = protection.Dict(key); protection == nil {
			return unclassic("invalid classic protection response")
		}
	}
	if protection = protection.Dict("branchProtectionRule"); protection != nil && protection.Truthy("requiresStatusChecks") {
		for _, item := range protection.List("requiredStatusChecks") {
			check, _ := item.(*run.Object)
			if check == nil {
				return unclassic("required check has no name")
			}
			app := ""
			if owner := check.Dict("app"); owner != nil {
				app = run.Text(owner.Get("databaseId"))
			}
			if err := need.add(check.Get("context"), app); err != nil {
				return unclassic(err.Error())
			}
		}
	}
	return need, "", nil
}

// requiredChecks waits for the target's required names on the commit sha, Python's checks,
// counting those that have not registered yet: whether they went green, and why not.  For a run in
// its landing line a red names what failed in full, for its fixer.
func requiredChecks(l *loop, pull *gh.Pull, target, sha string, line bool) (bool, string, error) {
	need, why, err := requiredOf(l, pull, target)
	if err != nil || why != "" {
		return false, why, err
	}
	if len(need) == 0 {
		l.say("checks: " + target + " requires no status checks")
		return true, "", nil
	}
	l.say(fmt.Sprintf("--- checks: %s requires %s", target, strings.Join(slices.Sorted(maps.Keys(need)), ", ")))
	if sha == "" {
		return false, "cannot verify required checks without the PR head SHA", nil
	}
	deadline := time.Now().Add(checksCap)
	rerun := map[string]int{} // a check GitHub cancelled ran nothing: asked again until GitHub takes it
	for {
		read, why, err := checkStates(l, pull, sha, need, rerun)
		if err != nil || why != "" {
			return false, why, err
		}
		var failed, missing, pending []string
		for name, buckets := range read.states {
			if slices.Contains(buckets, "fail") {
				failed = append(failed, name)
			}
			if len(buckets) == 0 {
				missing = append(missing, name)
			}
			if slices.ContainsFunc(buckets, func(bucket string) bool { return bucket != "pass" }) {
				pending = append(pending, name)
			}
		}
		slices.Sort(failed)
		slices.Sort(missing)
		slices.Sort(pending)
		if len(failed) > 0 {
			why := "required checks failed: " + strings.Join(failed, ", ")
			if line {
				why += "\n\n" + run.Encode(read.failed(failed))
			}
			return false, why, nil
		}
		if len(missing) == 0 && len(pending) == 0 {
			l.say("checks: required checks green")
			return true, "", nil
		}
		if !time.Now().Before(deadline) {
			var reasons []string
			if len(missing) > 0 {
				reasons = append(reasons, "required checks never registered: "+strings.Join(missing, ", "))
			}
			if len(pending) > 0 {
				reasons = append(reasons, "required checks did not finish: "+strings.Join(pending, ", "))
			}
			return false, strings.Join(reasons, "; "), nil
		}
		select {
		case <-l.ctx.Done():
			return false, "", l.ctx.Err()
		case <-time.After(min(checksPoll, time.Until(deadline))):
		}
	}
}

// A reading is one look at a commit's checks: each required name's as pass, fail or pending, and
// the latest check run of each name and app and status of each context they were read from.
type reading struct {
	states   map[string][]string
	latest   map[[2]string]*run.Object
	statuses map[string]*run.Object
}

// failed is the check runs and statuses of those names, as GitHub gave them.
func (r *reading) failed(names []string) *run.Object {
	runs, statuses := []any{}, []any{}
	for _, key := range slices.SortedFunc(maps.Keys(r.latest), func(a, b [2]string) int { return strings.Compare(a[0]+"\x00"+a[1], b[0]+"\x00"+b[1]) }) {
		if slices.Contains(names, key[0]) {
			runs = append(runs, r.latest[key])
		}
	}
	for _, name := range slices.Sorted(maps.Keys(r.statuses)) {
		if slices.Contains(names, name) {
			statuses = append(statuses, r.statuses[name])
		}
	}
	return run.Fields("check_runs", runs, "statuses", statuses)
}

// checkStates is each required name's check runs and statuses on the commit, as pass, fail or
// pending; none for a name not registered, or registered by another app than it requires.
func checkStates(l *loop, pull *gh.Pull, sha string, need wanted, rerun map[string]int) (*reading, string, error) {
	value, why, err := gh.JSON(l.dir, "api", "--paginate", pull.API()+"/commits/"+sha+"/check-runs?filter=latest&per_page=100")
	if err != nil {
		return nil, "", err
	}
	unread := func(why string) (*reading, string, error) {
		return nil, "cannot read required check runs: " + why, nil
	}
	pages, ok := value.([]any)
	if !ok {
		return unread(cmp.Or(why, "invalid check-runs response"))
	}
	latest := map[[2]string]*run.Object{}
	for _, each := range pages {
		page, _ := each.(*run.Object)
		if page == nil || !page.Has("check_runs") {
			return unread("invalid check-runs response")
		}
		for _, item := range page.List("check_runs") {
			check, _ := item.(*run.Object)
			if check == nil || check.Dict("app") == nil {
				return unread("invalid check-runs response")
			}
			key := [2]string{check.Str("name"), run.Text(check.Dict("app").Get("id"))}
			at, _ := check.Num("id")
			if held, seen := latest[key]; seen {
				if was, _ := held.Num("id"); at <= was {
					continue
				}
			}
			latest[key] = check
		}
	}
	states := map[string][]string{}
	missingApp := map[string]bool{}
	anyApp := false
	for _, name := range slices.Sorted(maps.Keys(need)) {
		apps := need[name]
		anyApp = anyApp || apps[""]
		states[name] = []string{}
		seen := map[string]bool{}
		for key, check := range latest {
			if key[0] != name || !apps[""] && !apps[key[1]] {
				continue
			}
			seen[key[1]] = true
			states[name] = append(states[name], checkBucket(check))
			if err := askAgain(l, pull, name, check, rerun); err != nil {
				return nil, "", err
			}
		}
		for app := range apps {
			if app != "" && !seen[app] {
				missingApp[name] = true
				states[name] = []string{} // a same-named check from another app cannot satisfy it
			}
		}
	}
	if !anyApp {
		return &reading{states, latest, nil}, "", nil
	}
	value, why, err = gh.JSON(l.dir, "api", "--paginate", pull.API()+"/commits/"+sha+"/statuses?per_page=100")
	if err != nil {
		return nil, "", err
	}
	statuses, why := latestStatuses(value, why)
	if why != "" {
		return nil, "cannot read required commit statuses: " + why, nil
	}
	for name, status := range statuses {
		if need[name][""] && !missingApp[name] {
			states[name] = append(states[name], statusBucket(status.Str("state")))
		}
	}
	return &reading{states, latest, statuses}, "", nil
}

// checkBucket is how a check run stands: a cancelled one ran nothing, so it is still owed.
func checkBucket(check *run.Object) string {
	conclusion := check.Str("conclusion")
	switch {
	case check.Str("status") != "completed", conclusion == "cancelled":
		return "pending"
	case conclusion == "success", conclusion == "neutral", conclusion == "skipped":
		return "pass"
	}
	return "fail"
}

func statusBucket(state string) string {
	switch state {
	case "success":
		return "pass"
	case "failure", "error":
		return "fail"
	}
	return "pending"
}

// latestStatuses is each context's newest commit status, and why it cannot say.
func latestStatuses(value any, why string) (map[string]*run.Object, string) {
	pages, ok := value.([]any)
	if !ok {
		return nil, cmp.Or(why, "invalid statuses response")
	}
	latest := map[string]*run.Object{}
	for _, each := range pages {
		page, ok := each.([]any)
		if !ok {
			return nil, "invalid statuses response"
		}
		for _, item := range page {
			status, _ := item.(*run.Object)
			if status == nil {
				return nil, "invalid statuses response"
			}
			at, _ := status.Num("id")
			if held := latest[status.Str("context")]; held != nil {
				if was, _ := held.Num("id"); at <= was {
					continue
				}
			}
			latest[status.Str("context")] = status
		}
	}
	return latest, ""
}

// askAgain asks GitHub to run a job it cancelled once more: it refuses while its workflow still
// runs, so that is asked again at the next poll.
func askAgain(l *loop, pull *gh.Pull, name string, check *run.Object, rerun map[string]int) error {
	id := run.Text(check.Get("id"))
	last, asked := rerun[id]
	if check.Str("conclusion") != "cancelled" || check.Dict("app").Str("slug") != "github-actions" || asked && last == 0 {
		return nil
	}
	code, said, err := gh.Call(l.dir, "api", "-X", "POST", pull.API()+"/actions/jobs/"+id+"/rerun")
	if err != nil {
		return err
	}
	if code == 0 {
		l.say("checks: GitHub cancelled " + name + "; asked it to run again")
	} else if !asked {
		l.say("checks: GitHub cancelled " + name + "; asked it to run again, refused for now: " + tail(said, 200))
	}
	rerun[id] = code
	return nil
}
