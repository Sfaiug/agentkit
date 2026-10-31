// Package host reads the machine's counters, read-only: memory, load, the runs slice's
// cgroup and the processes in /proc.
package host

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/tmux"
)

// Readings are one snapshot of the host, by Python ak's names; a number is a float64,
// and a missing or unreadable counter is absent.
type Readings map[string]any

// Number is the first of names that holds a number.
func (r Readings) Number(names ...string) (float64, bool) {
	for _, name := range names {
		if value, ok := r[name].(float64); ok {
			return value, true
		}
	}
	return 0, false
}

func (r Readings) set(name string, value float64, ok bool) {
	if ok {
		r[name] = value
	}
}

// Read is AK_HOST_READINGS where it holds a JSON object, standing in for /proc and the
// cgroups, else the live host.
func Read() Readings {
	var injected Readings
	if text := os.Getenv("AK_HOST_READINGS"); text != "" && json.Unmarshal([]byte(text), &injected) == nil && injected != nil {
		return injected
	}
	readings := Readings{"cpus": float64(cpuCount())}
	meminfo := map[string]float64{}
	if data, err := os.ReadFile("/proc/meminfo"); err == nil {
		for _, line := range strings.Split(string(data), "\n") {
			key, value, _ := strings.Cut(line, ":")
			if fields := strings.Fields(value); len(fields) > 0 {
				if kb, err := strconv.ParseFloat(fields[0], 64); err == nil {
					meminfo[key] = kb / 1024
				}
			}
		}
	}
	free, ok := meminfo["MemAvailable"]
	readings.set("free_mb", free, ok)
	total, ok := meminfo["MemTotal"]
	readings.set("mem_total_mb", total, ok)
	if data, err := os.ReadFile("/proc/loadavg"); err == nil {
		if fields := strings.Fields(string(data)); len(fields) > 0 {
			load, err := strconv.ParseFloat(fields[0], 64)
			readings.set("load", load, err == nil)
		}
	}
	slice, runs := sliceCgroup(), RunsCgroup()
	if limit := unitLimit(); limit != nil {
		readings["unit_limits"] = []any{limit}
	}
	cores, ok := cpuQuota(runs)
	if parent, set := cpuQuota(slice); set {
		if !ok || parent < cores {
			cores = parent
		}
		ok = true
	}
	readings.set("slice_cpu_quota", cores, ok)
	// One sample window for all three, so a burst between readings cannot count a
	// sibling as work outside the slice.
	whole := cgroupPath("")
	rates := cpuRates(runs, slice, whole)
	used, ok := rates[runs]
	if _, err := os.Stat(runs); err != nil && isDir(slice) {
		used, ok = 0, true // before its first launch the runs slice has no cgroup and holds no CPU
	}
	readings.set("slice_cpu_used", used, ok)
	if shared, ok := rates[slice]; ok {
		if all, ok := rates[whole]; ok {
			readings["outside_cpu_used"] = math.Max(0, all-shared)
		}
	}
	high, ok := megabytes(filepath.Join(slice, "memory.high"))
	if !ok {
		high, ok = megabytes(filepath.Join(slice, "memory.max"))
	}
	if held, known := heldMB(slice); ok && known {
		swap := swapMB(slice)
		readings["slice_memory_used_mb"], readings["slice_memory_high_mb"] = held+swap, high
		readings["slice_memory_swap_mb"] = swap
	}
	return readings
}

func isDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func cgroupPath(relative string) string {
	root := os.Getenv("AK_CGROUP_ROOT")
	if root == "" {
		root = "/sys/fs/cgroup"
	}
	return filepath.Join(root, strings.TrimLeft(relative, "/"))
}

// ownCgroups is this process's cgroup membership, every hierarchy's line.
func ownCgroups() (string, bool) {
	file := os.Getenv("AK_CGROUP_FILE")
	if file == "" {
		file = "/proc/self/cgroup"
	}
	data, err := os.ReadFile(file)
	return string(data), err == nil
}

// cgroupContains is whether this process's membership names that group.
func cgroupContains(name string) bool {
	data, _ := ownCgroups()
	return strings.Contains(data, name)
}

// ownCgroup is this process's unified cgroup, relative to the cgroup root.
func ownCgroup() (string, bool) {
	data, ok := ownCgroups()
	if !ok {
		return "", false
	}
	for _, line := range strings.Split(data, "\n") {
		if strings.HasPrefix(line, "0::") {
			return line[3:], true
		}
	}
	return "", false
}

// sliceCgroup is the slice every agent process starts in, under the user's manager:
// systemd reads the dashes in `agentkit-test.slice` as a path inside `agentkit.slice`.
func sliceCgroup() string {
	service := fmt.Sprintf("user@%d.service", os.Getuid())
	root := cgroupPath(filepath.Join("user.slice", fmt.Sprintf("user-%d.slice", os.Getuid()), service))
	own, _ := ownCgroup()
	parts := strings.FieldsFunc(own, func(r rune) bool { return r == '/' })
	for i, part := range parts {
		if part == service {
			root = cgroupPath(strings.Join(parts[:i+1], "/"))
			break
		}
	}
	pieces := strings.Split(tmux.Own(), "-")
	for depth := range pieces {
		root = filepath.Join(root, strings.Join(pieces[:depth+1], "-")+".slice")
	}
	return root
}

// SliceLine is the one line the screens say about where the agents run. `no slice` is no
// warning: a host with no user systemd manager starts its seats plainly.
func SliceLine() string {
	if !UserManager() {
		return "no slice (no user systemd manager)"
	}
	return sliceLine(sliceCgroup(), sliceCeiling())
}

// sliceLine reads the slice's tasks, and its ceiling, else the drop-ins' `ceiling`. A slice
// with nothing in it has no directory, so holds no tasks.
func sliceLine(cgroup string, ceiling float64) string {
	tasks, counted := number(filepath.Join(cgroup, "pids.current"))
	limit, limited := number(filepath.Join(cgroup, "pids.max"))
	if limited {
		ceiling = limit
	}
	counted = counted || !limited
	room := "no ceiling set"
	if counted && ceiling > 0 {
		room = fmt.Sprintf("%v%% of its ceiling", math.RoundToEven(100*tasks/ceiling))
	}
	plural := "s"
	if tasks == 1 {
		plural = ""
	}
	return fmt.Sprintf("slice %s.slice · %v task%s · %s", tmux.Own(), tasks, plural, room)
}

// sliceCeiling is the task ceiling the drop-ins set, 0 where none does: the live one appears
// with the slice's first process. The last file to name it wins, as systemd reads them.
func sliceCeiling() float64 {
	configHome := os.Getenv("XDG_CONFIG_HOME")
	if configHome == "" {
		home, _ := os.UserHomeDir()
		configHome = filepath.Join(home, ".config")
	}
	found := 0.0
	for _, base := range []string{"systemd/user", "systemd/user.control"} {
		files := config.Glob(filepath.Join(configHome, base, tmux.Own()+".slice.d"), "*.conf")
		sort.Strings(files)
		for _, file := range files {
			data, _ := os.ReadFile(file)
			for _, line := range strings.Split(string(data), "\n") {
				key, value, _ := strings.Cut(line, "=")
				if ceiling, err := strconv.ParseUint(strings.TrimSpace(value), 10, 64); err == nil && strings.TrimSpace(key) == "TasksMax" {
					found = float64(ceiling)
				}
			}
		}
	}
	return found
}

// RunsCgroup is where detached runs and their lander take CPU, apart from the seats.
func RunsCgroup() string {
	return filepath.Join(sliceCgroup(), tmux.Own()+"-runs.slice")
}

func number(path string) (float64, bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}
	value, err := strconv.ParseFloat(strings.TrimSpace(string(data)), 64)
	return value, err == nil && !math.IsInf(value, 0) && !math.IsNaN(value)
}

func megabytes(path string) (float64, bool) {
	value, ok := number(path)
	return value / (1024 * 1024), ok
}

// reclaimableMB is the file cache reclaim frees before any OOM kill: the pages on the
// file lists, never tmpfs or locked pages.
func reclaimableMB(path string) (float64, bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}
	total, found := 0.0, false
	for _, line := range strings.Split(string(data), "\n") {
		key, rest, _ := strings.Cut(line, " ")
		if key == "active_file" || key == "inactive_file" {
			if fields := strings.Fields(rest); len(fields) > 0 {
				if value, err := strconv.ParseFloat(fields[0], 64); err == nil {
					total, found = total+value, true
				}
			}
		}
	}
	return total / (1024 * 1024), found
}

// swapMB is what the cgroup swapped out, 0 where none is accounted: a page in swap is still in
// use, and a slice at its cap swaps rather than reclaims.
func swapMB(cgroup string) float64 {
	swap, _ := megabytes(filepath.Join(cgroup, "memory.swap.current"))
	return swap
}

func heldMB(cgroup string) (float64, bool) {
	raw, ok := megabytes(filepath.Join(cgroup, "memory.current"))
	cache, known := reclaimableMB(filepath.Join(cgroup, "memory.stat"))
	return math.Max(0, raw-cache), ok && known
}

// unitLimit is the nearest enclosing cgroup with a finite memory.high, as
// [used, high, raw, name, swap] with used excluding reclaimable cache, used and raw with swap,
// or nil.
func unitLimit() []any {
	own, ok := ownCgroup()
	if !ok {
		return nil
	}
	root := cgroupPath("")
	for current := cgroupPath(own); current == root || strings.HasPrefix(current, root+string(filepath.Separator)); current = filepath.Dir(current) {
		if high, ok := megabytes(filepath.Join(current, "memory.high")); ok {
			raw, ok := megabytes(filepath.Join(current, "memory.current"))
			cache, known := reclaimableMB(filepath.Join(current, "memory.stat"))
			if !ok || !known {
				return nil
			}
			name := filepath.Base(current)
			if current == root {
				name = "/"
			}
			swap := swapMB(current)
			return []any{math.Max(0, raw-cache) + swap, high, raw + swap, name, swap}
		}
		if current == root {
			break
		}
	}
	return nil
}

// cpuCount is the processors online, as os.cpu_count counts them, whatever this process may
// run on.
func cpuCount() int {
	data, err := os.ReadFile("/sys/devices/system/cpu/online")
	if err != nil {
		return runtime.NumCPU()
	}
	count := 0
	for _, span := range strings.Split(strings.TrimSpace(string(data)), ",") {
		first, last, ranged := strings.Cut(span, "-")
		low, err := strconv.Atoi(first)
		high, failed := low, error(nil)
		if ranged {
			high, failed = strconv.Atoi(last)
		}
		if err != nil || failed != nil || high < low {
			return runtime.NumCPU()
		}
		count += high - low + 1
	}
	return count
}

// cpuQuota is the cgroup's CPU quota in cores; `max` sets none.
func cpuQuota(cgroup string) (float64, bool) {
	data, err := os.ReadFile(filepath.Join(cgroup, "cpu.max"))
	parts := strings.Fields(string(data))
	if err != nil || len(parts) != 2 || parts[0] == "max" {
		return 0, false
	}
	allowed, err := strconv.Atoi(parts[0])
	period, failed := strconv.Atoi(parts[1])
	if err != nil || failed != nil || period == 0 {
		return 0, false
	}
	return float64(allowed) / float64(period), true
}

func usage(cgroup string) (float64, bool) {
	data, err := os.ReadFile(filepath.Join(cgroup, "cpu.stat"))
	if err != nil {
		return 0, false
	}
	for _, line := range strings.Split(string(data), "\n") {
		if strings.HasPrefix(line, "usage_usec") {
			if fields := strings.Fields(line); len(fields) > 1 {
				value, err := strconv.ParseFloat(fields[1], 64)
				return value, err == nil
			}
			return 0, false
		}
	}
	return 0, false
}

// cpuRates is each readable cgroup's live CPU use in cores over one tenth-of-a-second
// window: a single sample is cumulative since the cgroup was made, which says nothing live.
func cpuRates(cgroups ...string) map[string]float64 {
	first := map[string]float64{}
	for _, cgroup := range cgroups {
		if value, ok := usage(cgroup); ok {
			first[cgroup] = value
		}
	}
	rates := map[string]float64{}
	if len(first) == 0 {
		return rates
	}
	start := time.Now()
	time.Sleep(100 * time.Millisecond)
	elapsed := time.Since(start).Seconds()
	for cgroup, value := range first {
		if second, ok := usage(cgroup); ok {
			rates[cgroup] = math.Max(0, (second-value)/(elapsed*1e6))
		}
	}
	return rates
}

// CgroupUse is how many processes a cgroup holds and the bytes they use, false where either
// is unreadable.
func CgroupUse(cgroup string) (int, int64, bool) {
	procs, err := os.ReadFile(filepath.Join(cgroup, "cgroup.procs"))
	memory, failed := os.ReadFile(filepath.Join(cgroup, "memory.current"))
	bytes, bad := strconv.ParseInt(strings.TrimSpace(string(memory)), 10, 64)
	if err != nil || failed != nil || bad != nil {
		return 0, 0, false
	}
	count := 0
	for _, line := range strings.Fields(string(procs)) {
		if _, err := strconv.Atoi(line); err == nil {
			count++
		}
	}
	return count, bytes, true
}
