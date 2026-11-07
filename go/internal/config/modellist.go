package config

import "slices"

// ModelList is the model list as the config holds it, Python's matrix.compared reads it:
// companies, the makers you have as the boards name them, nil where `companies` is not set; and
// off, `models_off`, the releases of theirs turned off.  Each is named once, as config.load keeps
// them: a maker written twice would be two rows of the company list the keys cannot tell apart.
func ModelList() (companies, off []string, err error) {
	root, err := load()
	if err != nil {
		return nil, nil, err
	}
	named := func(key string) []string {
		listed, set := root.values[key].([]any)
		if !set {
			return nil
		}
		found := []string{} // set, even empty: then no maker is yours
		for _, one := range listed {
			if !slices.Contains(found, one.(string)) {
				found = append(found, one.(string))
			}
		}
		return found
	}
	return named("companies"), named("models_off"), nil
}
