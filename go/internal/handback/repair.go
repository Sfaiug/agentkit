package handback

import (
	"cmp"
	"context"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// StartRepair starts the repair run of the target that the member state is in dir owns, Python's
// start_followups with a `repair`: one for the target failing a `command` of its own on its tip, or,
// `flaky` naming when the landing line first saw it, a test file the line saw tests of fail, then
// pass, on two trees.  repair holds that command or file, keying the repair with the target and
// `flaky`, the done-when `check`, the target's tip (`sha`) and `text`, naming the tip and what failed
// there.  It is launched ahead of the queue under the lock that closes seats, as prepare readies a
// seat's follow-up.  Its answer is the repair: started, already open for that key at that tip, or
// left queued by a start that failed; "" where none is.
func StartRepair(state *run.Object, dir string, repair *run.Object, prepare func(string, *run.Object, *run.Object) (func() error, error), say func(string)) (string, error) {
	if run.Seat(state) == "" || !state.Truthy("repo") || state.Truthy("scratch") || state.Truthy("review_pr") && !state.Truthy("own_pr") {
		return "", nil
	}
	held, err := lock.Wait(context.Background(), filepath.Join(config.Home(), "state", "watch.lock"))
	if err != nil {
		return "", err
	}
	defer held.Close()
	_, lists, err := seatLists(state)
	if err != nil || lists == nil || !fixers(lists) {
		return "", err
	}
	state = state.Copy()
	state.Set("repo", mainCheckout(state.Str("repo")))
	target := strings.TrimPrefix(cmp.Or(state.Str("target"), state.Str("base")), "origin/")
	command, tip := repair.Str("command"), repair.Str("sha")
	key := run.Fields("target", target, "command", command)
	title, body := "Make "+target+" pass `"+command+"` again", repair.Str("text")+"\n\n"+task.FixTheCommand
	if repair.Has("flaky") {
		key.Set("flaky", repair.Get("flaky"))
		title, body = "Make "+command+" deterministic", repair.Str("text")
	}
	for _, other := range run.Dirs() {
		record, _ := run.Read(other)
		if record != nil && record.Str("run_id") != state.Str("run_id") && record.Truthy("followup") &&
			record.Str("repo") == state.Str("repo") && run.Equal(record.Get("repair"), key) && RepairOpen(record, tip) {
			return filepath.Base(other), nil
		}
	}
	text := repair.Str("text")
	child, err := followupTask(state, title, body, repair.Str("check"))
	if err != nil {
		return "", err
	}
	// its only check is the target's own, run at landing: its before is the lander's run there
	start, err := prepare(child, state, run.Fields("followup", run.Fields("run", filepath.Base(dir), "text", text, "place", followupPlace(text)),
		"repair", key, "repair_tip", tip, "base_proof", "at landing", "repo", state.Str("repo"), "first", true))
	if err == nil {
		err = start()
	}
	if err != nil {
		say("follow-up " + filepath.Base(child) + " could not start: " + err.Error())
		// a start that failed can leave its receipt queued for a slot, which the tick starts
		if record, _ := run.Read(child); record == nil || !RepairOpen(record, tip) {
			return "", nil
		}
	}
	return filepath.Base(child), nil
}

// RepairOpen is whether that repair run holds its command on the target at tip, Python's
// repair_open: on its way, on any tip, or ended there without delivering, which another run of
// it would only repeat.
func RepairOpen(record *run.Object, tip string) bool {
	delivered := record.Truthy("merged") || record.Str("state") == "not_needed"
	return onItsWay(record) || run.Ended(record) && !delivered && record.Str("repair_tip") == tip
}
