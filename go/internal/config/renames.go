package config

// policyRenames are the numbers' names before `review_rounds`, `executor_lines` and
// `orchestrator_lines`, Python's POLICY_RENAMES.
var policyRenames = [][2]string{{"rounds", "review_rounds"}, {"review_lines", "executor_lines"}, {"seat_lines", "orchestrator_lines"}}

// renamed is given read as Python's rename_policy keeps a run's record: an old name read as its new
// one where that is not named, and none left under its old name.
func renamed(given func(key string) (any, bool)) func(key string) (any, bool) {
	return func(key string) (any, bool) {
		for _, names := range policyRenames {
			switch key {
			case names[0]:
				return nil, false
			case names[1]:
				if value, set := given(key); set {
					return value, true
				}
				return given(names[0])
			}
		}
		return given(key)
	}
}
