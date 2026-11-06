package seat

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/adapters"
	"agentkit/internal/config"
	"agentkit/internal/hookfact"
	"agentkit/internal/host"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
	usages "agentkit/internal/usage"
)

var errAccountChanged = errors.New("seat changed before account move")

const heldContinue = "Your process was ended, not by you, while it held background work: %s. Resume what can be resumed and start the rest again."

// TickHome leaves live recovery to its tick row; ordinary views still require a word they
// can publish immediately.
func TickHome(now time.Time) (Home, bool) { return reading(now, true, lookRuns, nil, true) }

func accountName(record *run.Object, key string) string {
	if account := record.Str(key); account != "" {
		return account
	}
	return "default"
}

func listedAccount(model config.Model, account string) bool {
	if account == "" || account == "default" {
		return true
	}
	accounts, err := config.Accounts(model.Provider)
	return err == nil && slices.Contains(accounts, account)
}

// AccountIdle is the account case that needs no recovery or account selection.
func AccountIdle(live Live) bool {
	if live.File.Truthy("usage_wait") || live.File.Truthy("usage_refusal") || live.File.Truthy("midturn") {
		return false
	}
	models, err := config.Models()
	if err != nil {
		return false
	}
	model := live.Record.Str("orchestrator")
	accounts, err := config.Accounts(models[model].Provider)
	readings, unread := usages.Cached()
	return err == nil && len(accounts) == 0 && accountName(live.Record, "account") == accountName(live.Record, "home_account") &&
		unread == nil && readings.Spent(model) == "" && !live.WrappedUp
}

// MoveAccount is seat_account's two prompt-time moves. Refusals, pending recovery, owner input
// and turns in flight are left at this point, before a relaunch writes anything; a move waits for
// the input field to read empty (fieldWaits).
func MoveAccount(live Live, log func(string)) (carried bool, err error) {
	file := live.File
	if file.Truthy("usage_wait") || file.Truthy("usage_refusal") || file.Truthy("midturn") {
		return false, nil
	}
	if AccountIdle(live) {
		return true, nil
	}
	// a draft is read under the lock, where the move waits for it
	if live.Stall != nil || live.Login != nil ||
		live.State != "at_prompt" && live.State != "draft" || live.WrappedUp || notify.UnansweredQuestion(live.Name) {
		return false, nil
	}
	at := seatAt{live.Name, live.Own, harnessPane(live.Name)}
	found := at.sight(at.capture())
	if flight, _ := found.turnInFlight(live.Own); flight || !at.free(found) && found.state != "draft" {
		return false, nil
	}
	current, home := accountName(live.Record, "account"), accountName(live.Record, "home_account")
	accounts, err := usages.SeatAccounts(live.Record.Str("orchestrator"), home)
	if err != nil {
		return false, nil
	}
	var own *usages.Account
	for i := range accounts {
		if accounts[i].Name == current {
			own = &accounts[i]
		}
	}
	if own == nil {
		return false, nil
	}
	spent := own.Spent != ""
	work := hookfact.Standing(live.Name).Holds
	if !spent && len(work) > 0 {
		return true, nil
	}
	var moves []string
	// The first branch is Python's between-turns choice; the spent branch prefers windows
	// over credits. Stable sorting has already put the home first while it has room.
	for _, a := range accounts {
		if a.Name != current && a.Spent == "" && (spent || !a.Credits &&
			(own.Credits || !a.Low && (a.Name == home || own.Low))) {
			moves = append(moves, a.Name)
		}
	}
	if len(moves) == 0 {
		return !spent, nil
	}
	_, record, err := config.ResolveSession(live.Name)
	if err != nil {
		return false, nil
	}
	back, ready := comingBack(filepath.Join(config.Home(), "state"), live.Name, record, true, true)
	if !ready || !back.launchable(record) || back.conversation == "" || file.Truthy("owed_lines") {
		return false, nil
	}
	back.account = ""
	for _, target := range moves {
		if adapters.SeatAuth(live.Own, target) {
			back.account = target
			break
		}
	}
	if back.account == "" {
		return false, nil
	}
	err = under(filepath.Join(config.Home(), "state", "watch.lock"), func() error {
		if err := live.accountStill(live.Name, !spent); err != nil {
			return err
		}
		work := hookfact.Standing(live.Name).Holds
		back.still = func(name string) error {
			if !slices.Equal(hookfact.Standing(name).Holds, work) {
				return errAccountChanged
			}
			return live.accountStill(name, !spent)
		}
		if spent && len(work) > 0 {
			launch, _ := config.Section(live.Own, "launch")
			if !back.opened || launch["first_prompt"] != true {
				return errAccountChanged
			}
			back.line = fmt.Sprintf(heldContinue, strings.Join(work, ", "))
		}
		when := seconds(time.Now())
		name, carried, err := back.relaunch(false, io.Discard)
		if !carried {
			return errAccountChanged
		}
		if err != nil {
			return err
		}
		log(back.said())
		if back.line != "" {
			return Write(name, "midturn", run.Fields("boot", host.BootID(), "at", when, "name", name,
				"line", back.line, "launched", true, "account", true))
		}
		return nil
	})
	if errors.Is(err, errFieldHeld) {
		return at.fieldWaits(spent), nil
	}
	if errors.Is(err, errAccountChanged) {
		return false, nil
	}
	return true, err
}

// accountStill is the last look under the launch's typing lock: errFieldHeld where the input
// field is not read whole and empty, errAccountChanged where anything else moved. A between-turns
// move also requires a terminal untouched for DRAFT_STILL and no newly held background work.
func (live Live) accountStill(name string, between bool) error {
	file := revivalFile(name)
	if name != live.Name || !live.sameRecord() ||
		!run.Equal(file.Get("opened_at"), live.File.Get("opened_at")) || file.Truthy("stopped_at") ||
		file.Truthy("closed_by_owner") || file.Truthy("midturn") || file.Truthy("usage_wait") ||
		file.Truthy("usage_refusal") || notify.UnansweredQuestion(name) || !Watching(name) {
		return errAccountChanged
	}
	at := seatAt{name, live.Own, harnessPane(name)}
	pane := at.capture()
	found := at.sight(pane)
	if !fieldEmpty(live.Own, pane) {
		return errFieldHeld
	}
	if !at.free(found) || found.stall != nil || found.login != nil || at.unread() {
		return errAccountChanged
	}
	if !between {
		return nil
	}
	tty, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", at.pane, "#{pane_tty}")
	info, statErr := os.Stat(tty)
	if err != nil || statErr != nil || !terminalQuiet(info) || len(hookfact.Standing(name).Holds) > 0 {
		return errAccountChanged
	}
	return nil
}

func (live Live) sameRecord() bool {
	record, err := run.ReadJSON(ownFile("session", live.Name))
	return err == nil && record != nil && run.Equal(record, live.Record)
}

// Live recovery marks belong to their own tick passes, not the listing's closed-seat check.
func liveStopped(file *run.Object) (bool, bool) {
	if file != nil && !file.Truthy("stopped_at") && !file.Truthy("closed_by_owner") {
		file = file.Copy()
		for _, key := range waits {
			file.Delete(key)
		}
	}
	return revivalStopped(file)
}

func liveClimbs(state string, seat Seat, found sight, now float64) bool {
	facts := accountClimbing(climbingOf(state, seat, found, now))
	_, err := facts.climb()
	return err == nil
}

func accountClimbing(facts climbing) climbing {
	facts.file = facts.file.Copy()
	facts.file.Delete("usage_wait")
	facts.file.Delete("usage_refusal")
	return facts
}
