"""
Unit and edge-case tests for robust pipeline behavior.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from models.message import MessageContent
from plugins.core import QJinEraPlugin
from services.commands import handle_command
from services.message_preprocessor import is_mentioned, preprocess_message
from services.storage import database, topics


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_edge_cases.db"
    monkeypatch.setattr(database, "_DB_PATH", str(test_db))
    database.init_db()
    yield test_db


def test_corrupt_and_legacy_db_content():
    now = time.time()
    t_id = topics.create("3003", now)

    # 1. Plain non-json string in database
    topics.add_message(t_id, "u1", "plain legacy string", now, "LegacyUser")

    # 2. Legacy json string without images key
    topics.add_message(t_id, "u2", '{"text": "legacy json text"}', now, "JsonUser")

    # 3. Malformed json
    topics.add_message(t_id, "u3", '{"text": incomplete json', now, "MalformedUser")

    # 4. Null content in database
    topics.add_message(t_id, "u4", None, now, "NullUser")

    active = topics.get_latest_active("3003")
    assert active is not None
    assert len(active["messages"]) == 4

    m1 = active["messages"][0]["content"]
    assert isinstance(m1, MessageContent)
    assert m1.text == "plain legacy string"
    assert m1.images == []

    m2 = active["messages"][1]["content"]
    assert isinstance(m2, MessageContent)
    assert m2.text == "legacy json text"
    assert m2.images == []

    m3 = active["messages"][2]["content"]
    assert isinstance(m3, MessageContent)
    assert m3.text == '{"text": incomplete json'

    m4 = active["messages"][3]["content"]
    assert isinstance(m4, MessageContent)
    assert m4.text == ""
    assert m4.images == []


def test_message_content_unusual_types():
    assert MessageContent.from_raw(None).text == ""
    assert MessageContent.from_raw(12345).text == "12345"
    assert MessageContent.from_raw({"text": None}).text == ""
    assert MessageContent.from_raw({"images": None}).images == []
    assert MessageContent.from_raw({"images": "single.jpg"}).images == ["single.jpg"]
    assert MessageContent.from_raw("").text == ""
    assert MessageContent.from_json("").text == ""
    assert MessageContent.from_json(None).text == ""
    assert "text" in MessageContent(text="")
    assert "images" not in MessageContent(text="")
    assert "images" in MessageContent(text="", images=["a.jpg"])


@pytest.mark.asyncio
async def test_preprocess_malformed_cq_face():
    # Non-integer face id
    content, _ = await preprocess_message("你好[CQ:face,id=undefined]世界")
    assert "你好" in content.text
    assert "世界" in content.text

    # Empty face id or missing id
    content2, _ = await preprocess_message("表情[CQ:face]测试")
    assert "[表情]" in content2.text


@pytest.mark.asyncio
async def test_preprocess_cq_at_with_extra_params():
    class MockEv:
        self_id = 98765
        message = "[CQ:at,qq=98765,name=BotName] 你好"

    assert is_mentioned(MockEv()) is True

    content, _ = await preprocess_message(MockEv.message)
    assert "[@98765]" in content.text
    assert "你好" in content.text


@pytest.mark.asyncio
async def test_preprocess_image_download_failure():
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Network timeout")

    with patch("services.message_preprocessor.get_http_client", return_value=mock_client):
        msg = "测试异常[CQ:image,url=http://example.com/fail.jpg]"
        content, memory_images = await preprocess_message(msg)

        assert "测试异常 [图片]" in content.text
        # Even if download fails, preprocessing doesn't crash and returns empty images
        assert content.images == []
        assert memory_images == []


@pytest.mark.asyncio
async def test_preprocess_stripped_cq_code_fallback():
    # Message with only CQ codes that get stripped
    msg = "[CQ:record,file=voice.amr]"
    content, memory_images = await preprocess_message(msg)
    assert content.text == "[图片/表情]"


@pytest.mark.asyncio
async def test_command_case_and_whitespace():
    event = AsyncMock()
    event.group_id = "555"
    event.reply = AsyncMock()

    with patch("services.topic.topic_manager.switch_topic") as mock_switch:
        # Uppercase /CLEAR
        assert await handle_command(event, MessageContent(text="/CLEAR")) is True
        mock_switch.assert_called_with("555")

        # Leading & trailing spaces
        assert await handle_command(event, MessageContent(text="   /clear   ")) is True

        # With arguments
        assert await handle_command(event, MessageContent(text="/clear all context")) is True

        # Preceded by @bot mention
        assert await handle_command(event, MessageContent(text="[@1106447644] /clear")) is True

        # Full-width Chinese IME slash ／clear
        assert await handle_command(event, MessageContent(text="／clear")) is True


def test_cleanup_stale_locks():
    # Insert some fake locks
    QJinEraPlugin._group_locks["stale_1"] = AsyncMock(locked=lambda: False)
    QJinEraPlugin._group_locks["stale_2"] = AsyncMock(locked=lambda: True)  # locked shouldn't be purged

    with patch("services.topic.topic_manager.active_topics", {"stale_2": {}}):
        QJinEraPlugin._cleanup_stale_locks()
        assert "stale_1" not in QJinEraPlugin._group_locks
        assert "stale_2" in QJinEraPlugin._group_locks
