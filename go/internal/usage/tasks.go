package usage

import (
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/quality"
	"agentkit/internal/run"
)

// workerRoles are the roles a run's turns pair their tokens under.
var workerRoles = []string{"executor", "reviewer"}

// TaskUsage is, per model and effort of rates (Rates), the mean weekly percentage points a run
// took in each worker role, nil where no run qualifies, Python's usage.task_usage.  A run's share
// in a role is every token its turns in that role paired, at the rate of the one model and effort
// they all ran at: a run handed between models or efforts counts for neither.  A run counts only
// with a pair for each of its launches in that role and a launch for each pair, as a missed
// reading, or diagnostics gone, must not make a task look cheaper.
func TaskUsage(rates *run.Object) *run.Object {
	type task struct{ id, role string }
	type paired struct {
		provider, account string
		pair              *run.Object
	}
	var tasks []task
	pairs := map[task][]paired{}
	measured := measuredPairs()
	for _, provider := range measured.Keys() {
		logins := object(measured.Get(provider))
		for _, account := range logins.Keys() {
			for _, listed := range values(object(logins.Get(account))) {
				for _, pair := range wellFormed(listed) {
					id, _ := pair.Get("run_id").(string)
					role, _ := pair.Get("role").(string)
					if each := (task{id, role}); id != "" && slices.Contains(workerRoles, role) {
						if pairs[each] == nil {
							tasks = append(tasks, each)
						}
						pairs[each] = append(pairs[each], paired{provider, account, pair})
					}
				}
			}
		}
	}
	shares := map[[3]string][]float64{}
	for _, each := range tasks {
		model, named := pairs[each][0].pair.Get("model").(string)
		effort, said := pairs[each][0].pair.Get("effort").(string)
		rate, rated := number(object(rates.Get(model)).Get(effort))
		if !named || !said || !rated || slices.ContainsFunc(pairs[each], func(p paired) bool {
			return p.pair.Get("model") != model || p.pair.Get("effort") != effort
		}) {
			continue
		}
		// One turn can pair several gating meters at the same timestamp.
		type turn struct {
			provider, account string
			at                float64
		}
		var turns []turn
		tokens := map[turn]float64{}
		for _, p := range pairs[each] {
			at := turn{p.provider, p.account, field(p.pair, "at")}
			if _, seen := tokens[at]; !seen {
				turns = append(turns, at)
			}
			tokens[at] = field(p.pair, "tokens")
		}
		receipts, _ := fs.Glob(os.DirFS(filepath.Join(run.Runs(), each.id)), "round-*/*/harness")
		launches := 0
		for _, receipt := range receipts {
			if strings.HasPrefix(path.Base(path.Dir(receipt)), "reviewer") == (each.role == "reviewer") {
				launches++
			}
		}
		spent := make([]float64, len(turns))
		for i, at := range turns {
			spent[i] = tokens[at]
		}
		if launches != len(turns) || launches == 0 || slices.ContainsFunc(spent, func(t float64) bool { return t <= 0 }) {
			continue
		}
		key := [3]string{model, effort, each.role}
		shares[key] = append(shares[key], quality.Sum(spent)*rate/1e6)
	}
	found := run.NewObject()
	for _, model := range rates.Keys() {
		efforts := run.NewObject()
		for _, effort := range object(rates.Get(model)).Keys() {
			roles := run.NewObject()
			for _, role := range workerRoles {
				roles.Set(role, nil)
				if taken := shares[[3]string{model, effort, role}]; len(taken) > 0 {
					roles.Set(role, quality.Sum(taken)/float64(len(taken)))
				}
			}
			efforts.Set(effort, roles)
		}
		found.Set(model, efforts)
	}
	return found
}
