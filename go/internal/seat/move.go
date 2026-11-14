package seat

import (
	"fmt"
	"io"
	"maps"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/host"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	meters "agentkit/internal/usage"
)

// screenChanged refuses a move over a draft or a question that came up on the seat's screen
// after it was asked, which a restart would discard.
const screenChanged = Refusal("the seat's screen changed; keep its input before moving it")

const movedLine = "This seat moved to you in the middle of a turn. Continue that turn from where the conversation your instructions point you to leaves it; do not start over."

// A seatMove is what a move writes in the seat's record: from the orchestrator it held (`was`,
// run by `own`), the fields it takes (`chosen`), with the `left` it makes where it leaves a
// conversation (`leaving`), and its orchestrator's effort where one is given (`effort` on `model`,
// its entry among `models`); when a restart began.
type seatMove struct {
	was, own, model, effort string
	models                  map[string]config.Model
	chosen                  []field
	leaving                 bool
	at                      float64
}

// A plannedMove is a seat's move every refusal Go carries has passed (planMove): in place on its
// launch's own pane where its running harness takes it (switchPane), else a restart on `back`,
// on the conversation it keeps (keptConversation) where it has one.
type plannedMove struct {
	name, pane string
	was        config.Model
	back       reopening
	record     map[string]any
	selected   *run.Object
}

// ModelOff is matrix.Off, which matrix supplies: it reads the harness catalogs through packages
// that import this one.
var ModelOff func(name string) (bool, error)

// Move moves the seat to `model`, its orchestrator at `effort`, else at the seat's own, as
// orch.switch_orchestrator does: in place, asking nothing, where its running harness takes the
// move (switchPane), else by a restart once `asked(kept)` says so, `kept` whether its
// conversation goes on.  Given `effort`, its own model moves as another would.  Refusals of
// _switch_plan, a move in place into a harness Go types nothing into or after which a turn its
// usage cut off goes on, drafts and dialogs return before asked.  The launch, including its
// rollback, remains the one reopening uses.
func Move(name, model, effort string, asked func(kept bool) (bool, bool)) (bool, error) {
	plan, known := planMove(name, model, effort)
	if !known || plan == nil {
		return known, nil
	}
	return plan.carry(asked)
}

// planMove is Move's every check before anything is written: nil where the seat already runs
// `model` and no effort is given, false where Go does not carry the move.
func planMove(name, model, effort string) (*plannedMove, bool) {
	name, record, err := config.ResolveSession(name)
	selected, unread := ConfigSelection(name)
	models, unconfigured := config.Models()
	entry, named := models[model]
	if err != nil || unread != nil || selected == nil || unconfigured != nil || !named {
		return nil, false
	}
	old := selected.Str("orchestrator")
	if old == model && effort == "" {
		return nil, true
	}
	// _switch_plan refuses a model the model list turned off first; its refusal is Python's
	if off, err := ModelOff(model); err != nil || off {
		return nil, false
	}
	// _switch_plan: installed, login, then the screen's spent meter
	adapter, err := config.Adapter(entry.Harness)
	if err == config.ErrNoAdapterDir {
		adapter, err = config.ShippedAdapter(entry.Harness)
	}
	program := entry.Harness
	if version, _ := config.Words(entry.Harness, "update", "version"); len(version) > 0 && version[0] != "" {
		program = version[0]
	}
	if err != nil || harness.Binary(program) == "" {
		return nil, false
	}
	readings, err := meters.Cached()
	if err != nil {
		return nil, false
	}
	was := models[old]
	kept, _ := record["account"].(string)
	account, known := moveLogin(model, was, entry, kept, adapter, readings)
	if !known || readings.SeatSpent(model) {
		return nil, false
	}
	// Within its provider the account stays as the record holds it under the lock, so a recovery
	// made since this read is not undone; a restart's launch writes the one it runs on.
	moving := &seatMove{was: old, own: was.Harness, model: model, effort: effort, models: models,
		chosen: []field{{"orchestrator", model}}}
	if was.Provider != entry.Provider { // the account it moved onto is its home
		homed := any(nil)
		if account != "" {
			homed = account
		}
		moving.chosen = append(moving.chosen, field{"account", homed}, field{"home_account", homed})
	}
	entry, efforts := atOwnEfforts(entry, model, record)
	if effort != "" {
		at := map[string]string{}
		maps.Copy(at, entry.Efforts)
		at["effort"] = effort
		entry.Efforts = at
	}
	pane, err := switchPane(name, was, entry)
	if err != nil || !efforts || pane != "" && (!typable(entry.Harness) || usageGoesOn(name)) {
		return nil, false
	}
	plan := &plannedMove{name: name, pane: pane, was: was, record: record, selected: selected,
		back: reopening{name: name, orchestrator: model, model: entry, opened: true, account: account, moving: moving}}
	if pane != "" {
		return plan, true
	}
	conversation, opened, known := keptConversation(was, entry, record)
	if !known || conversation == "" && !harness.CanHandOver(was.Harness) || !harness.CanLaunch(entry.Harness) ||
		!moving.leaves(record, selected, conversation) {
		return nil, false
	}
	plan.back.conversation, plan.back.opened = conversation, opened
	held, _, known := find(name, record)
	cwd, _ := record["cwd"].(string)
	info, err := os.Stat(cwd)
	if !known || err != nil || !info.IsDir() {
		return nil, false
	}
	plan.back.cwd, plan.back.held = cwd, held
	if _, known := moving.sight(name, held); !known {
		return nil, false
	}
	return plan, true
}

// carry makes the planned move: in place at once, else the restart once `asked` says so.  A
// restart on the conversation it keeps hands nothing over and forgets nothing of it; one its
// harness never opened has no turn to go on with (orch.resume_command).
func (plan *plannedMove) carry(asked func(bool) (bool, bool)) (bool, error) {
	if plan.pane != "" {
		return true, plan.inPlace()
	}
	kept := plan.back.conversation != ""
	accepted, known := asked(kept)
	if !known || !accepted {
		return known, nil
	}
	name, held, back, moving := plan.name, plan.back.held, plan.back, plan.back.moving
	record, selected, model, was := plan.record, plan.selected, moving.model, plan.was
	found, known := moving.sight(name, held)
	if !known {
		return true, screenChanged
	}
	if held {
		// and once more with its keys off, under the seat's lock, after the adapter took its time
		back.still = func(current string) error {
			if _, known := moving.sight(current, true); !known {
				return screenChanged
			}
			return nil
		}
	}
	moving.at = seconds(time.Now())
	going, _ := found.turnInFlight(was.Harness)
	if going || usageGoesOn(name) {
		switch {
		case !kept:
			back.line = movedLine
		case back.opened:
			back.line = MidturnContinue
		}
	}
	text := ""
	if !kept {
		if text, known = harness.Handover(was.Harness, record); !known {
			return true, conversationChanged
		}
	}
	handed := ownFile("handover", name)
	before, err := os.ReadFile(handed)
	if err != nil && !os.IsNotExist(err) {
		return true, err
	}
	if text != "" {
		if err := replace(handed, append(append([]byte(nil), before...), text...)); err != nil {
			return true, err
		}
	}
	_, launched, err := back.relaunch(false, io.Discard)
	if err != nil || !launched {
		if before == nil {
			os.Remove(handed)
		} else {
			replace(handed, before)
		}
		if err == nil {
			err = Refusal(fmt.Sprintf("could not reopen %s on %s", name, model))
		}
		return true, err
	}
	if kept {
		return true, nil
	}
	if err = harness.Retire(was.Harness, selected); err == nil {
		err = forgetSeen(filepath.Dir(handed), name, time.Now())
	}
	if err == nil {
		err = notify.Clear(name)
	}
	return true, err
}

func (moving *seatMove) sight(name string, held bool) (sight, bool) {
	if !held {
		return sight{}, true
	}
	pane, exited := harnessScreen(name)
	if exited || strings.TrimFunc(pane, config.Space) == "" {
		return sight{}, true
	}
	seen := eyeOf(moving.own)
	if seen.bad != nil {
		return sight{}, false
	}
	read := seen.rules.Read(pane)
	draft, _ := seen.rules.ComposerDraft(pane)
	found, _ := observed(filepath.Join(config.Home(), "state"), name, harness.For(moving.own), pane, seconds(time.Now()))
	return found, read.State != "asking" && read.State != "draft" && found.state != "asking" && draft == ""
}

// launch holds the same announce lock as switch_orchestrator, publishing the new
// orchestrator, and its effort, before the harness starts and restoring only those on failure.
func (moving *seatMove) launch(state, name string, launch func() error) error {
	return announcing(state, name, func() error {
		var before *run.Object
		var chosen []field
		refused := Refusal("the seat's orchestrator changed before it could move")
		err := update(state, name, func(data *run.Object) bool {
			if data.Str("orchestrator") != moving.was {
				return false
			}
			made := false
			if chosen, made = moving.fields(data); !made {
				refused = conversationChanged
				return false
			}
			before = data.Copy()
			if moving.effort != "" {
				data.Set("efforts", orchestratingAt(data, moving.model, moving.effort, moving.models))
			}
			fill(data, chosen)
			return true
		})
		if err != nil {
			return err
		}
		if before == nil {
			return refused
		}
		if err = launch(); err != nil {
			update(state, name, func(data *run.Object) bool {
				for _, each := range chosen {
					fill(data, []field{{each.key, before.Get(each.key)}})
				}
				moving.effortBack(data, before)
				return true
			})
		}
		return err
	})
}

func (moving *seatMove) relaunched(name, own, line string) error {
	if line == "" {
		return nil
	}
	mark := run.Fields("boot", host.BootID(), "at", run.Float(moving.at), "name", name, "line", line)
	launch, err := config.Section(own, "launch")
	if err != nil {
		return err
	}
	if launch["first_prompt"] == true {
		mark.Set("launched", true)
	}
	return writeSeat(filepath.Join(config.Home(), "state"), name, []field{{"midturn", mark}})
}
