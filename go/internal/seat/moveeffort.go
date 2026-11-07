package seat

import "agentkit/internal/run"

// effortBack is orch.effort_back: the moved model's orchestrator effort in the record `data` back
// at what `before` ran it at, its entry's where `before` held none, the move at its effort having
// failed, where `data` still holds that effort there: a move made since keeps its own.
func (moving *seatMove) effortBack(data, before *run.Object) {
	efforts := data.Dict("efforts")
	if moving.effort == "" || efforts == nil {
		return
	}
	own := efforts.Dict(moving.model)
	if own == nil || own.Str("effort") != moving.effort {
		return
	}
	was := moving.models[moving.model].Efforts["effort"]
	if held := before.Dict("efforts"); held != nil && held.Dict(moving.model) != nil {
		was = held.Dict(moving.model).Str("effort")
	}
	own.Set("effort", was)
}
