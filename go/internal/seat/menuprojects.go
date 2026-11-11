package seat

import (
	"context"
	"path/filepath"
	"sync"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// menuProjects files old records before reading their order: first session_projects' missing
// repo, then file_projectless' run votes, and says whether it wrote. The typing lock keeps a
// snapshot from undoing a launch.
func menuProjects(runs, projects map[string][]ran) (wrote, known bool) {
	state, stands := filepath.Join(config.Home(), "state"), sync.OnceValue(listed)
	for _, path := range config.SeatFiles() {
		record, err := run.Shared(path)
		if err != nil || record == nil || record.Has(config.Renamed) {
			continue
		}
		if record.Has("repo") && (record.Truthy("repo") || record.Truthy("filed")) {
			continue
		}
		name, _ := sessionFile(filepath.Base(path))
		repo := record.Get("repo")
		if !record.Has("repo") {
			repo = vote(projects[name]) // session_projects counts unattended runs too
		}
		if filed, _ := repo.(string); filed == "" && !record.Truthy("filed") {
			var votes []ran
			for _, each := range runs[name] {
				project, known := runProject(each.record)
				if !known {
					return wrote, false
				}
				if checkout := checkoutOf(project, stands); checkout != "" {
					votes = append(votes, ran{record: run.Fields("repo", checkout)})
				}
			}
			if chosen := vote(votes); chosen != nil {
				repo = chosen
			}
		}
		if record.Has("repo") && run.Equal(repo, record.Get("repo")) {
			continue
		}
		wrote = true
		if err := notify.Held(context.Background(), name, func(current string) error {
			return update(state, current, func(data *run.Object) bool {
				if data.Has("repo") && (data.Truthy("repo") || data.Truthy("filed")) {
					return false
				}
				return set([]field{{"repo", repo}})(data)
			})
		}); err != nil {
			return wrote, false
		}
	}
	return wrote, true
}
