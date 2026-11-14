package harness

import "errors"

// antigravityNamed is antigravityOwned, only asked: none only for a record naming none and no
// launch.  A launch /proc shows holding none, or two, is the error, as /proc may not show its agy,
// and a conversation its hook followed is Python's.
func antigravityNamed(record map[string]any) (string, error) {
	if record["id_source"] == "antigravity-hook" {
		return "", errors.New("Go leaves a conversation an Antigravity hook followed to Python")
	}
	if conversation := antigravityLearn(antigravityEvidence(record), false); conversation != "" {
		return conversation, nil
	}
	if _, launched := record["antigravity_launch"].(string); launched {
		return "", errors.New("Go cannot tell which conversation an Antigravity launch holds open")
	}
	return "", nil
}
