"""Supervisor promotion flow (deferred).

The full "CLI-Fork Supervision" pattern from design.md §4.1.2 involves:
1. Forking the planning session via SessionManager
2. Establishing supervisor session UUID via claude --fork-session
3. Recording supervisor configuration in the executor session

The --fork-session flag is available since Claude Code v2.1.77+. The automated
promotion flow (creating a dedicated supervisor session) is not yet implemented.

Preferred approach (available now):
    forge session fork planner --name executor --supervise   # At fork time
    forge guard supervise planner                            # On existing session
    %guard supervise planner                                 # In-session

Manual approach (still works):
    forge session set policy.supervisor.resume_id <name-or-uuid>
"""
