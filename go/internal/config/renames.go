package config

import "slices"

// policyRenames are the numbers' names before `review_rounds`, `executor_lines` and
// `orchestrator_lines`, Python's POLICY_RENAMES.
var policyRenames = [][2]string{{"rounds", "review_rounds"}, {"review_lines", "executor_lines"}, {"seat_lines", "orchestrator_lines"}}

// renamePolicy reads config.toml's numbers as Python's every command leaves the file
// (config.migrate_policy): an old name read as its new one, dropped where the file names both.
func renamePolicy(root *table) {
	for _, names := range policyRenames {
		value, held := root.values[names[0]]
		if !held {
			continue
		}
		delete(root.values, names[0])
		root.keys = slices.DeleteFunc(root.keys, func(key string) bool { return key == names[0] })
		if _, named := root.values[names[1]]; !named {
			root.put(names[1], value)
		}
	}
}
