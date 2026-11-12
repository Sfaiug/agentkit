package loop

import (
	"errors"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/logins"
	"agentkit/internal/pick"
	"agentkit/internal/usage"
)

// A ready is a usage read with the harnesses asked if they can run a turn, Python's
// usage.readiness: asked on every pick and never kept with the meters, as a login comes and goes
// between two probes.  A model on one that cannot has no room, whatever its meters say.
type ready struct {
	*usage.Readings
	cannot map[string]string
}

func (r ready) Spent(name string) string {
	if why := r.cannot[name]; why != "" {
		return why
	}
	return r.Readings.Spent(name)
}

// Unstaffed is why a run's groups leave no executor or no reviewer that can run here, which
// ends a run with no meter read and no turn, in whatever home; "" where they leave both.
func Unstaffed(rules *pick.Rules) string {
	return rules.Unstaffed(unable())
}

// unable is why each model cannot run a turn here, each harness asked once for each provider it
// runs.
func unable() map[string]string {
	found := map[string]string{}
	models, err := config.Models()
	if err != nil {
		return found
	}
	asked := map[[2]string]string{}
	for name, model := range models {
		place := [2]string{model.Harness, model.Provider}
		why, seen := asked[place]
		if !seen {
			why = unready(model)
			asked[place] = why
		}
		found[name] = why
	}
	return found
}

// unready is why the model's harness cannot run a turn here, Python's usage.harness_unready: not
// installed, or its own `auth` verb saying no for every login a turn may run on, each account its
// provider lists else the usual one, which in a home with no adapter to ask is Go's own read of
// the usual login.  No answer withholds nothing, as for a login only a turn can renew.
func unready(model config.Model) string {
	program := model.Harness
	if version, _ := config.Words(model.Harness, "update", "version"); len(version) > 0 && version[0] != "" {
		program = version[0]
	}
	adapter, err := config.Adapter(model.Harness)
	unnamed := errors.Is(err, config.ErrNoAdapterDir)
	if err != nil && !unnamed || harness.Binary(program) == "" {
		return model.Harness + " is not installed"
	}
	accounts, err := config.Accounts(model.Provider)
	if err != nil || len(accounts) > 0 && unnamed {
		return ""
	}
	if unnamed {
		// the login the scripted probe reads, on ChildEnv
		login, _, err := config.UsualAccount(model.Harness)
		answer, read := harness.Auth(model.Harness, login, false)
		if err == nil && read && !answer.Yes && !answer.Lapsed {
			return model.Harness + " is not logged in"
		}
		return ""
	}
	env, err := config.ChildEnv()
	if err != nil {
		return ""
	}
	if len(accounts) == 0 {
		accounts = []string{""} // the usual login
	}
	for _, account := range accounts {
		told := append(slices.Clip(env), "AGENTKIT_PROVIDER="+model.Provider)
		if account != "" {
			told = append(told, config.AccountEnv(account))
		}
		if answered, yes, _ := logins.Auth(adapter, told); !answered || yes {
			return ""
		}
	}
	return model.Harness + " is not logged in"
}
