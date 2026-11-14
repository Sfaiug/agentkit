//go:build !darwin

package host

// loadAverage is the one-minute load Linux keeps; Windows keeps none.
func loadAverage() (float64, bool) { return procLoad() }
