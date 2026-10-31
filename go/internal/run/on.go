package run

import "errors"

// PRNumber is the number of the pull request a URL names, "" for no pull request URL.
func PRNumber(url string) string {
	if found := pullRequest.FindStringSubmatch(url); found != nil {
		return found[3]
	}
	return ""
}

// OnPR is the records of the runs on that pull request, however its URL was spelled, as
// transitions.runs_on reads them: a task run keeps its own in `pr`, a review in `review_pr`.
// A record Go cannot read as Python does is ErrLoneSurrogate.
func OnPR(url string) ([]*Object, error) {
	wanted, on := prKey(url), []*Object(nil)
	for _, dir := range Dirs() {
		record, err := Read(dir)
		if errors.Is(err, ErrLoneSurrogate) {
			return nil, err
		}
		if record != nil && wanted != "" && (prKey(record.Get("pr")) == wanted || prKey(record.Get("review_pr")) == wanted) {
			on = append(on, record)
		}
	}
	return on, nil
}
