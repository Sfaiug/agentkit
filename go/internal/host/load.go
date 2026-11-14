package host

// Load is the host's one-minute load average and its count of cores, read from the host itself
// as Python's os.getloadavg() and os.cpu_count() read them, never from AK_HOST_READINGS: those
// stand in for the gate's readings.  The load is 0 where the platform keeps no load average.
func Load() (float64, int) {
	load, _ := loadAverage()
	return load, cpuCount()
}
