package harness

import (
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// antigravityLend lends Antigravity's login as antigravity.sh's `lend` does: its token file as it
// is, as a Google refresh token stays valid after use until revoked, so the copy never lapses.  The
// file is the last of its `[worker] logins` the call names, a named account's in an app data
// directory of its own, which agy is told by the flag its sign-in carries.
func antigravityLend(login config.Login) Loan {
	logins, _ := config.Words("antigravity", "worker", "logins")
	var file string
	for _, each := range config.ManifestPaths(logins, map[string]string{"AGENTKIT_ACCOUNT": login.Account}, "") {
		file = each
	}
	data, _ := os.ReadFile(file)
	value, _ := run.Decode(data)
	if whole, ok := value.(*run.Object); ok {
		if token := whole.Dict("token"); token != nil && !blank(token.Str("refresh_token")) {
			return Loan{Copy: run.Line(value), File: file}
		}
	}
	signin := "agy"
	if login.Account != "" {
		signin = "DBUS_SESSION_BUS_ADDRESS=disabled: agy --app_data_dir=" + filepath.Base(filepath.Dir(file))
	}
	return Loan{Line: "agy: no refresh token in " + file + " to lend; run `" + signin + "` and sign in"}
}
