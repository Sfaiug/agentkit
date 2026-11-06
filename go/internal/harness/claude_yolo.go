package harness

import (
	"cmp"
	"fmt"
	"io"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// claudeYolo has Claude bypass its permission prompts, unwarned, and never update itself: `ak
// update` is the only way a harness moves, as an update mid-run would change the thing under
// test between one round and the next, and nothing would say so.  The file is backed up first.
func claudeYolo(out io.Writer) error {
	path := filepath.Join(config.UserHome(), ".claude", "settings.json")
	text, found, err := settings(path)
	if err != nil {
		return err
	}
	data := run.NewObject()
	if found {
		value, err := run.DecodeLimited([]byte(text))
		if err != nil {
			// a malformed file is not a missing one: replacing it would drop the owner's settings
			return fmt.Errorf("%s is not valid JSON (%v)", path, err)
		}
		var object bool
		if data, object = value.(*run.Object); !object {
			return fmt.Errorf("%s is not a JSON object", path)
		}
	}
	perms, env := cmp.Or(data.Dict("permissions"), run.NewObject()), cmp.Or(data.Dict("env"), run.NewObject())
	if perms.Get("defaultMode") == "bypassPermissions" && data.Get("skipDangerousModePermissionPrompt") == true &&
		env.Get("DISABLE_AUTOUPDATER") == "1" {
		fmt.Fprintf(out, "yolo: %s already bypassPermissions, autoupdater pinned\n", path)
		return nil
	}
	if found {
		backup, err := config.BackUp(path)
		if err != nil {
			return err
		}
		fmt.Fprintf(out, "backed up %s -> %s\n", path, backup)
	}
	perms.Set("defaultMode", "bypassPermissions")
	data.Set("permissions", perms)
	data.Set("skipDangerousModePermissionPrompt", true)
	env.Set("DISABLE_AUTOUPDATER", "1")
	data.Set("env", env)
	if err := writeConfig(path, run.Encode(data)+"\n"); err != nil {
		return err
	}
	fmt.Fprintf(out, "yolo: %s permissions.defaultMode=bypassPermissions, skipDangerousModePermissionPrompt=true, env.DISABLE_AUTOUPDATER=1\n", path)
	return nil
}
