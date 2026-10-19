"""
Unit tests for services/message_preprocessor.py.
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import pytest

from models.message import MessageContent
from services.message_preprocessor import is_mentioned, preprocess_message


class MockEvent:
    def __init__(self, message: str = "", self_id: int | str = 123456):
        self.message = message
        self.self_id = self_id


@pytest.mark.asyncio
async def test_preprocess_plain_text():
    content, memory_images = await preprocess_message("今天天气真好")
    assert isinstance(content, MessageContent)
    assert content.text == "今天天气真好"
    assert content.images == []
    assert memory_images == []


@pytest.mark.asyncio
async def test_preprocess_empty_message():
    content, memory_images = await preprocess_message("")
    assert isinstance(content, MessageContent)
    assert content.text == "[图片/表情]"
    assert content.images == []
    assert memory_images == []


@pytest.mark.asyncio
async def test_preprocess_cq_face():
    # id 14 is 微笑 / 呲牙 in standard face table
    content, _ = await preprocess_message("你好[CQ:face,id=14]呀")
    assert "[微笑]" in content.text or "/微笑" in content.text or "face:14" in content.text
    assert "你好" in content.text
    assert "呀" in content.text


@pytest.mark.asyncio
async def test_preprocess_cq_at():
    content, _ = await preprocess_message("[CQ:at,qq=987654321] 请问在吗？")
    assert "[@987654321]" in content.text
    assert "请问在吗？" in content.text

    content_all, _ = await preprocess_message("[CQ:at,qq=all] 全员通知")
    assert "[@all]" in content_all.text


@pytest.mark.asyncio
async def test_preprocess_cq_image_summary_sticker():
    # Sticker with summary
    msg = "[CQ:image,file=sticker.gif,summary=&#91;晚安&#93;]"
    content, memory_images = await preprocess_message(msg)
    assert "[动画表情:[晚安]]" in content.text
    assert memory_images == []
    assert content.images == []


@pytest.mark.asyncio
async def test_preprocess_cq_image_download_mocked(tmp_path):
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake_jpeg_image_data"
    mock_resp.raise_for_status = lambda: None

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("services.message_preprocessor.get_http_client", return_value=mock_client), \
         patch("services.message_preprocessor.IMAGE_DIR", str(tmp_path)):

        msg = "看这张图[CQ:image,file=photo.jpg,url=http://example.com/test.jpg]"
        content, memory_images = await preprocess_message(msg)

        assert "看这张图 [图片]" in content.text
        assert len(content.images) == 1
        assert len(memory_images) == 1
        assert memory_images[0] == base64.b64encode(b"fake_jpeg_image_data").decode("utf-8")


@pytest.mark.asyncio
async def test_preprocess_cq_image_base64_protocol(tmp_path):
    raw_bytes = b"inline_b64_img_data"
    b64_str = base64.b64encode(raw_bytes).decode("utf-8")
    msg = f"[CQ:image,file=base64://{b64_str}]"

    with patch("services.message_preprocessor.IMAGE_DIR", str(tmp_path)):
        content, memory_images = await preprocess_message(msg)
        assert "[图片]" in content.text
        assert len(content.images) == 1
        assert len(memory_images) == 1
        assert memory_images[0] == b64_str


@pytest.mark.asyncio
async def test_preprocess_cq_image_file_as_url(tmp_path):
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.content = b"downloaded_from_file_attr"
    mock_resp.raise_for_status = lambda: None

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("services.message_preprocessor.get_http_client", return_value=mock_client), \
         patch("services.message_preprocessor.IMAGE_DIR", str(tmp_path)):

        msg = "[CQ:image,file=https://example.com/from_file_param.png]"
        content, memory_images = await preprocess_message(msg)

        assert "[图片]" in content.text
        assert len(content.images) == 1
        assert len(memory_images) == 1


@pytest.mark.asyncio
async def test_preprocess_cq_image_gif_skipped():
    msg = "动图[CQ:image,file=test.gif,url=http://example.com/test.gif]"
    content, memory_images = await preprocess_message(msg)
    assert "[图片]" in content.text
    assert content.images == []
    assert memory_images == []


def test_is_mentioned():
    event_literal = MockEvent(message="[@123456] 你好", self_id=123456)
    assert is_mentioned(event_literal) is False

    # The raw message from NapCat / CQHTTP adapter has [CQ:at,qq=123456]
    event_cq = MockEvent(message="[CQ:at,qq=123456] 你好", self_id=123456)
    assert is_mentioned(event_cq) is True

    # With extra params like name=
    event_cq_name = MockEvent(message="[CQ:at,qq=123456,name=TestBot] 你好", self_id=123456)
    assert is_mentioned(event_cq_name) is True

    # Prefix mismatch
    event_prefix = MockEvent(message="[CQ:at,qq=1234567] 你好", self_id=123456)
    assert is_mentioned(event_prefix) is False

    event_other = MockEvent(message="[CQ:at,qq=999999] 你好", self_id=123456)
    assert is_mentioned(event_other) is False

    event_none = MockEvent(message="普通消息", self_id=123456)
    assert is_mentioned(event_none) is False
