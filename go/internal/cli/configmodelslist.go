package cli

import (
	"context"
	"slices"

	"agentkit/internal/config"
	modelListing "agentkit/internal/listing"
	"agentkit/internal/terminal"
)

// modelsList is what a harness's row on Models opens (menu.models_page's listing): each model its
// catalog offers; on a host (config.ProviderHosts), each model of a provider it is logged in to, under
// that provider, then each of the config's providers it lists with no login, to log in to.
func modelsList(harness string, keyboard *terminal.Keyboard, painter *terminal.Painter) ([]throughChoice, error) {
	const title = "config · models"
	if hosts, _ := config.ProviderHosts(); !slices.Contains(hosts, harness) {
		models, err := waitConfigCatalog(harness, title, nil, keyboard, painter)
		choices := make([]throughChoice, len(models))
		for i := range models {
			choices[i].model = &models[i]
		}
		return choices, err
	}
	listed, err := waitAdapter(title, nil, keyboard, painter, func(ctx context.Context) ([]modelListing.Provider, error) {
		return modelListing.Providers(ctx, harness)
	})
	if err != nil {
		return nil, err
	}
	models, err := waitConfigCatalog(harness, title, nil, keyboard, painter)
	if err != nil {
		return nil, err
	}
	has, _, err := config.ProviderNames()
	if err != nil {
		return nil, err
	}
	choices, err := throughChoices(keyboard.Screen(), harness, listed, models, nil)
	return slices.DeleteFunc(choices, func(choice throughChoice) bool {
		return choice.model == nil && !slices.Contains(has, choice.provider.ID)
	}), err
}

// under is the provider a host lists the choice's model under, nil off a host.
func (choice throughChoice) under() *config.Listed {
	if choice.provider.ID == "" {
		return nil
	}
	return &choice.provider
}
