package seat

import (
	"context"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// inPlace is orch.switch_in_place: under the seat's send and announce locks, so no look follows
// the old model's last answer back meanwhile, the record takes the move, its orchestrator and
// effort, and the harness in the launch's pane is owed the lines its prompt takes for it
// (switchLines); a record or lines that cannot be written put the record back.  The lines then go
// in at its quiet prompt, now or at a tick's, and its bar names the new model.  Nothing restarts,
// so nothing is cut or asked.
func (plan *plannedMove) inPlace() error {
	state := filepath.Join(config.Home(), "state")
	err := notify.Held(context.Background(), plan.name, func(current string) error {
		return plan.back.moving.launch(state, current, func() error {
			pane, err := switchPane(current, plan.was, plan.back.model)
			if err != nil {
				return err
			}
			if pane != plan.pane || usageGoesOn(current) {
				return Refusal("the seat's harness changed before it could move")
			}
			lines, err := switchLines(pane, plan.was, plan.back.model)
			if err == nil {
				err = oweLines(current, lines...)
			}
			if err == nil {
				err = writeSeat(state, current, []field{{"usage_wait", nil}})
			}
			return err
		})
	})
	if err != nil {
		return err
	}
	if _, err := TellOwed(plan.name, func(string) {}); err != nil {
		return err
	}
	Redress(plan.name)
	return nil
}

// switchLines is what the prompt in that pane takes to run `next` at its orchestrator effort
// (orch.switch_lines), each owed to that pane as a move's (`switch`): `[switch]`'s `model` then
// `effort`, an effort of `none` typing none, and a step of effort on the model it runs only
// `effort`.
func switchLines(pane string, was, next config.Model) ([]*run.Object, error) {
	block, err := config.Section(next.Harness, "switch")
	if err != nil {
		return nil, err
	}
	at := next.Efforts["effort"]
	var keys []string
	for _, key := range []string{"model", "effort"} {
		if block[key] != nil && (key != "effort" || at != "none") {
			keys = append(keys, key)
		}
	}
	if len(keys) == 2 && was.ID == next.ID {
		keys = keys[1:] // a harness may save each `/model` as its default for new sessions
	}
	given := strings.NewReplacer("{model}", next.ID, "{effort}", at)
	var lines []*run.Object
	for _, key := range keys {
		line, _ := block[key].(string)
		lines = append(lines, run.Fields("line", given.Replace(line), "switch", true, "pane", pane))
	}
	return lines, nil
}

// usageGoesOn is whether the seat's turn its usage cut off is to go on once it moves
// (`usage_wait`'s `continue`): a restart opens on that, and a move in place, which Python tells
// it after its lines, is Python's.
func usageGoesOn(name string) bool {
	wait := revivalFile(name).Dict("usage_wait")
	return wait != nil && wait.Truthy("continue")
}
