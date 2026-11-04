package config

// CloudBudget is the cloud setting as google_cloud._setting reads it, zero for an invalid cap.
func CloudBudget() (active bool, cap float64) {
	value, _, _ := topLevel("google_cloud")
	cloud, _ := value.(*table)
	active = cloud.get("active") == true
	value = cloud.get("max_month")
	cap, valid := tomlNumber(value)
	if !valid || cap < 0 {
		cap = 0
	}
	if _, floating := value.(float64); floating && cap >= 1e12 {
		cap = 0
	}
	return
}
