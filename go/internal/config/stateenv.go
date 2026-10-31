package config

import "regexp"

var leadingVariable = regexp.MustCompile(`^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))`)

// StateEnv is the variables a harness's state and logins are found by, as each manifest's
// `[worker] state` and `logins` begin with one: a seat takes them from whoever opens it (Python's
// config.state_env_names).
func StateEnv() ([]string, error) {
	manifests, err := manifests()
	var names []string
	for _, root := range manifests {
		for _, path := range append(words(root, "worker", "state"), words(root, "worker", "logins")...) {
			if found := leadingVariable.FindStringSubmatch(path); found != nil {
				names = append(names, found[1]+found[2])
			}
		}
	}
	return names, err
}
