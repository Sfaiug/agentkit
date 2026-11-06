package machines

import (
	"fmt"
	"math"
	"strings"
	"time"

	"agentkit/internal/run"
)

// Overview is m as `c`'s Machines page says it, off the reading String says (menu.machine_value):
// home, rented until its end, or its kind; its size; then how busy it is and the memory used, or
// since when it has not answered, or that it never has.
func (m Machine) Overview() string {
	kind := kindOf(m.checks, m.said)
	if m.Name == Here {
		kind = "home"
	} else if m.until != 0 {
		kind = "rented until " + time.Unix(m.until, 0).Format("15:04")
	}
	words := []string{kind}
	number := func(key string) float64 {
		value, _ := m.said.Num(key)
		return value
	}
	if m.said != nil {
		words = append(words, fmt.Sprintf("%s cores · %s", run.Text(m.said.Get("cores")), gb(number("memory_mb"))))
	}
	answered := func(check any) bool { yes, _ := at(check, 1).(bool); return yes }
	switch last := len(m.checks) - 1; {
	case last >= 0 && !answered(m.checks[last]):
		for last > 0 && !answered(m.checks[last-1]) {
			last--
		}
		since, _ := run.Num(at(m.checks[last], 0))
		words = append(words, "not answering since "+when(since))
	case m.said != nil:
		total := number("memory_mb")
		busy := min(100, max(0, int(math.RoundToEven(100*number("load")/max(1, number("cores"))))))
		words = append(words, fmt.Sprintf("%d%% busy · %s of %s used", busy,
			strings.TrimSuffix(gb(total-number("free_mb")), " GB"), gb(total)))
	default:
		words = append(words, "never answered")
	}
	return strings.Join(words, " · ")
}
