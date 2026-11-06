package gitcall

import (
	"crypto/sha256"
	"encoding/hex"
	"path/filepath"
	"regexp"

	"agentkit/internal/config"
)

// told is the name a check's clone was given of the repository it came from.
var told = regexp.MustCompile(`^[0-9a-f]{12}$`)

// RepositoryID is the short name this host and a machine keep a repository's records under,
// Python's gitcall.repository_id: the one a check's clone was told (`ak.repository`), else its
// main checkout's, ak's own being ~/agentkit whatever version of it this checks.
func RepositoryID(cwd string) string {
	g := Git{Repo: cwd}
	if code, name, err := g.Out("config", "--local", "--get", "ak.repository"); err == nil && code == 0 && told.MatchString(name) {
		return name
	}
	main := cwd
	if code, common, err := g.Out("rev-parse", "--git-common-dir"); err == nil && code == 0 && common != "" {
		if !filepath.IsAbs(common) {
			common = filepath.Join(cwd, common)
		}
		common = config.Resolve(common)
		main = filepath.Dir(common)
		if common == config.Resolve(filepath.Join(config.Home(), "agentkit.git")) {
			main = filepath.Join(config.UserHome(), "agentkit")
		}
	}
	sum := sha256.Sum256([]byte(main))
	return hex.EncodeToString(sum[:6])
}
