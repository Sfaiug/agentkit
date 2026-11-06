package cli

import (
	"bytes"
	"fmt"
	"os/exec"
	"slices"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// What `− remove` asks, and what it means, of a provider's last subscription and of any other
// (menu.REMOVE_PROVIDER_ASK, menu.REMOVE_SUBSCRIPTION_ASK).
var removeAsks = [2][2]string{
	{"Remove %s and its models?", "Its models leave the config, and its logins are signed out on this machine."},
	{"Remove %s?", "Nothing new starts on it, and its login is signed out on this machine."}}

// menuRemoveSubscription is `− remove` under a row of Subscriptions (menu.config_remove_provider):
// for its provider's last subscription, `Remove <provider> and its models?`, which takes out its
// table, its models and their places in [defaults] (config.RemoveProvider), and for any other
// `Remove <subscription>?`, which takes it out of its provider's `accounts`; asked under its name,
// `Keep` lit and Esc keeping it.  Once saved, the subscription that went is signed out on this
// machine.  The last provider is refused without asking.  What to say under the page, or "".
func menuRemoveSubscription(cell menu.Cell, keyboard *terminal.Keyboard, painter *terminal.Painter) string {
	accounts, err := config.Accounts(cell.Provider)
	if err != nil {
		return saved(err)
	}
	has, _, err := config.ProviderNames()
	if err != nil {
		return saved(err)
	}
	// a provider listing no subscription has its usual login alone
	last := len(accounts) < 2
	if last && len(has) < 2 {
		return "the config needs one provider"
	}
	ask := removeAsks[1]
	if last {
		ask = removeAsks[0] // its label is its provider's name
	}
	defer painter.Forget()
	if menuChoose(func(s terminal.Screen) menu.List {
		return menu.Confirm(s, "config · "+cell.Label, "", fmt.Sprintf(ask[0], cell.Label), ask[1], "Remove")
	}, "Keep", keyboard, painter) != "Remove" {
		return ""
	}
	if last {
		err = config.RemoveProvider(cell.Provider, seat.KeepConfigEfforts)
	} else {
		err = config.ListAccounts(cell.Provider, slices.DeleteFunc(accounts, func(account string) bool { return account == cell.Account }), seat.KeepConfigEfforts)
	}
	if err != nil {
		return saved(err) // still listed, so still signed in
	}
	return signedOut(cell)
}

// signedOut is that subscription signed out on this machine by its harness's adapter's `logout`
// (menu._signed_out): "" once it is, else what to say while it is still on it, the last line its
// adapter said and the command that signs it out by hand, which names its account even when empty,
// as a seat's shell has one of its own.
func signedOut(cell menu.Cell) string {
	logout, err := adapterCall(cell.Harness, cell.Account, cell.Provider, "logout")
	said := ""
	if err == nil {
		var stderr bytes.Buffer
		logout.Stderr = &stderr
		if err = logout.Run(); err == nil {
			return ""
		}
		if lines := config.SplitLines(strings.TrimSpace(stderr.String())); len(lines) > 0 {
			said = lines[len(lines)-1]
		}
	}
	if _, exited := err.(*exec.ExitError); !exited {
		said = err.Error()
	}
	if said != "" {
		said = " (" + said + ")"
	}
	var byHand []string
	for _, pair := range adapterTold(cell.Account, cell.Provider) {
		key, value, _ := strings.Cut(pair, "=")
		byHand = append(byHand, key+"="+commandhelp.ShellJoin([]string{value}))
	}
	return cell.Label + "'s login is still on this machine" + said + "; sign it out with " +
		strings.Join(append(byHand, commandhelp.ShellJoin([]string{config.AdapterPath(cell.Harness), "logout"})), " ")
}
