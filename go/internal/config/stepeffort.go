package config

// StepEffort is Python's menu.config_effort for new seats: `step` taken on the entry they open
// at, the whole file written as Python's save writes it, [defaults] as the file holds them.
// `keep` is as RememberDefaults's.  An error leaves the file as it was.
func StepEffort(step EffortStep, keep func() error) error {
	_, file, err := modelFile()
	if err != nil {
		return err
	}
	return saveConfig(file, func(root *table) error { return recommendedEfforts(root, []EffortStep{step}) }, keep)
}
