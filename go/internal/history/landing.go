package history

import (
	"cmp"
	"os"

	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// landingCounts is how history_ending counts a merged run's landing reds (landing_red_patches), as
// column, value pairs: a red whose patch the merge kept unchanged is a flake, every other a break,
// as is one whose patch git could not say.  None for a run that did not merge or saw none: its row
// keeps the none it started with.
func landingCounts(record *run.Object) []any {
	reds := record.List("landing_red_patches")
	if !record.Truthy("merged") || len(reds) == 0 {
		return nil
	}
	repo := record.Str("repo")
	if worktree := record.Str("worktree"); worktree != "" {
		if info, err := os.Stat(worktree); err == nil && info.IsDir() {
			repo = worktree
		}
	}
	head := cmp.Or(record.Str("delivery_sha"), cmp.Or(record.Dict("review"), run.NewObject()).Str("head_sha"))
	patch := ""
	if base := record.Str("base_sha"); repo != "" && head != "" && base != "" {
		patch, _ = gitcall.Git{Repo: repo}.PatchID(base, head) // a git that stopped proves no flake
	}
	flakes := 0
	for _, red := range reds {
		if id, _ := red.(string); id != "" && id == patch {
			flakes++
		}
	}
	return []any{"landing_breaks", len(reds) - flakes, "landing_flakes", flakes}
}
