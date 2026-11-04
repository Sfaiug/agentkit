package cli

import (
	"cmp"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/quality"
)

// Read company colours with the lineup, so moving the pointer only draws.
func modelColours(rows []quality.Row) map[string]string {
	colours := map[string]string{}
	for _, row := range rows {
		if row.Maker == "" || colours[row.Maker] != "" {
			continue
		}
		provider, _ := config.Company(row.Maker)
		_, colour, _ := config.ProviderLook(provider)
		_, fallback := harness.Company(provider)
		colours[row.Maker] = cmp.Or(colour, fallback, "accent")
	}
	return colours
}
