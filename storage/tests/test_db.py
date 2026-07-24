from __future__ import annotations

import sqlite3

import pytest

from storage.db import DuplicateRecordError, SQLiteStorage


@pytest.fixture()
def storage(tmp_path):
    db_path = tmp_path / "storage.sqlite3"
    db = SQLiteStorage(db_path)
    try:
        yield db, db_path
    finally:
        db.close()


def test_create_database(storage):
    db, db_path = storage

    assert db_path.exists()
    with db.connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert {"skills", "channels", "images"}.issubset(tables)


def test_insert_and_retrieve_skill(storage):
    db, _ = storage

    created = db.create_skill(
        name="analytics",
        description="Analytics skill",
        version="1.0.0",
        enabled=True,
        config={"region": "us-east-1"},
    )

    retrieved = db.get_skill("analytics")

    assert created == retrieved
    assert retrieved == {
        "name": "analytics",
        "description": "Analytics skill",
        "version": "1.0.0",
        "enabled": True,
        "config": {"region": "us-east-1"},
    }


def test_insert_and_retrieve_channel(storage):
    db, _ = storage

    created = db.create_channel(
        name="ops",
        type="slack",
        webhook_url="https://example.com/webhook",
        enabled=False,
    )

    retrieved = db.get_channel("ops")

    assert created == retrieved
    assert retrieved == {
        "name": "ops",
        "type": "slack",
        "webhook_url": "https://example.com/webhook",
        "enabled": False,
    }


def test_insert_and_retrieve_image(storage):
    db, _ = storage

    created = db.create_image(
        prompt="A small robot in a warehouse",
        size="1024x1024",
        style="realistic",
        format="png",
    )

    retrieved = db.get_image(created["id"])

    assert created == retrieved
    assert retrieved["prompt"] == "A small robot in a warehouse"
    assert retrieved["size"] == "1024x1024"
    assert retrieved["style"] == "realistic"
    assert retrieved["format"] == "png"
    assert retrieved["created_at"]


def test_duplicate_skill_rejected(storage):
    db, _ = storage

    db.create_skill(
        name="duplicate",
        description="Original skill",
        version="1.0.0",
        enabled=True,
        config={},
    )

    with pytest.raises(DuplicateRecordError):
        db.create_skill(
            name="duplicate",
            description="Second skill",
            version="1.0.1",
            enabled=False,
            config={},
        )


@pytest.mark.parametrize(
    "getter,missing_id",
    [
        ("get_skill", "missing-skill"),
        ("get_channel", "missing-channel"),
        ("get_image", "missing-image"),
    ],
)
def test_missing_record_returns_none(storage, getter, missing_id):
    db, _ = storage

    result = getattr(db, getter)(missing_id)

    assert result is None
