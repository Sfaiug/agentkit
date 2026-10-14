# Is this event a sub-agent's own, run through the seat's hooks?  Codex marks it `agent_id`,
# Grok `subagentType`, each with its other spelling beside it.  Its turn is not the seat's: its
# end is a SubagentStop, never the seat's Stop, and its prompt is not the owner's answer.
# hooks/seat-state.sh and hooks/orchestrator-stop.sh both leave such a prompt or Stop alone.
(.agent_id // .agentId // .subagentType // .subagent_type) != null
