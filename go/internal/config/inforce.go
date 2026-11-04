package config

import (
	"regexp"
	"strconv"
)

// templated is a placeholder of Python's string.Template.
var templated = regexp.MustCompile(`(?i)\$(?:(\$)|([_a-z][_a-z0-9]*)|\{([_a-z][_a-z0-9]*)\})`)

// roundsSaid is a budget of rounds opening a sentence, and the round past it.
var roundsSaid = map[int][2]string{1: {"One", "a second"}, 2: {"Two", "a third"}, 3: {"Three", "a fourth"},
	4: {"Four", "a fifth"}, 5: {"Five", "a sixth"}}

// InForce is ak's own words as this host's numbers make them (config.in_force); a config.toml
// that does not read gives ak's defaults, since words only saying the numbers refuse nothing.
// Only ak's own text comes here: a rule the owner or a project wrote is theirs to the letter.
func InForce(text string) string {
	numbers, err := HostNumbers()
	if err != nil {
		numbers = Numbers{defaultRounds, DefaultReviewLines, 50}
	}
	said, known := roundsSaid[numbers.Rounds]
	if !known {
		said = [2]string{strconv.Itoa(numbers.Rounds), "round " + strconv.Itoa(numbers.Rounds+1)}
	}
	plural := "s"
	if numbers.Rounds == 1 {
		plural = ""
	}
	values := map[string]string{"review_rounds": strconv.Itoa(numbers.Rounds), "executor_lines": strconv.Itoa(numbers.ReviewLines),
		"orchestrator_lines": strconv.Itoa(numbers.SeatLines), "Review_rounds": said[0], "one_over": said[1], "s": plural,
		"executor_size": executorSize(numbers.ReviewLines), "orchestrator_size": orchestratorSize(numbers.SeatLines)}
	return templated.ReplaceAllStringFunc(text, func(found string) string {
		parts := templated.FindStringSubmatch(found)
		if parts[1] != "" {
			return "$"
		}
		if value, known := values[parts[2]+parts[3]]; known {
			return value
		}
		return found
	})
}
