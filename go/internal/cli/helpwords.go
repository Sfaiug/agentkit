package cli

import (
	"agentkit/internal/config"
	"agentkit/internal/run"
)

// helpWords is help's text at the numbers in force, Python's command_help.render: from a seat,
// those of the project its record names, else the host's; the host's where those do not read,
// since help still prints.
func helpWords(text string) string {
	repo := ""
	if _, record, err := config.CurrentSession(); err == nil {
		place, filed := record["repo"]
		if !filed {
			place = record["cwd"]
		}
		repo, _ = place.(string)
	}
	if repo != "" {
		if numbers, err := run.LaunchPolicy(repo); err == nil {
			return config.InForceAt(text, numbers)
		}
	}
	return config.InForce(text)
}
