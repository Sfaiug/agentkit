"""Codex's real async card protocol keeps each question until its own owner reply.

The item shapes were captured from the 0.163 TUI: selecting a card submits a UserMessage
with questionItemId; accepted, turn completion and the disappearing card are not answers.
"""
import json
import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, notify, orch, questions, watch
from agentkit.harness import codex

SEAT = 'acme-card'
ASKS = [{'title': 'Which colour should acme use?', 'options': ['Blue', 'Green']},
        {'title': 'Which shape should acme use?', 'options': ['Round', 'Square']}]
TEXTS = [codex.question_line(q) for q in ASKS]
CALL = {'hook_event_name': 'PreToolUse', 'tool_name': 'request_user_input_async',
        'tool_use_id': 'call-acme', 'tool_input': {'questions': ASKS}}


class CodexQuestionCards(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, 'astra', ['astra'], {'cwd': str(self.root)})
        self.stack.enter_context(patch.dict(os.environ, {'AGENTKIT_SESSION': SEAT,
                               'AK_RUN_ROLE': '', 'AK_NOTIFY_SINK': 'off',
                               'AGENTKIT_DISCORD_WEBHOOK': 'off'}))
        self.stack.enter_context(patch.object(orch, 'tmux_out', return_value=(0, '')))
        self.path = self.root / 'rollout.jsonl'
        self.path.touch()
        self.stack.enter_context(patch.object(codex, 'transcript', return_value=str(self.path)))
        self.stack.enter_context(patch.object(notify, 'conversation_of', return_value=(
            orch.harness_plugin('codex'), {}, str(self.root), 'acme-thread')))
        self.add('response_item', {'type': 'function_call', 'name': 'request_user_input_async',
                                  'call_id': 'call-acme', 'arguments': json.dumps(CALL['tool_input'])}, 9999)

    def add(self, kind, payload, at=10001):
        with self.path.open('a') as stream:
            stream.write(json.dumps({'timestamp': at, 'type': kind, 'payload': payload}) + '\n')

    def ask(self):
        self.assertIsNone(codex.ask(CALL), 'the native question cards must be allowed')
        self.assertEqual(questions.pending(SEAT), TEXTS)

    def reply(self, index, at=10001, call='call-acme', answer='Blue'):
        text = '<send_user_message_question_reply>\n' + json.dumps([{
            'answer': answer, 'question': ASKS[index]['title'],
            'questionItemId': json.dumps(['request_user_input_async', call, index])
        }]) + '\n</send_user_message_question_reply>'
        self.add('event_msg', {'type': 'item_completed', 'item': {
            'type': 'UserMessage', 'content': [{'type': 'text', 'text': text}]}}, at)

    def stopped(self):
        watch.turn_ended(SEAT)
        with notify.session_lock(SEAT):
            notify.ask_kept(SEAT)

    def repeat(self):
        repeated = dict(CALL, tool_use_id='call-new', tool_input={'questions': ASKS[:1]})
        with patch.object(notify.time, 'time', return_value=10003):
            self.assertIsNone(codex.ask(repeated))
        self.add('response_item', {'type': 'function_call', 'name': 'request_user_input_async',
                 'call_id': 'call-new', 'arguments': json.dumps(repeated['tool_input'])}, 10003)

    def test_native_cards_are_allowed_and_each_question_survives_acceptance_and_stop(self):
        self.ask()
        self.add('response_item', {'type': 'function_call_output', 'call_id': 'call-acme',
                                  'output': '{"accepted":true}'})
        self.add('event_msg', {'type': 'task_complete', 'last_agent_message': ''})
        self.assertFalse(notify.answer_written(SEAT))
        self.stopped()
        self.assertEqual(questions.pending(SEAT), TEXTS)
        self.assertFalse(notify.answer_written(SEAT))
        self.assertEqual(questions.pending(SEAT), TEXTS)

    def test_a_card_answer_during_independent_work_resolves_only_that_question(self):
        self.ask()
        self.reply(0)
        self.assertTrue(notify.answer_written(SEAT))
        self.assertEqual(questions.pending(SEAT), TEXTS[1:])
        self.assertIsNone(notify.last(SEAT))
        self.stopped()
        self.assertEqual(questions.pending(SEAT), TEXTS[1:])
        self.assertFalse(notify.answer_written(SEAT))

    def test_a_card_answer_read_after_the_stop_or_reopen_resolves_only_its_question(self):
        self.ask()
        self.reply(0, at=10001)
        with patch.object(notify.time, 'time', return_value=10002):
            self.stopped()
        self.assertTrue(notify.answer_written(SEAT, at=10003))
        self.assertEqual(questions.pending(SEAT), TEXTS[1:])
        self.reply(1, at=10004, answer='Round')
        self.assertTrue(notify.answer_written(SEAT, at=10005))
        self.assertEqual(questions.pending(SEAT), [])

    def test_an_old_reply_does_not_answer_the_same_question_asked_again(self):
        self.ask()
        self.reply(0)
        self.assertTrue(notify.answer_written(SEAT))
        with patch.object(notify.time, 'time', return_value=10003):
            self.assertIsNone(codex.ask(CALL))
        self.assertFalse(notify.answer_written(SEAT))
        self.assertEqual(set(questions.pending(SEAT)), set(TEXTS))

    def test_a_late_reply_answers_only_its_original_card_before_and_after_stop(self):
        self.ask()
        self.repeat()
        self.reply(0, at=10004)
        self.assertTrue(notify.answer_written(SEAT, at=10005))
        self.assertEqual(set(questions.pending(SEAT)), set(TEXTS))
        with patch.object(notify.time, 'time', return_value=10006):
            self.stopped()
        self.assertFalse(notify.answer_written(SEAT, at=10007))
        self.assertEqual(set(questions.pending(SEAT)), set(TEXTS))
        self.reply(0, at=10008, call='call-new')
        self.assertTrue(notify.answer_written(SEAT, at=10009))
        self.assertEqual(questions.pending(SEAT), TEXTS[1:])

    def test_a_late_reply_does_not_answer_a_repeated_standing_question(self):
        self.ask()
        self.stopped()
        self.repeat()
        self.reply(0, at=10004)
        self.assertFalse(notify.answer_written(SEAT, at=10005))
        self.assertEqual(questions.pending(SEAT), TEXTS)
        self.reply(0, at=10006, call='call-new')
        self.assertTrue(notify.answer_written(SEAT, at=10007))
        self.assertEqual(questions.pending(SEAT), TEXTS[1:])

    def test_a_reply_on_the_latest_card_answers_every_copy_kept_before_it(self):
        self.ask()
        self.stopped()
        self.repeat()
        latest = dict(CALL, tool_use_id='call-last', tool_input={'questions': ASKS[:1]})
        with patch.object(notify.time, 'time', return_value=10004):
            self.assertIsNone(codex.ask(latest))
        self.add('response_item', {'type': 'function_call', 'name': 'request_user_input_async',
                 'call_id': 'call-last', 'arguments': json.dumps(latest['tool_input'])}, 10004)
        self.reply(0, at=10005, call='call-last')
        self.assertTrue(notify.answer_written(SEAT, at=10006))
        self.stopped()
        self.assertEqual(questions.pending(SEAT), TEXTS[1:])

    def test_stop_does_not_replace_a_new_cards_identity_with_an_older_kept_one(self):
        self.ask()
        with notify.session_lock(SEAT):
            notify._said(SEAT, 'needs', 'Ship the sample?', at=10002)
        self.repeat()
        with patch.object(notify.time, 'time', return_value=10005):
            self.stopped()
        self.reply(0, at=10004)
        self.assertFalse(notify.answer_written(SEAT, at=10006))
        self.assertIn(TEXTS[0], questions.pending(SEAT))
        self.reply(0, at=10007, call='call-new')
        self.assertTrue(notify.answer_written(SEAT, at=10008))
        self.assertNotIn(TEXTS[0], questions.pending(SEAT))

    def test_a_later_question_does_not_hide_an_earlier_questions_native_answer(self):
        self.ask()
        self.stopped()
        with notify.session_lock(SEAT):
            notify._said(SEAT, 'needs', 'Ship the sample?', at=10005)
        self.reply(0, at=10001)
        self.assertTrue(notify.answer_written(SEAT, at=10006))
        self.assertEqual(questions.pending(SEAT), [TEXTS[1], 'Ship the sample?'])

    def test_expired_unknown_empty_or_malformed_replies_answer_nothing(self):
        self.ask()
        self.reply(0, call='expired-call')
        self.reply(1, answer='')
        self.add('event_msg', {'type': 'item_completed', 'item': {'type': 'UserMessage',
                 'content': [{'type': 'text', 'text': '<send_user_message_question_reply>bad'}]}})
        self.stopped()
        self.assertFalse(notify.answer_written(SEAT))
        self.assertEqual(questions.pending(SEAT), TEXTS)

    def test_an_unclosed_reply_answers_nothing(self):
        self.ask()
        self.reply(0)
        self.path.write_text(self.path.read_text().replace(
            '</send_user_message_question_reply>', ''))
        self.assertFalse(notify.answer_written(SEAT))
        self.assertEqual(questions.pending(SEAT), TEXTS)

    def test_a_bad_reply_does_not_hide_another_cards_valid_answer(self):
        self.ask()
        text = '<send_user_message_question_reply>\n' + json.dumps([
            {'questionItemId': 'bad', 'answer': 'Blue'},
            {'questionItemId': json.dumps(['request_user_input_async', 'call-acme', 1]),
             'answer': 'Round'},
        ]) + '\n</send_user_message_question_reply>'
        self.add('event_msg', {'type': 'item_completed', 'item': {'type': 'UserMessage',
                 'content': [{'type': 'text', 'text': text}]}})
        self.assertTrue(notify.answer_written(SEAT))
        self.assertEqual(questions.pending(SEAT), TEXTS[:1])


if __name__ == '__main__':
    unittest.main()
