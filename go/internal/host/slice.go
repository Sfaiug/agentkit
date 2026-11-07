package host

import (
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"agentkit/internal/config"
)

// What a slice's drop-ins set, as Python's orch reads them, and the one way a tick changes the runs
// slice; what the kernel says of them is readings.go's.

// SetOnRuns sets one property of the runs slice for this boot only, and is systemctl's exit code.
func SetOnRuns(property string) (int, error) {
	return setProperty(filepath.Base(RunsCgroup()), property)
}

// setProperty sets one property of a unit for this boot only, and is systemctl's exit code.
func setProperty(unit, property string) (int, error) {
	code, _, err := Systemctl("set-property", "--runtime", unit, property)
	return code, err
}

// dropInTasksMax is the TasksMax a slice's drop-ins set, false where none does. The last file to
// name it wins, as systemd reads them.
func dropInTasksMax(slice string) (int, bool) {
	found, set := 0, false
	for _, value := range dropInValues(slice, "TasksMax") {
		if ceiling, err := strconv.Atoi(value); err == nil && config.Digits(value) {
			found, set = ceiling, true
		}
	}
	return found, set
}

var memorySpec = regexp.MustCompile(`(?i)^(\d+)([KMGT%]?)$`)

// dropInMemoryMax is the MemoryMax a slice's drop-ins set in MiB, false where none does or the
// last says `max` or `infinity`. A bare number is bytes; a percentage is of MemTotal.
func dropInMemoryMax(slice string) (int, bool) {
	found, set := 0, false
	for _, value := range dropInValues(slice, "MemoryMax") {
		if lower := strings.ToLower(value); lower == "max" || lower == "infinity" {
			found, set = 0, false
			continue
		}
		parts := memorySpec.FindStringSubmatch(value)
		if parts == nil {
			continue
		}
		number, err := strconv.Atoi(parts[1])
		if err != nil {
			continue
		}
		switch strings.ToUpper(parts[2]) {
		case "":
			found = number >> 20
		case "K":
			found = number >> 10
		case "M":
			found = number
		case "G":
			found = number << 10
		case "T":
			found = number << 20
		case "%":
			total, ok := memTotalMB()
			if !ok {
				continue
			}
			found = total * number / 100
		}
		set = true
	}
	return found, set
}

// dropInValues are the values a slice's drop-ins give key, stripped, in the order systemd reads
// them.
func dropInValues(slice, key string) []string {
	var values []string
	for _, file := range dropIns(slice) {
		data, _ := os.ReadFile(file)
		for _, line := range strings.Split(string(data), "\n") {
			name, value, _ := strings.Cut(line, "=")
			if strings.TrimFunc(name, config.Space) == key {
				values = append(values, strings.TrimFunc(value, config.Space))
			}
		}
	}
	return values
}
