package cli

import (
	"cmp"
	"context"
	"crypto/rand"
	"encoding/hex"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	modelListing "agentkit/internal/listing"
	"agentkit/internal/logins"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// addTitle is the name every screen of `+ add a subscription` is drawn under.
const addTitle = "config · add a subscription"

// menuAddSubscription is `+ add a subscription` on Subscriptions (menu.config_add_provider): one of
// menu.Addables picked from a list, so nothing is typed.  Each subscription is signed in afresh
// under an account name of its own, so no login already on disk is ever taken for it, the owner's
// word of 26 Oct 2026; one whose sign-in does not finish adds nothing and leaves nothing of it.  A
// host opens its own list (menuAddThrough), Esc there coming back here, that host highlighted; a
// provider the config lacks goes in as the shipped default has it, listing that account alone, with
// the first model its new login lists (AddProvider); another subscription is listed among its
// provider's `accounts`.  A harness whose program is nowhere to be found is installed first.  Esc
// goes back with nothing done.  What to say under the page, or "".
func menuAddSubscription(cells []menu.Cell, keyboard *terminal.Keyboard, painter *terminal.Painter) string {
	// random, never `default` nor the next free name: a login once on disk under either would call
	// the new subscription logged in, on an account nobody chose
	random := make([]byte, 3)
	rand.Read(random)
	fresh := hex.EncodeToString(random)
	choices, err := menu.Addables(fresh)
	if err != nil {
		return "config: " + err.Error()
	}
	var labels []string
	for _, choice := range choices {
		labels = append(labels, choice.Label)
	}
	list := menu.List{Title: addTitle, Choices: labels, Enter: func(label string) string {
		if choices[slices.Index(labels, label)].Host != "" {
			return "open"
		}
		return "add"
	}}
	label := ""
	if len(labels) > 0 {
		label = labels[0]
	}
	defer painter.Forget()
	for {
		if label = menuChoose(func(terminal.Screen) menu.List { return list }, label, keyboard, painter); label == "" {
			return ""
		}
		picked := choices[slices.Index(labels, label)]
		switch {
		case picked.Host != "":
			if verb := adapterVerbs(keyboard, painter, picked.Host, installing(picked.Host), "", "", false); verb != "" {
				return notAdded(picked.Host, verb, label)
			}
			if menuAddThrough(picked.Host, label, cells, keyboard, painter) {
				continue // Esc there comes back here, that host highlighted
			}
			return ""
		case len(picked.Accounts) > 0:
			return addAccount(picked, keyboard, painter)
		}
		return addProvider(picked, fresh, cells, keyboard, painter)
	}
}

// addAccount is another subscription of picked's provider (menu._add_subscription): its harness's
// `login` under the account last in its Accounts, then those its `accounts`.  Its harness is its
// models' or, with none left, the shipped default's.
func addAccount(picked menu.Addable, keyboard *terminal.Keyboard, painter *terminal.Painter) string {
	harnesses, err := config.ProviderHarnesses(picked.Provider)
	if err != nil {
		return "config: " + err.Error()
	}
	if len(harnesses) == 0 {
		return "config: no model names a harness for [providers." + picked.Provider + "]"
	}
	if verb := adapterVerbs(keyboard, painter, harnesses[0], []string{"login"}, picked.Accounts[len(picked.Accounts)-1], picked.Provider, true); verb != "" {
		return notAdded(harnesses[0], verb, picked.Label)
	}
	return saved(config.ListAccounts(picked.Provider, picked.Accounts, seat.KeepConfigEfforts))
}

// addProvider is picked, a provider the config lacks, signed in on its shipped harness under
// account, then its models asked of that login while the screen waits, Esc there adding nothing.
// Where a model has the name its first would take, nothing is installed or added.
func addProvider(picked menu.Addable, account string, cells []menu.Cell, keyboard *terminal.Keyboard, painter *terminal.Painter) string {
	on, first, err := config.ShippedModel(picked.Provider)
	if err != nil {
		return "config: " + err.Error()
	}
	if taken, err := config.HasModel(first); err != nil {
		return saved(err)
	} else if taken {
		return picked.Label + " adds its model as " + first + ", and a model has that name; nothing added"
	}
	if verb := adapterVerbs(keyboard, painter, on, append(installing(on), "login"), account, picked.Provider, true); verb != "" {
		return notAdded(on, verb, picked.Label)
	}
	listed, err := waitAdapter(addTitle, cells, keyboard, painter, func(ctx context.Context) ([]modelListing.Choice, error) {
		return modelListing.ChoicesAdding(ctx, on, picked.Provider, account)
	})
	if err == context.Canceled {
		return "" // Esc while its catalog was asked: nothing added
	} else if err != nil {
		return "config: " + err.Error()
	}
	// a `<provider>/<model>` id is that provider's, the way a host names every provider's models, and
	// any other id is every provider's the harness runs
	listed = slices.DeleteFunc(listed, func(model modelListing.Choice) bool {
		owner, _, named := strings.Cut(model.ID, "/")
		return named && owner != picked.Provider
	})
	if len(listed) == 0 {
		return "the " + on + " catalog names no model; " + picked.Label + " is not added"
	}
	return saved(config.AddProvider(picked.Provider, account, listed[0].ID, listed[0].Efforts, seat.KeepConfigEfforts))
}

// installing is `install` where that harness's program is nowhere to be found, else nothing.
func installing(name string) []string {
	if harness.Present(name) {
		return nil
	}
	return []string{"install"}
}

// notAdded is what a verb of that harness that did not finish says of picked.
func notAdded(harness, verb, picked string) string {
	return config.HarnessName(harness) + " " + verb + " did not finish; " + picked + " is not added"
}

// addedAt is where a subscription an add put in sits on the page, read again: each that was not
// among before is asked whose login it is (logins.Renewed), for its line, and the first is pointed
// at; at where none went in.
func addedAt(before []menu.Cell, at int) int {
	after, err := menu.Cells(time.Now())
	if err != nil {
		return at
	}
	// a provider's only login is its usual one, listed or not
	signed := func(cell menu.Cell) [2]string {
		return [2]string{cell.Provider, cmp.Or(cell.Account, config.DefaultAccount)}
	}
	first := -1
	for i, cell := range after {
		if !slices.ContainsFunc(before, func(was menu.Cell) bool { return signed(was) == signed(cell) }) {
			logins.Renewed(cell.Provider, cell.Account, cell.Harness)
			if first < 0 {
				first = i
			}
		}
	}
	if first < 0 {
		return at
	}
	return first
}
