package worker

import (
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/helper"
	"agentkit/internal/machines"
)

// elsewhere is the turn argv sent to a machine that takes turns, as Python's machine_turn.call
// first offers it one; nil where it runs here, as helper.Placed declines it, or as the checkout
// holds a stopped rebase, merge or cherry-pick: git keeps one in the checkout's own git directory,
// which no parcel carries, so a machine's clone has none to go on.  A directory git cannot answer
// for goes as any other.
func elsewhere(model config.Model, argv []string, workspace, out string, env map[string]string, session string) *helper.Turn {
	if !machines.TakesTurns() {
		return nil
	}
	if stopped, _ := gitcall.InProgress(gitcall.Git{Repo: workspace}); stopped {
		return nil
	}
	return placed(model, argv, workspace, out, env, session)
}

// placed is helper.Placed, which a test stands in for.
var placed = helper.Placed
