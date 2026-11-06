package config

import (
	"slices"
	"strings"
)

// ModelsKey is what of the config a lineup is computed from, as Python's matrix.config_key: each
// offered model's name, harness, id and the effort it runs each role at, by name.
func ModelsKey() ([][]string, error) {
	root, err := load()
	if err != nil {
		return nil, err
	}
	key := [][]string{}
	for _, name := range offered(root) {
		entry := root.values["models"].(*table).values[name].(*table)
		text := func(field string) string {
			value, _ := entry.values[field].(string)
			return value
		}
		row := []string{name, text("harness"), text("model")}
		for _, field := range RoleEfforts {
			if _, set := entry.values[field]; !set {
				field = "effort"
			}
			row = append(row, text(field))
		}
		key = append(key, row)
	}
	slices.SortFunc(key, func(a, b []string) int { return strings.Compare(a[0], b[0]) })
	return key, nil
}

// HarnessNames is every harness with a manifest, sorted.
func HarnessNames() ([]string, error) {
	found, err := manifests()
	if err != nil {
		return nil, err
	}
	var names []string
	for name := range found {
		names = append(names, name)
	}
	slices.Sort(names)
	return names, nil
}

// CatalogTable is the `[catalog]` table of that harness's manifest as a listing's rows, [id,
// efforts], in file order: written from the harness's own docs for one that cannot list its models.
func CatalogTable(harness string) ([][]string, error) {
	found, err := manifests()
	if err != nil {
		return nil, err
	}
	catalog, _ := found[harness].get("catalog").(*table)
	if catalog == nil {
		return nil, nil
	}
	var rows [][]string
	for _, model := range catalog.keys {
		if _, ok := catalog.values[model].(*table); ok {
			rows = append(rows, []string{model, strings.Join(words(catalog, model, "efforts"), " ")})
		}
	}
	return rows, nil
}
