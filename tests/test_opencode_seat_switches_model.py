"""The seat plugin's `/ak-model <provider/model[#variant]> <effort>` switches the session it is
typed in to that model at the id's own variant, else the effort, as OpenCode 2.2.4's
`session.switchModel` takes it; any other text, or a refusal, changes nothing and says nothing.
Offline: the real plugin under Node, handed a fake `ctx`, as tests/test_opencode_title.py."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
DRIVER = r'''
import { pathToFileURL } from "node:url";
const plugin = (await import(pathToFileURL(process.argv[1]).href)).default;
const [texts, refuse] = [JSON.parse(process.argv[2]), process.argv[3] === "refuse"];
const commands = [], switched = [];
const ctx = {
  tool: { hook: () => null },
  command: { transform: (edit) => edit({ add: (command) => commands.push(command) }) },
  session: { switchModel: async (call) => {
    switched.push(call);
    if (refuse) throw new Error("refused");
  } },
  event: { subscribe: async function* () {} },
};
const stop = await plugin.setup(ctx);
await new Promise((resolve) => setTimeout(resolve, 50));
const [command] = commands;
for (const text of texts) {
  await command.execute({ sessionID: "ses_acme", prompt: { text, files: [], agents: [] },
                          delivery: "steer" });
}
stop();
console.log(JSON.stringify({ names: commands.map((each) => each.name), switched }));
'''


@unittest.skipUnless(NODE, "no node installed")
class OpencodeSeatSwitchesModel(unittest.TestCase):
    def drive(self, *texts, refuse=False):
        proc = subprocess.run(
            [NODE, "--input-type=module", "-e", DRIVER, str(REPO / "hooks/opencode-seat/index.js"),
             json.dumps(texts), "refuse" if refuse else ""],
            text=True, capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout.splitlines()[-1])
        self.assertEqual(out["names"], ["ak-model"])
        return [(call["sessionID"], call["model"]) for call in out["switched"]]

    def test_the_model_and_effort_move_the_session_it_is_typed_in(self):
        self.assertEqual(self.drive("opencode/glm-5.3-flash-free high",
                                    " mimo/mimo-v2.6-pro#none high ",
                                    "openrouter/acme/flash max"), [
            ("ses_acme", {"providerID": "opencode", "id": "glm-5.3-flash-free", "variant": "high"}),
            ("ses_acme", {"providerID": "mimo", "id": "mimo-v2.6-pro", "variant": "none"}),
            ("ses_acme", {"providerID": "openrouter", "id": "acme/flash", "variant": "max"})])

    def test_any_other_text_switches_nothing(self):
        self.assertEqual(self.drive("", "glm-5.3-flash-free high", "opencode/glm-5.3-flash-free",
                                    "opencode/glm-5.3-flash-free high now"), [])

    def test_a_refused_switch_says_nothing(self):
        self.assertEqual(len(self.drive("opencode/glm-5.3-flash-free high", refuse=True)), 1)


if __name__ == "__main__":
    unittest.main()
