package config

import "fmt"

// DoneCheckModel is the name `[done_check] model` gives the model that checks a seat's work, ""
// where it gives none, as Python's done_check.checker reads it.
func DoneCheckModel() (string, error) {
	value, path, err := topLevel("done_check")
	section, _ := value.(*table)
	if err != nil || section == nil || !truthy(section.values["model"]) {
		return "", err
	}
	name, named := section.values["model"].(string)
	if !named {
		return "", fmt.Errorf("%s: [done_check] model must name a model (got %s)", path, valueRepr(section.values["model"]))
	}
	return name, nil
}
