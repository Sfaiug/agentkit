package config

import "strings"

// ModelName is the full name every screen shows the configured model by (config.model_name): its
// harness's catalog label for its id, else that id with a provider's prefix off; the name itself
// where it is no entry or names no id of its own.
func ModelName(name string, models map[string]Model) string {
	model, listed := models[name]
	if !listed || model.ID == "" || model.ID == "default" {
		return name
	}
	catalog, _ := Tree(model.Harness, "catalog")
	if entry, ok := catalog[model.ID].(map[string]any); ok {
		if label, ok := entry["label"].(string); ok && label != "" && label != model.ID {
			return label
		}
	}
	return model.ID[strings.LastIndexByte(model.ID, '/')+1:]
}

// ModelAt is how every screen names model `name` at its effort `key` (RoleEfforts, else
// `effort`) in `models`, a seat's as it runs them (config.model_at): its full name, then that
// effort, alone where it is none.
func ModelAt(name, key string, models map[string]Model) string {
	efforts := models[name].Efforts
	effort, set := efforts[key]
	if !set {
		effort = efforts["effort"]
	}
	if effort == "" || effort == "none" {
		return ModelName(name, models)
	}
	return ModelName(name, models) + " " + effort
}
