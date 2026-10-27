package host

import (
	"fmt"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/config"
)

const (
	heavyCPUs  = 0.7 // one heavy suite's cores
	heavyMemMB = 410 // ... and its memory
)

// G is megabytes as gigabytes to one decimal, trailing zeros dropped; `?` for no reading.
func G(mb float64, ok bool) string {
	if !ok {
		return "?"
	}
	text := strconv.FormatFloat(mb/1024, 'f', 1, 64)
	return strings.TrimSuffix(strings.TrimRight(text, "0"), ".")
}

// Short is a number as Python's `:g` writes it.
func Short(value float64) string {
	return strconv.FormatFloat(value, 'g', 6, 64)
}

func unknown(value float64, ok bool) string {
	if !ok {
		return "?"
	}
	return Short(value)
}

// A memory is a cgroup's use against its limit, the reclaimable cache left out, swap in;
// raw is with the cache, where the readings carry it.
type memory struct {
	used, high, raw, swap float64
	hasRaw                bool
	name                  string
}

// unitMemory is the cgroup the gate reads: the first valid `unit_limits` entry, the nearest
// limit first, else the flat unit counters.
func (r Readings) unitMemory() (memory, bool) {
	if limits, ok := r["unit_limits"].([]any); ok {
		for _, entry := range limits {
			parts, _ := entry.([]any)
			if len(parts) < 2 {
				continue
			}
			used, a := parts[0].(float64)
			high, b := parts[1].(float64)
			if !a || !b || high < 0 {
				continue
			}
			found := memory{used: used, high: high}
			if len(parts) > 2 {
				found.raw, found.hasRaw = parts[2].(float64)
			}
			if len(parts) > 3 {
				found.name, _ = parts[3].(string)
			}
			if len(parts) > 4 {
				found.swap, _ = parts[4].(float64)
			}
			return found, true
		}
	}
	used, a := r.Number("unit_memory_current_mb", "memory_current_mb")
	high, b := r.Number("unit_memory_high_mb", "memory_high_mb")
	if !a || !b || high < 0 {
		return memory{}, false
	}
	raw, hasRaw := r.Number("unit_memory_raw_mb", "unit_memory_with_cache_mb", "memory_raw_mb")
	name, _ := r["unit_memory_name"].(string)
	if _, set := r["unit_memory_name"]; !set {
		name, _ = r["unit_name"].(string)
	}
	swap, _ := r.Number("unit_memory_swap_mb")
	return memory{used, high, raw, swap, hasRaw, name}, true
}

// sliceOrUnitMemory is the slice's memory, else the nearest limited unit's.
func (r Readings) sliceOrUnitMemory() (memory, bool) {
	used, a := r.Number("slice_memory_used_mb")
	high, b := r.Number("slice_memory_high_mb")
	if a && b && high >= 0 {
		swap, _ := r.Number("slice_memory_swap_mb")
		return memory{used: used, high: high, swap: swap}, true
	}
	return r.unitMemory()
}

// inUse is ` · <name> 1.2 of 4 G in use`, and what of it is in swap.
func (m memory) inUse(name string) string {
	text := fmt.Sprintf(" · %s %s of %s G in use", name, G(m.used, true), G(m.high, true))
	if m.swap != 0 {
		text += " · " + G(m.swap, true) + " G in swap"
	}
	return text
}

// heavyLimit is the suites running plus how many more the live headroom fits, at least one:
// the idle cores over one suite's 0.7, free memory over its 410 MB, whichever fits fewer, and
// never more in all than the cores and memory fit with nothing running.
func (r Readings) heavyLimit() int {
	running := 0
	for _, path := range heavyLocks() {
		if held(path) {
			running++
		}
	}
	var cpuFree, cpuWhole float64
	hasCPU := true
	cpuQuota, hasCPUQuota := r.Number("slice_cpu_quota")
	cpus, hasCPUs := r.Number("cpus", "nproc")
	used, hasUsed := r.Number("slice_cpu_used")
	if hasCPUQuota || hasCPUs && hasUsed {
		if !hasCPUQuota {
			cpuQuota = cpus
		}
		if outside, ok := r.Number("outside_cpu_used"); ok && hasCPUs {
			cpuQuota = min(cpuQuota, cpus-outside)
		}
		cpuFree, cpuWhole = cpuQuota, cpuQuota
		if hasUsed {
			cpuFree -= used
		}
	} else {
		cpuFree, cpuWhole, hasCPU = cpus, cpus, hasCPUs
		if load, ok := r.Number("load", "load1", "load_1m"); hasCPUs && ok {
			cpuFree = cpus - load
		}
	}
	var memFree, memWhole float64
	hasMem, hasWhole := true, true
	if limit, ok := r.sliceOrUnitMemory(); ok {
		memFree, memWhole = limit.high-limit.used, limit.high
	} else {
		memFree, hasMem = r.Number("free_mb", "mem_available_mb", "mem_available")
		memWhole, hasWhole = r.Number("mem_total_mb")
	}
	var candidates []int
	if hasCPU {
		candidates = append(candidates, int(cpuFree/heavyCPUs))
	}
	if hasMem {
		candidates = append(candidates, int(memFree/heavyMemMB))
	}
	if len(candidates) == 0 {
		return 1
	}
	if hasCPU {
		candidates = append(candidates, int(cpuWhole/heavyCPUs)-running)
	}
	if hasWhole {
		candidates = append(candidates, int(memWhole/heavyMemMB)-running)
	}
	return max(1, running+max(0, slices.Min(candidates)))
}

// heavyLocks are the turn files on disk, a shrunk limit's higher ones included: the suites
// still holding those count too.
func heavyLocks() []string {
	paths, _ := filepath.Glob(filepath.Join(config.Home(), "runs", ".heavy-*.lock"))
	highest := -1
	for _, path := range paths {
		name := strings.TrimSuffix(strings.TrimPrefix(filepath.Base(path), ".heavy-"), ".lock")
		if index, err := strconv.Atoi(name); err == nil && index > highest {
			highest = index
		}
	}
	var locks []string
	for index := 0; index <= highest; index++ {
		locks = append(locks, filepath.Join(config.Home(), "runs", fmt.Sprintf(".heavy-%d.lock", index)))
	}
	return locks
}

// StatusLines are the two lines a run listing opens with: what the host has and when it
// admits a run, then the heavy-suite turns in force and whether a setting pins them.
func StatusLines() (string, error) {
	readings := Read()
	total, _ := readings.Number("mem_total_mb", "total_mb", "mem_total")
	cpus, _ := readings.Number("cpus", "nproc")
	if cpus == 0 {
		cpus = 1
	}
	minimum, err := config.MinFreeMB(total)
	if err != nil {
		return "", err
	}
	maximum, err := config.MaxLoad(cpus)
	if err != nil {
		return "", err
	}
	var gates []string
	if minimum != 0 {
		gates = append(gates, "≥ "+G(minimum, true)+" G free")
	}
	// Only a pinned load gates CPU, so only it shows the load.
	signal := ""
	if config.MaxLoadSet() {
		if maximum != 0 {
			gates = append(gates, "load ≤ "+Short(maximum))
		}
		load, ok := readings.Number("load", "load1")
		signal = " · load " + unknown(load, ok)
	}
	admitted := "a run is admitted (host memory and load gates off)"
	if len(gates) > 0 {
		admitted = "a run is admitted while " + strings.Join(gates, " and ")
	}
	if limit, _ := config.MaxRuns(); limit == 1 {
		admitted += " · at most 1 run at once"
	} else if limit > 0 {
		admitted += fmt.Sprintf(" · at most %d runs at once", limit)
	}
	var heavy string
	switch pinned, err := config.MaxGates(); {
	case err == nil && pinned == 0:
		heavy = "heavy suites: no cap (pinned)"
	case err == nil && pinned > 0:
		heavy = fmt.Sprintf("heavy suites: %d at once (pinned)", pinned)
	default:
		heavy = fmt.Sprintf("heavy suites: %d at once (derived)", readings.heavyLimit())
	}
	segment := ""
	unit, hasUnit := readings.unitMemory()
	if hasUnit && unit.name != "" {
		segment = unit.inUse(unit.name)
	}
	// From a shell outside it, ak's slice is not the unit above, yet its swap is what
	// admission reads.
	ours, hasOurs := readings.sliceOrUnitMemory()
	slice := filepath.Base(sliceCgroup())
	if hasOurs && ours.swap != 0 && !(hasUnit && ours == unit) && !(hasUnit && unit.name == slice) {
		segment += ours.inUse(slice)
	}
	free, ok := readings.Number("free_mb", "mem_available_mb")
	return fmt.Sprintf("host: %d cpus%s · %s G free%s · %s\n%s",
		int(cpus), signal, G(free, ok), segment, admitted, heavy), nil
}
