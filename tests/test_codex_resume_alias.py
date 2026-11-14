"""Resuming through the same transcript's resolved path preserves the owned conversation."""
import json
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config
from agentkit.harness import codex


class CodexResumeAlias(Sandbox):
    def test_resume_accepts_the_same_file_but_rejects_another_transcript(self):
        original = self.root / 'rollout.jsonl'
        original.write_text(json.dumps({'type': 'session_meta', 'payload': {
            'id': 'acme-thread', 'cwd': str(self.root)}}) + '\n')
        linked = self.root / 'linked.jsonl'
        linked.symlink_to(original)
        config.save_session(self.cfg, 'acme', 'astra', ['astra'], {'cwd': str(self.root)})
        receipt = codex.prepare('acme', self.root, None)
        event = {'hook_event_name': 'SessionStart', 'session_id': 'acme-thread',
                 'transcript_path': str(linked), 'cwd': str(self.root), 'source': 'startup'}
        codex.capture(receipt, event)
        codex.capture(receipt, dict(event, source='compact'))
        self.assertEqual(codex.conversation(config.session_records()['acme']), 'acme-thread')
        receipt = codex.prepare('acme', self.root, 'acme-thread')
        codex.capture(receipt, dict(event, transcript_path=str(original), source='resume'))
        linked.unlink()
        record = config.session_records()['acme']
        self.assertEqual(codex.conversation(record), 'acme-thread')
        codex.capture(receipt, dict(event, transcript_path=str(original), source='compact'))
        self.assertEqual(codex.conversation(record), 'acme-thread')
        other = self.root / 'another.jsonl'
        other.write_text(original.read_text())
        codex.capture(receipt, dict(event, transcript_path=str(other), source='resume'))
        # neither read nor marking the receipt: only the seat's own Codex moves it (`follow`)
        read = codex.conversation(record), codex.transcript(record, self.root, 'acme-thread')
        self.assertEqual(read, ('acme-thread', str(original.resolve())))


if __name__ == '__main__':
    unittest.main()
