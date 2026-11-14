package config

// PlanPrice is the list price a month of the plan named exactly so on that harness's manifest's
// `[plans]`, Python's harness plugin's plans as usage.price reads them; nil for a plan not listed
// or a value that is no number.
func PlanPrice(harness, plan string) (*float64, error) {
	plans, err := Section(harness, "plans")
	if price, ok := tomlNumber(plans[plan]); ok {
		return &price, err
	}
	return nil, err
}
