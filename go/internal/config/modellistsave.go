package config

import "slices"

// SaveModelList is Python's menu.models_listed: `companies` written as your companies and `off`,
// sorted, as `models_off`, the key gone where none is off, the whole file written as Python's
// save writes it.  `keep` is as RememberDefaults's.  An error leaves the file as it was.
func SaveModelList(companies, off []string, keep func() error) error {
	return saveConfig(fileTable, func(root *table) error {
		root.put("companies", listed(companies))
		if len(off) == 0 {
			delete(root.values, "models_off")
		} else {
			root.put("models_off", listed(slices.Sorted(slices.Values(off))))
		}
		return nil
	}, keep)
}
