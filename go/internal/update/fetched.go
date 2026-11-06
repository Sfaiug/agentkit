package update

import "agentkit/internal/config"

// Version is the version `ak update` reads of that harness here, Python's VERSION in what its
// update.version says, as Python's machine_turn._program puts it for a manifest's `{version}`: ""
// where no configured harness of that name says how it is upgraded, or its version cannot be read.
func Version(name string) string {
	plans, err := harnesses()
	env, unread := config.ChildEnv()
	if err != nil || unread != nil {
		return ""
	}
	for _, each := range plans {
		if each.name == name {
			identity, _ := version(each, append(env, pins...))
			return versionWord.FindString(identity)
		}
	}
	return ""
}
