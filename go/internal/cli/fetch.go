package cli

import "agentkit/internal/fetch"

func init() { commands["fetch"] = fetch.Main }
