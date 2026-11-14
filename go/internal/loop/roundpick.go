package loop

import "agentkit/internal/pick"

// roundRules is what a pick within a round reads, Python's off the loop's lp.cfg
// (config.at_efforts): the run's rules, each model at the efforts the run launched with (model).
// A launch's pick, a resume's and a pull request's reviewer read the config as it stands, as
// Python's run.loop, resume_models and review_pr_round read config.load.
func (l *loop) roundRules() (*pick.Rules, bool) {
	rules, ok := l.rules()
	if !ok {
		return nil, false
	}
	return rules.At(l.model)
}
