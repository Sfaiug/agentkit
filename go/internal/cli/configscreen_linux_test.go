package cli

import (
	"os/exec"
	"path/filepath"
	"testing"
)

func TestConfigMatrixKeepsConcurrentRolesAndConnectedServices(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	binary := filepath.Join(t.TempDir(), "ak")
	build := exec.Command("go", "build", "-mod=vendor", "-o", binary, "./cmd/ak")
	build.Dir = filepath.Join("..", "..")
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v\n%s", err, out)
	}
	call := exec.Command("python3", "-B", "-c", `
import fcntl, json, os, sys
from pathlib import Path
os.environ["AK_BIN"] = sys.argv[1]
sys.path.insert(0, str(Path("tests").resolve()))
from fixtures.akbin import Home
from fixtures import akconfig, fakeadapter
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

for feature in ("roles", "mark_on", "mark_off", "discord", "cloud"):
    with Home() as home:
        extra = "[google_cloud]\nactive = true\n" if feature == "cloud" else ""
        akconfig.write(home, {"fable": "claude", "astra": {"harness": "codex", "effort": "high"}},
                       workers=["astra"], extra=extra)
        fakeadapter.install(home, claude="pass", codex="pass")
        workers = ["astra", "fable"] if feature == "mark_off" else ["astra"]
        Seat(home, "acme", model="fable", record={"workers": workers, "reviewers": ["astra"]})
        if feature == "discord":
            home.write(".agentkit/secrets/discord_webhook", "https://example.com/acme-webhook")
        term = Terminal(home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": "acme"})
        term.wait("esc leave", bound=10)
        term.keys("c")
        shown = term.wait(lambda s: "For  acme" in s and "[●]" in s, bound=10)
        if feature == "discord":
            assert "webhook …ebhook" in shown, shown
            assert "https://example.com/acme-webhook" not in shown, shown
        if feature == "cloud":
            assert "Google Cloud on · spend unknown" in shown, shown
        term.keys("Right", "Right")
        term.wait("[■]" if feature == "mark_off" else "[□]", bound=10)
        record = home.path / ".agentkit/state/session-acme.json"
        concurrent = feature in ("roles", "mark_on", "mark_off")
        if concurrent:
            with record.with_name(".session-acme.lock").open("a") as held:
                fcntl.flock(held, fcntl.LOCK_EX)
                changed = json.loads(record.read_text())
                changed["reviewers"] = ["fable"]
                if feature != "roles":
                    changed["workers"] = ["astra", "fable"] if feature == "mark_on" else ["astra"]
                swap = record.with_suffix(".probe")
                swap.write_text(json.dumps(changed))
                swap.replace(record)
        term.keys("Space")
        term.wait("[□]" if feature == "mark_off" else "[■]", bound=10)
        saved = json.loads(record.read_text())
        assert saved["workers"] == (["astra"] if feature == "mark_off" else ["astra", "fable"]), (feature, saved)
        assert saved["reviewers"] == (["fable"] if concurrent else ["astra"]), (feature, saved)
        term.keys("Escape")
        term.wait("esc leave", bound=10)
        term.keys("Escape")
        assert term.exit_code() == 0
`, binary)
	call.Dir = filepath.Join("..", "..", "..")
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("config matrix: %v\n%s", err, out)
	}
}
