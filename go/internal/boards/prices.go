package boards

import (
	"math"
	"slices"

	"agentkit/internal/quality"
)

// listed is the column of a release's values listing its price a million tokens of each type of
// token ak keeps: input, cache write, cache read and output.
var listed = []string{"aa.price1mInputTokens", "aa.cacheWritePrice", "aa.cacheHitPrice", "aa.price1mOutputTokens"}

// Prices is a model's listed price a million tokens of each type, nil where it has none, Python's
// spend._prices: its release's, the one Found finds alone, at the release's default effort, else
// its first; a cache price it lists none of is its input price, and one listing no input or output
// price has none.
func (index Index) Prices(model string) []float64 {
	if model == "" {
		return nil
	}
	var release *Release
	for _, one := range index.Found(model) {
		if release != nil && release.Slug != one.Release.Slug {
			return nil
		}
		release = one.Release
	}
	if release == nil || len(release.Efforts) == 0 {
		return nil
	}
	values := release.Efforts[max(0, slices.IndexFunc(release.Efforts, func(effort *Effort) bool { return effort.Default }))].Values
	fresh, priced := values.Num(listed[0])
	if !priced || !values.Has(listed[len(listed)-1]) {
		return nil
	}
	prices := make([]float64, len(listed))
	for i, column := range listed {
		prices[i] = fresh
		if price, ok := values.Num(column); ok {
			prices[i] = price
		}
	}
	return prices
}

// Dollars is what counts of each type cost at prices, a million tokens of each, Python's
// spend._dollars: false where prices are nil or the cost is no float's, as a board listing an
// infinite price or one near a float's largest: summed, it would leave every cost it joins
// infinite or NaN.
func Dollars(prices, counts []float64) (float64, bool) {
	if prices == nil {
		return 0, false
	}
	costs := make([]float64, len(prices))
	for i, price := range prices {
		costs[i] = counts[i] * price
	}
	dollars := quality.Sum(costs) / 1e6
	return dollars, !math.IsInf(dollars, 0) && !math.IsNaN(dollars)
}
