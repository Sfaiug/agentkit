package cli

import "agentkit/internal/seat"

func recordedEnding(name string, record map[string]any, asked bool, since float64) (ends, parked bool, err error) {
	return seat.RecordedEnding(name, nil, record, asked, since)
}
