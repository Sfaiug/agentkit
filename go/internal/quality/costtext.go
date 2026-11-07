package quality

import "strconv"

// CostText is a priced row's cost as the models screen and its why say it, Python's
// menu.model_cost: a week share in percent, else dollars.
func (s *Said) CostText(row *Rating) string {
	if s.CostUnit == "share" {
		return strconv.FormatFloat(*row.Cost, 'f', 2, 64) + "%"
	}
	return "$" + strconv.FormatFloat(*row.Cost, 'f', 2, 64)
}
