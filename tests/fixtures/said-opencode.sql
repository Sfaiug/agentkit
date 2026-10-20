CREATE TABLE `session_message` (
          `id` text PRIMARY KEY,
          `session_id` text NOT NULL,
          `type` text NOT NULL,
          `seq` integer NOT NULL,
          `time_created` integer NOT NULL,
          `time_updated` integer NOT NULL,
          `data` text NOT NULL
        );
INSERT INTO session_message VALUES ('msg_01', 'ses_0fa1c2d3e4ffAcmeFixture01', 'user', 1, 1, 1, '{"time": {"created": 1}, "text": "Rename the acme report to fix-api.", "files": [], "agents": []}');
INSERT INTO session_message VALUES ('msg_02', 'ses_0fa1c2d3e4ffAcmeFixture01', 'assistant', 2, 2, 2, '{"time": {"created": 2}, "agent": "build", "model": {"id": "mimo-v2.6-pro", "providerID": "mimo"}, "content": [{"type": "reasoning", "text": "The report lives under acme/.", "state": {"reasoningField": "reasoning_content"}}, {"type": "text", "text": "I''ll look at the report first."}, {"type": "tool", "id": "call_1", "name": "shell", "executed": false, "state": {"status": "completed", "input": {"command": "mv acme/report.md acme/fix-api.md"}, "content": [{"type": "text", "text": "renamed"}]}}]}');
INSERT INTO session_message VALUES ('msg_03', 'ses_0fa1c2d3e4ffAcmeFixture01', 'assistant', 3, 3, 3, '{"time": {"created": 3}, "agent": "build", "content": [{"type": "text", "text": "Renamed acme/report.md to acme/fix-api.md."}]}');
INSERT INTO session_message VALUES ('msg_04', 'ses_0fa1c2d3e4ffAcmeFixture01', 'idle', 4, 4, 4, '{"time": {"created": 4}, "outcome": "succeeded"}');
INSERT INTO session_message VALUES ('msg_05', 'ses_0fa1c2d3e4ffAcmeFixture01', 'system', 5, 5, 5, '{"time": {"created": 5}, "text": "Today''s date is now: Tue Oct 20 2026", "description": "Instructions updated: core/date"}');
INSERT INTO session_message VALUES ('msg_06', 'ses_0fa1c2d3e4ffAcmeFixture01', 'synthetic', 6, 6, 6, '{"time": {"created": 6}, "text": "The previous response was interrupted. Continue from where you left off."}');
INSERT INTO session_message VALUES ('msg_07', 'ses_0fa1c2d3e4ffAcmeFixture01', 'user', 7, 7, 7, '{"time": {"created": 7}, "text": "Thanks, that is all.", "files": [], "agents": []}');
INSERT INTO session_message VALUES ('msg_08', 'ses_0fa1c2d3e4ffAcmeFixture01', 'assistant', 8, 8, 8, '{"time": {"created": 8}, "agent": "build", "content": [{"type": "text", "text": "Done."}]}');
INSERT INTO session_message VALUES ('msg_99', 'ses_0fa1c2d3e4ffSubagent02', 'assistant', 1, 9, 9, '{"content": [{"type": "text", "text": "A subagent answer."}]}');
