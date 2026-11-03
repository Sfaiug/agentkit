package transcript

import "os"

// WrappedUp is whether the conversation at path, the named harness's, ended its latest turn for a
// spent subscription with no prompt since (claude.py `wrapped_up`): its harness told the model to
// wrap up, a dated `usageLimitNote` of its own, so the turn stopped with nothing refused.
func WrappedUp(name, path string) bool {
	file, err := os.Open(path)
	if err != nil {
		return false
	}
	defer file.Close()
	for entry := range newest(file) {
		if entry.Get("usageLimitNote") == "wrap_up" {
			return moment(entry.Get("timestamp")) != 0
		}
		if Prompted(name, entry).Text != "" {
			return false
		}
	}
	return false
}
