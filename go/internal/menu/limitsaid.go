package menu

import (
	"fmt"
	"math"

	"agentkit/internal/history"
)

// RoundsSaid is what `runs` (history.RoundEndings) would have done at held review rounds, said
// under RoundsChart, Python's menu.rounds_said, M the last round one merged in and F the number
// that failed.  Off, how many went that way; under M, those merged after held, and F, back to their
// orchestrator sooner; at M, F back; one past M, a guess that F merge at the share round M merged
// of its merges and F; further, nothing they can say.  "" with no run, unless off.
func RoundsSaid(runs []history.Row, held int) string {
	var merged []int
	for _, run := range runs {
		if round, ok := run.Num("round"); ok {
			merged = append(merged, int(round))
		}
	}
	count := func(keep func(int) bool) (n int) {
		for _, round := range merged {
			if keep(round) {
				n++
			}
		}
		return n
	}
	if held == 0 {
		said := "None of your runs went that way, so they can't say how it would go."
		if bare := count(func(round int) bool { return round == 0 }); bare > 0 {
			said = fmt.Sprintf("%d of your runs went that way.", bare)
		}
		return "Off: no reviewer, so a change lands when its checks pass. " + said
	}
	if len(runs) == 0 {
		return ""
	}
	failed, last := len(runs)-len(merged), 0
	for _, round := range merged {
		last = max(last, round)
	}
	switch {
	case held < last:
		later := count(func(round int) bool { return round > held })
		said := fmt.Sprintf("The %d change%s that merged after round %d would have gone back to their orchestrator instead",
			later, plural(later), held)
		if failed > 0 {
			said += fmt.Sprintf(", and the %d that failed would have gone back after round %d", failed, held)
		}
		return said + "."
	case held == last:
		return fmt.Sprintf("%d change%s (%d%%) went back to their orchestrator after %d round%s.",
			failed, plural(failed), percent(failed, len(runs)), held, plural(held))
	case held == last+1 && last > 0 && failed > 0:
		kept := count(func(round int) bool { return round == last })
		return fmt.Sprintf("If a %s round went like the %s, where %d%% merged, about %d of those %d would have merged. "+
			"No run has had one, so this is a guess.", nth(held), nth(last), percent(kept, kept+failed),
			int(math.RoundToEven(float64(failed*kept)/float64(kept+failed))), failed)
	}
	return fmt.Sprintf("No run has gone past %d round%s, so your runs can't say.", last, plural(last))
}

// LinesSaid is what a line limit's changes would have done at held lines, runs the ones its
// SizeChart draws (history.FirstReviewSizes), own for orchestrators' own pull requests under
// `orchestrator_lines` (executorsOff when `executor_lines` is 0, so own pull requests over the
// limit are split rather than made tasks), Python's menu.lines_said: those of more than held
// lines, as the first review's gates refuse them, split, for builds or with executors off, or
// made tasks, for own pull requests -- the owner's design of 5 Nov 2026 -- and how often their
// first review passed, or round 1 merged them, beside the rest; off, or past the largest, what
// they can't say.  "" with none, unless off.
func LinesSaid(runs []history.Row, held any, own, executorsOff bool) string {
	if held == 0 {
		switch {
		case !own:
			return "Off: executors build nothing, so your runs can't say how that would go."
		case len(runs) > 0:
			return fmt.Sprintf("Off: orchestrators build nothing themselves, so every one of their %d own pull request%s would have been a task.",
				len(runs), plural(len(runs)))
		}
		return "Off: orchestrators build nothing themselves."
	}
	if len(runs) == 0 {
		return ""
	}
	// at "no limit" none is over
	limit, limited := held.(int)
	var over, under struct{ passed, runs int }
	largest := runs[0]
	for _, run := range runs {
		lines, _ := run.Num("lines")
		passed, _ := run.Num("passed")
		side := &under
		if limited && lines > float64(limit) {
			side = &over
		}
		side.passed, side.runs = side.passed+int(passed), side.runs+1
		if most, _ := largest.Num("lines"); lines > most {
			largest = run
		}
	}
	if over.runs == 0 {
		noun := "build"
		if own {
			noun = "own pull request"
		}
		return fmt.Sprintf("Your largest %s was %v lines, so your runs can't say how bigger ones would go.", noun, largest["lines"])
	}
	were, rest := "were", ""
	if over.runs == 1 {
		were = "was"
	}
	if under.runs > 0 {
		rest = fmt.Sprintf(", and %d%% at %d lines or fewer", percent(under.passed, under.runs), limit)
	}
	if own {
		fate := "tasks"
		switch {
		case executorsOff:
			fate = "split"
		case over.runs == 1:
			fate = "a task"
		}
		return fmt.Sprintf("%d of your orchestrators' %d own pull requests %s more than %d lines and would have been %s. Round 1 merged %d%% of them%s.",
			over.runs, len(runs), were, limit, fate, percent(over.passed, over.runs), rest)
	}
	return fmt.Sprintf("%d of your %d builds (%d%%) %s more than %d lines and would have been split. Their first review passed %d%% of the time%s.",
		over.runs, len(runs), percent(over.runs, len(runs)), were, limit, percent(over.passed, over.runs), rest)
}

// percent is part of whole as a whole percent, rounded half to even as Python's round is.
func percent(part, whole int) int {
	return int(math.RoundToEven(float64(100*part) / float64(whole)))
}

// plural is the s a count other than 1 takes.
func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// nth is n as an ordinal: 1st, 2nd, 3rd, 4th, 11th, 21st.
func nth(n int) string {
	if suffix, ok := map[int]string{1: "st", 2: "nd", 3: "rd"}[n%10]; ok && n%100/10 != 1 {
		return fmt.Sprint(n, suffix)
	}
	return fmt.Sprint(n, "th")
}
