package quality

import (
	"math"
	"math/big"
	"slices"
)

// Python's float sums, roots and powers, to the last digit: `ak models --json` prints them whole,
// and a home's boards read by either program say the same.

// precision is enough bits that rounding the result to a float64 rounds the exact answer.
const precision = 1024

// sum is Python's sum over floats, compensated since 3.12.
func sum(values []float64) float64 {
	total, lost := 0.0, 0.0
	for _, value := range values {
		next := total + value
		if math.Abs(total) >= math.Abs(value) {
			lost += (total - next) + value
		} else {
			lost += (value - next) + total
		}
		total = next
	}
	if lost != 0 && !math.IsInf(lost, 0) && !math.IsNaN(lost) {
		total += lost
	}
	return total
}

// hypot is Python's math.hypot over each value, rounded from the exact root of squares.
func hypot(values map[source]float64) float64 {
	squares := new(big.Float).SetPrec(precision)
	for _, value := range values {
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return value
		}
		one := new(big.Float).SetPrec(precision).SetFloat64(value)
		squares.Add(squares, one.Mul(one, one))
	}
	root, _ := new(big.Float).SetPrec(precision).Sqrt(squares).Float64()
	return root
}

// Median is Python's statistics.median of at least one value.
func Median(values []float64) float64 {
	sorted := slices.Sorted(slices.Values(values))
	middle := len(sorted) / 2
	if len(sorted)%2 == 1 {
		return sorted[middle]
	}
	return (sorted[middle-1] + sorted[middle]) / 2
}

// stdev is Python's statistics.stdev of at least two values, worked in exact fractions.
func stdev(values []float64) float64 {
	mean := new(big.Rat)
	exact := make([]*big.Rat, len(values))
	for i, value := range values {
		if exact[i] = new(big.Rat).SetFloat64(value); exact[i] == nil {
			return math.NaN()
		}
		mean.Add(mean, exact[i])
	}
	mean.Quo(mean, big.NewRat(int64(len(values)), 1))
	squares := new(big.Rat)
	for _, value := range exact {
		apart := new(big.Rat).Sub(value, mean)
		squares.Add(squares, apart.Mul(apart, apart))
	}
	squares.Quo(squares, big.NewRat(int64(len(values)-1), 1))
	root, _ := new(big.Float).SetPrec(precision).Sqrt(new(big.Float).SetPrec(precision).SetRat(squares)).Float64()
	return root
}

var bigLn10, _ = new(big.Float).SetPrec(precision).SetString("2.302585092994045684017991454684364207601101488628772976033327900967572609677352480235997205089598298341967784042286248633409525465082806756666287369098781689482907208325554680843799894826233198528393505308965377732628846163366222287698219886746543667474404243274365155048934314939391479619404400222105101714174800368808401264708068556774321622835522011480466371565912137345074785694768346361679210180644507064800027750268491674655058685693567815573607")

// pow10 is 10 ** x as C's pow, which Python's is and Go's math.Pow is not, gets it: rounded from
// the exact power, by the series of e ** (x ln 10).  Past a float's range it is Go's.
func pow10(x float64) float64 {
	if math.IsNaN(x) || math.Abs(x) > 300 {
		return math.Pow(10, x)
	}
	power := new(big.Float).SetPrec(precision).SetFloat64(x)
	power.Mul(power, bigLn10)
	total := new(big.Float).SetPrec(precision).SetInt64(1)
	term := new(big.Float).SetPrec(precision).SetInt64(1)
	for k := int64(1); term.Sign() != 0 && term.MantExp(nil) > total.MantExp(nil)-precision; k++ {
		term.Mul(term, power)
		term.Quo(term, new(big.Float).SetPrec(precision).SetInt64(k))
		total.Add(total, term)
	}
	found, _ := total.Float64()
	return found
}
