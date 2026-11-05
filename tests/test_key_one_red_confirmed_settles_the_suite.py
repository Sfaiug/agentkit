"""One helper red failing again alone settles the suite; later reds keep their helper output.

Black-box: AK_BIN checks a Line whose four helper pieces name different failed tests. Named
reruns and the tip probe leave their test names in Git storage, and history records their outcomes.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akline import Line, RUNNER
from test_key_history_db import read
from test_key_landing_and_health_leave_rows import started

SSH = f"""#!{sys.executable}
import shlex, sys
words = shlex.split(sys.argv[-1])
verb = words.index('mac.sh') + 1
if words[verb] == 'probe':
    print('cpus 4\\nload 0\\nroom_mb 65536')
elif words[verb] == 'prepare':
    sys.stdin.buffer.read()
elif words[verb] == 'run':
    print('HELPER RED ' + words[verb + 7])
    sys.exit(1)
elif words[verb] == 'failed' and words[-1] == 'failed':
    k = int(words[-2].rsplit('-', 2)[-2])
    print(chr(96 + k) + '.sh')
"""
NAMES = ['a.sh', 'b.sh', 'c.sh', 'd.sh']
RUNNER = ('if [ -n "${AK_ONLY:-}" ]; then\n'
          '  cat "$AK_ONLY" >>"$(git rev-parse --git-common-dir)/alone.log"\n'
          'fi\n' + RUNNER)


class OneRedConfirmedSettlesTheSuite(unittest.TestCase):
    def land(self, reds, whole_red=False):
        tests = {f't/{name}': ('test ! -f api.txt\n' if name in reds else 'true\n')
                 for name in NAMES}
        if whole_red:
            tests['t/a.sh'] = 'test -n "${AK_ONLY:-}" || test ! -f api.txt\n'
        line = Line({**tests, 'suite.sh': RUNNER,
                     'tools/helper/Containerfile': 'FROM acme/base\n'})
        self.addCleanup(line.close)
        akconfig.write(line.home, ['opus', 'astra'], settings={'suite_helper': 'acme-mac'})
        line.home.fake('ssh', SSH)
        started(line.home, 'fix-1')
        line.member({'api.txt': 'x\n'})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        return line, (line.rig.path / '.git/alone.log').read_text().splitlines()

    def outcomes(self, line):
        rows = read(line.home, "SELECT test, flaky FROM test_reds WHERE kind='landing'")
        return sorted((row['test'], row['flaky']) for row in rows)

    def test_one_repeat_failure_leaves_every_other_helper_red_untouched(self):
        line, alone = self.land(NAMES)
        self.assertEqual(alone, ['a.sh', 'a.sh'])  # stack confirmation, then tip probe
        red = line.verdict(1)['fix']
        self.assertEqual((red['piece'], red['tests']), ('1/4', ['a.sh']))
        self.assertEqual(self.outcomes(line), [('a.sh', 0)])
        text = Path(red['log']).read_text()
        for k in (2, 3, 4):
            self.assertIn(f'--- AK_SHARD={k}/4 ---\n[exit 1]\nHELPER RED {k}/4', text)

    def test_flakes_advance_until_a_repeat_failure_and_blame_that_confirmed_piece(self):
        line, alone = self.land(NAMES[1:], whole_red=True)
        self.assertEqual(alone, ['a.sh', 'b.sh', 'b.sh'])
        red = line.verdict(1)['fix']
        self.assertEqual((red['piece'], red['tests']), ('2/4', ['b.sh']))
        self.assertEqual(self.outcomes(line), [('a.sh', 1), ('b.sh', 0)])

    def test_all_named_flakes_still_run_their_whole_pieces_and_can_land(self):
        line, alone = self.land([])
        self.assertEqual(alone, NAMES)
        self.assertIn('land', line.verdict(1))
        self.assertEqual(sorted(line.runs()), [('alone', '')] * 4
                         + [('piece', f'{k}/4', '') for k in (1, 2, 3, 4)])
        self.assertEqual(self.outcomes(line), [(name, 1) for name in NAMES])


if __name__ == '__main__':
    unittest.main()
