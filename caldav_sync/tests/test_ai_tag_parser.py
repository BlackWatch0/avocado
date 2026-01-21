from datetime import timedelta

from caldav_sync.ai_tag_parser import parse_ai_block


def test_parse_ai_block_basic():
    description = """
    Something here
    [AI]
    schema=1
    type=task
    lock=true
    estimated=2h
    deadline=2026-01-24T23:59:59Z
    priority=high
    unknown=foo
    [/AI]
    """
    meta = parse_ai_block(description)
    assert meta is not None
    assert meta.schema == 1
    assert meta.type == "task"
    assert meta.lock is True
    assert meta.estimated == timedelta(hours=2)
    assert meta.deadline is not None
    assert meta.priority == "high"
    assert meta.extra == {"unknown": "foo"}


def test_parse_ai_block_missing_end():
    description = "[AI]\nkey=value"
    assert parse_ai_block(description) is None


def test_parse_ai_block_duration_formats():
    description = "[AI]\nestimated=30m\n[/AI]"
    meta = parse_ai_block(description)
    assert meta is not None
    assert meta.estimated == timedelta(minutes=30)

    description = "[AI]\nestimated=PT2H30M\n[/AI]"
    meta = parse_ai_block(description)
    assert meta is not None
    assert meta.estimated == timedelta(hours=2, minutes=30)
