package harness

import "os"

// grokOpened is whether Grok Build has written the conversation a seat's record names down yet
// (grokbuild.py `opened`): its session's folder is there, a link followed.  One that is resumes;
// one that is not opens fresh under the same id, as `--session-id` asks: an id not there yet.
func grokOpened(record map[string]any) bool {
	cwd, _ := record["cwd"].(string)
	conversation, _ := record["conversation"].(string)
	info, err := os.Stat(grokSession(cwd, conversation))
	return err == nil && info.IsDir()
}
