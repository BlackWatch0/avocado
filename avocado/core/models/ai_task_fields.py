from __future__ import annotations

AI_TASK_PUBLIC_FIELDS = (
    "locked",
    "category",
    "user_intent",
)

AI_TASK_META_FIELDS = (
    "version",
    "editable_fields",
    "updated_at",
)

AI_TASK_ALL_FIELDS = AI_TASK_PUBLIC_FIELDS + AI_TASK_META_FIELDS
