package loop

import (
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/usage"
	"agentkit/internal/worker"
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

// withRoom is that read, each harness asked once for each provider it runs.
func withRoom(readings *usage.Readings) ready {
	found := ready{readings, map[string]string{}}
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
		found.cannot[name] = why
	}
	return found
}

// unready is why the model's harness cannot run a turn here, Python's usage.harness_unready: not
// installed, or its own `auth` verb saying no.  No answer withholds nothing.
func unready(model config.Model) string {
	program := model.Harness
	if version, _ := config.Words(model.Harness, "update", "version"); len(version) > 0 && version[0] != "" {
		program = version[0]
	}
	adapter, err := config.Adapter(model.Harness)
	if err != nil || harness.Binary(program) == "" {
		return model.Harness + " is not installed"
	}
	env, err := config.ChildEnv()
	if err != nil {
		return ""
	}
	if answered, yes, _ := worker.Login(adapter, append(env, "AGENTKIT_PROVIDER="+model.Provider)); answered && !yes {
		return model.Harness + " is not logged in"
	}
	return ""
}
