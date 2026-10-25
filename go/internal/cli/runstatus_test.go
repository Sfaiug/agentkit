package cli

import (
	"path/filepath"
	"testing"
)

// What Go cannot yet show as Python ak does, it refuses having printed and written nothing.
func TestRunStatusRefusals(t *testing.T) {
	ended := `{"run_id":"20261020-0900-fix-api","state":"pass","finished_at":1}`
	for name, setup := range map[string]struct {
		files map[string]string
		args  []string
	}{
		"queued":    {map[string]string{"runs/20261020-0900-fix-api/run.json": `{"state":"queued"}`}, nil},
		"loop gone": {map[string]string{"runs/20261020-0900-fix-api/run.json": `{"state":"running"}`}, nil},
		"hidden": {map[string]string{"runs/20261020-0900-fix-api/run.json": ended,
			"runs/20261020-0900-add-beta/run.json": `{"state":"interrupted","finished_at":1}`}, nil},
		"says unreadable": {map[string]string{"runs/20261020-0900-fix-api/run.json": `{"state":"unreadable"}`}, nil},
		"by id":           {map[string]string{"runs/20261020-0900-fix-api/run.json": ended}, []string{"20261020-0900-fix-api"}},
		"sweep owed":      {map[string]string{"runs/20261020-0900-fix-api/run.json": `{"state":"fail","scope":"ak-fix-api.scope"}`}, nil},
		"lone surrogate": {map[string]string{"runs/20261020-0900-fix-api/run.json": ended,
			"runs/20261020-0900-add-beta/run.json": `{"state":"pass","title":"beta \ud800"}`}, []string{"--json"}},
		"job":     {map[string]string{"jobs/batch/job.json": `{"tasks":[]}`}, nil},
		"history": {map[string]string{"runs/20261020-0900-fix-api/run.json": ended, "history.db": ""}, []string{"--json"}},
		"seat": {map[string]string{"runs/20261020-0900-fix-api/run.json": ended,
			"state/session-acme.json": `{"name":"acme"}`}, []string{"--history"}},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			for path, content := range setup.files {
				write(t, filepath.Join(home, ".agentkit", path), content)
			}
			assertCall(t, append([]string{"run", "status"}, setup.args...), 3, "", "ak run status: not implemented in Go yet\n")
		})
	}
}

// An ended run whose loop started nothing to sweep is listed with the sweep stamped, as
// Python's reap leaves it, though only in memory.
func TestRunStatusStampsASweepWithNothingToEnd(t *testing.T) {
	home := sandbox(t)
	dir := filepath.Join(home, ".agentkit", "runs", "20261020-0900-fix-api")
	write(t, filepath.Join(dir, "run.json"), `{"run_id":"20261020-0900-fix-api","state":"pass","finished_at":1e10}`)
	assertCall(t, []string{"run", "status", "--json"}, 0, `[
  {
    "run_id": "20261020-0900-fix-api",
    "state": "pass",
    "finished_at": 10000000000.0,
    "tree_stopped": [
      null,
      null
    ],
    "paths": {
      "result": "`+dir+`/result.md",
      "record": "`+dir+`/run.json",
      "logs": "`+dir+`",
      "workspace": null,
      "workspace_present": false
    }
  }
]
`, "")
}
