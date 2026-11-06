package seat

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/host"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/screen"
	meters "agentkit/internal/usage"
	"agentkit/internal/worker"
)

const movedLine = "This seat moved to you in the middle of a turn. Continue that turn from where the conversation your instructions point you to leaves it; do not start over."

type seatMove struct {
	was, own string
	chosen   []field
	line     string
	at       float64
}

// Move takes only a fresh-conversation restart. Refusals of _switch_plan,
// in-place switches, kept conversations, drafts and dialogs return before asked.
// The launch, including its rollback, remains the one reopening uses.
func Move(name, model string, asked func() (bool, bool)) (bool, error) {
	name, record, err := config.ResolveSession(name)
	selected, unread := ConfigSelection(name)
	models, unconfigured := config.Models()
	entry, named := models[model]
	if err != nil || unread != nil || selected == nil || unconfigured != nil || !named {
		return false, nil
	}
	old := selected.Str("orchestrator")
	if old == model {
		return true, nil
	}
	// _switch_plan: installed, login, then the screen's spent meter. Named
	// subscriptions still need Python's account ordering and seat_auth hooks.
	adapter, err := config.Adapter(entry.Harness)
	if err == config.ErrNoAdapterDir {
		adapter, err = config.ShippedAdapter(entry.Harness)
	}
	program := entry.Harness
	if version, _ := config.Words(entry.Harness, "update", "version"); len(version) > 0 && version[0] != "" {
		program = version[0]
	}
	if err != nil || harness.Binary(program) == "" {
		return false, nil
	}
	accounts, err := config.Accounts(entry.Provider)
	account, _ := record["account"].(string)
	if err != nil || len(accounts) != 0 || account != "" && account != "default" {
		return false, nil
	}
	subscriptions, err := config.Subscriptions()
	if err != nil {
		return false, nil
	}
	var providers []string
	for _, subscription := range subscriptions {
		if subscription.Harness == entry.Harness {
			providers = append(providers, subscription.Name)
		}
	}
	env := append(host.Unmarked(os.Environ()), "AGENTKIT_ACCOUNT=", "AGENTKIT_PROVIDER="+strings.Join(providers, " "))
	if answered, yes, _ := worker.Login(adapter, env, "seat"); answered && !yes {
		return false, nil
	}
	readings, err := meters.Cached()
	if err != nil || readings.SeatSpent(model) {
		return false, nil
	}
	was := models[old]
	if !moveRestarts(name, was, entry, record) {
		return false, nil
	}
	if !harness.CanHandOver(was.Harness) || !harness.CanLaunch(entry.Harness) {
		return false, nil
	}
	held, _, known := find(name, record)
	cwd, _ := record["cwd"].(string)
	info, err := os.Stat(cwd)
	entry, efforts := atOwnEfforts(entry, model, record)
	if !known || !efforts || err != nil || !info.IsDir() {
		return false, nil
	}
	back := reopening{name: name, orchestrator: model, cwd: cwd, model: entry, opened: true, held: held}
	moving := &seatMove{was: old, own: was.Harness, chosen: []field{{"orchestrator", model}, {"account", record["account"]}}}
	if was.Provider != entry.Provider {
		moving.chosen = []field{{"orchestrator", model}, {"account", nil}, {"home_account", nil}}
	}
	back.moving = moving
	if _, known := moving.sight(name, held); !known {
		return false, nil
	}
	accepted, known := asked()
	if !known || !accepted {
		return known, nil
	}
	found, known := moving.sight(name, held)
	if !known {
		return true, Refusal("the seat's screen changed; keep its input before moving it")
	}
	moving.at = seconds(time.Now())
	file := revivalFile(name)
	going, _ := found.turnInFlight(was.Harness)
	if going || file.Dict("usage_wait") != nil && file.Dict("usage_wait").Truthy("continue") {
		moving.line = movedLine
	}
	text, known := harness.Handover(was.Harness, record)
	if !known {
		return true, Refusal("the seat's conversation changed before it could move")
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
	read := seen.rules.Read(screen.Tail(pane))
	draft, _ := seen.rules.ComposerDraft(pane)
	found, _ := observed(filepath.Join(config.Home(), "state"), name, harness.For(moving.own), pane, seconds(time.Now()))
	return found, read.State != "asking" && read.State != "draft" && found.state != "asking" && draft == ""
}

// launch holds the same announce lock as switch_orchestrator, publishing the new
// orchestrator before the harness starts and restoring only its fields on failure.
func (moving *seatMove) launch(state, name string, launch func() error) error {
	return announcing(state, name, func() error {
		var before *run.Object
		err := update(state, name, func(data *run.Object) bool {
			if data.Str("orchestrator") != moving.was {
				return false
			}
			before = data.Copy()
			fill(data, moving.chosen)
			return true
		})
		if err != nil {
			return err
		}
		if before == nil {
			return Refusal("the seat's orchestrator changed before it could move")
		}
		if err = launch(); err != nil {
			update(state, name, func(data *run.Object) bool {
				for _, chosen := range moving.chosen {
					fill(data, []field{{chosen.key, before.Get(chosen.key)}})
				}
				return true
			})
		}
		return err
	})
}

func (moving *seatMove) relaunched(name, own string) error {
	if moving.line == "" {
		return nil
	}
	mark := run.Fields("boot", host.BootID(), "at", run.Float(moving.at), "name", name, "line", moving.line)
	launch, err := config.Section(own, "launch")
	if err != nil {
		return err
	}
	if launch["first_prompt"] == true {
		mark.Set("launched", true)
	}
	return writeSeat(filepath.Join(config.Home(), "state"), name, []field{{"midturn", mark}})
}
