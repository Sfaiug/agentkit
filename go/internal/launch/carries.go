package launch

import "agentkit/internal/run"

// Carries is whether Go's resume takes up that run rather than leave it to Python, read before a
// caller writes the decision the resume is to adopt, so a run Go does not carry is handed over
// as it stood.  A refusal is the resume's own to say.
func Carries(dir string, record *run.Object) bool {
	return reached(record) && goesOn(dir, record)
}
