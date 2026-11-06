package adapters

import (
	"cmp"
	"fmt"
	"os"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	record "agentkit/internal/run"
)

// statusLine puts in a seat's call the `{pins}` its line runs on where its harness reads the
// owner's status command from settings files (harness.StatusFiles): the manifest's, with a status
// line of ak's, `ak hook status`, which writes down what each render says the seat runs on and
// hands the render on to the owner's command, the first those files name, run verbatim, a
// trailing comment or heredoc included.  They are read as the login's harness reads them, in the
// seat's folder.  A turn runs on the manifest's pins alone.
func statusLine(name, root string, login config.Login, call map[string][]string) error {
	files := harness.StatusFiles(name)
	if files == nil {
		return nil
	}
	launch, err := config.Section(name, "launch")
	pins, _ := launch["pins"].(string)
	read, _ := record.Decode([]byte(cmp.Or(pins, "{}")))
	settings, _ := read.(*record.Object)
	if err != nil || settings == nil {
		return cmp.Or(err, fmt.Errorf("adapter manifest %s.toml: [launch] pins is no JSON object", name))
	}
	ak := harness.StatusCommand(root)
	line := record.Fields("type", "command", "command", ak+" >/dev/null")
	env := map[string]string{}
	for _, pair := range login.Environ(os.Environ()) {
		key, value, _ := strings.Cut(pair, "=")
		env[key] = value
	}
	cwd, _ := os.Getwd()
	for _, path := range config.ManifestPaths(files, env, cwd) {
		data, _ := os.ReadFile(path)
		read, _ := record.Decode(data)
		var owner *record.Object
		if file, _ := read.(*record.Object); file != nil {
			owner = file.Dict("statusLine")
		}
		if owner != nil && owner.Str("command") != "" {
			line = owner.Copy()
			line.Set("command", ak+" | { "+owner.Str("command")+"\n}")
			break
		}
	}
	settings.Set("statusLine", line)
	call["pins"] = []string{record.Line(settings)}
	return nil
}
