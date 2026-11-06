package config

import (
	"fmt"
	"regexp"
)

// noReview is what ak's words say of review where it is off.
const noReview = "No review: a change lands on its checks; no reviewer."

// budgetLine is a line of ak's words opening with the budget, as a list item or not.
var budgetLine = regexp.MustCompile(`(?m)^([ \t]*(?:- )?)\$Review_rounds[^\n]*`)

// budget is ak's words with each line opening with the budget said whole as no review where
// review is off, and what the budget's own placeholders say, as Python's config.in_force says them.
func budget(text string, rounds int) (string, map[string]string) {
	if rounds == 0 {
		return budgetLine.ReplaceAllString(text, "${1}"+noReview), map[string]string{
			"run_budget": noReview, "rounds_refusal": "Review is off for this host or project.",
			"resume_budget": noReview, "resume_example": "", "s": "s",
			"pr_delivery": "--review-pr sends a GitHub PR to the landing line on its checks; no reviewer."}
	}
	plural := "s"
	if rounds == 1 {
		plural = ""
	}
	return text, map[string]string{
		"run_budget":     fmt.Sprintf("--rounds sets the round limit, at most %d (default: task rounds or %d).", rounds, rounds),
		"rounds_refusal": fmt.Sprintf("a task over %d round%s is refused regardless.", rounds, plural),
		"resume_budget":  fmt.Sprintf("--rounds raises the round limit, at most %d.", rounds),
		"resume_example": fmt.Sprintf(" --rounds %d", rounds), "s": plural,
		"pr_delivery": "--review-pr reviews a GitHub PR, without an executor: the seat's own merges on\n" +
			"PASS with green checks, anyone else's asks the inbox."}
}
