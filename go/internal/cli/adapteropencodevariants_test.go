package cli

import (
	"bytes"
	"testing"
)

// `ak adapter <root> opencode variants` answers as adapters/opencode.sh does: a named account
// refused before anything else, a missing model its usage line, else the document.
func TestOpenCodeVariantsAnswersAsItsScript(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	for _, each := range []struct {
		account     string
		args        []string
		code        int
		said, wrote string
	}{
		{"second", nil, 1, "", "opencode: account second refused; OpenCode keeps logins and sessions in one opencode.db, so a login of its own cannot resume a conversation\n"},
		{"", nil, 2, "", "opencode.sh variants needs <model>\n"},
		{"", []string{"acme/m#high", "more"}, 0, `{"provider":{"acme":{"models":{"m":{"variants":{"none":{}}}}}}}` + "\n", ""},
	} {
		t.Setenv("AGENTKIT_ACCOUNT", each.account)
		var out, errOut bytes.Buffer
		code := adapter(append([]string{t.TempDir(), "opencode", "variants"}, each.args...), &out, &errOut)
		if code != each.code || out.String() != each.said || errOut.String() != each.wrote {
			t.Errorf("%q %q: %d %q %q", each.account, each.args, code, out.String(), errOut.String())
		}
	}
}
