-- A task can be left open with a small, durable handoff for its next session.
-- These fields are deliberately separate from artifact/question/answer: a
-- continuation is mutable working context, while submitted learning evidence
-- remains governed by the existing immutability rules.
ALTER TABLE tasks ADD COLUMN continuation_state TEXT NOT NULL DEFAULT 'active';
ALTER TABLE tasks ADD COLUMN next_step TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN blocker TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN tried TEXT NOT NULL DEFAULT '';

-- A carried task is a new tomorrow record. Keeping the source id on the new
-- row makes carry-forward idempotent and leaves the source day's record intact.
ALTER TABLE tasks ADD COLUMN carried_from_task_id INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS ux_tasks_carried_from_task
ON tasks(carried_from_task_id)
WHERE carried_from_task_id IS NOT NULL;
