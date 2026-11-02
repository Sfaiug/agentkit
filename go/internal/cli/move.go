package cli

import "agentkit/internal/move"

func init() { commands["move"] = move.Main }
