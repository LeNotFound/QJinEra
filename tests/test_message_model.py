"""
Unit tests for models/message.py.
"""

from __future__ import annotations

import pytest
from models.message import MessageContent


def test_message_content_defaults():
    mc = MessageContent()
    assert mc.text == ""
    assert mc.images == []
    assert mc.to_dict() == {"text": ""}
    assert mc.to_json() == '{"text": ""}'


def test_message_content_with_data():
    mc = MessageContent(text="Hello world", images=["data/images/test.jpg"])
    assert mc.text == "Hello world"
    assert mc.images == ["data/images/test.jpg"]
    assert mc.to_dict() == {"text": "Hello world", "images": ["data/images/test.jpg"]}
    assert "images" in mc.to_json()


def test_message_content_dict_compatibility():
    mc = MessageContent(text="Hello", images=["1.jpg"])
    assert mc["text"] == "Hello"
    assert mc["images"] == ["1.jpg"]
    assert mc.get("text") == "Hello"
    assert mc.get("images") == ["1.jpg"]
    assert mc.get("non_existent", "default") == "default"
    assert "text" in mc
    assert "images" in mc
    assert str(mc) == "Hello"
    assert list(mc.keys()) == ["text", "images"]
    assert "Hello" in list(mc.values())
    assert ("text", "Hello") in list(mc.items())

    mc_no_images = MessageContent(text="No images")
    assert "text" in mc_no_images
    assert "images" not in mc_no_images
    assert mc_no_images.get("images") == []
    assert str(mc_no_images) == "No images"

    mc_empty = MessageContent(text="")
    assert "text" in mc_empty
    assert "images" not in mc_empty

    with pytest.raises(KeyError):
        _ = mc["non_existent"]


def test_message_content_from_dict():
    data = {"text": "From dict", "images": ["a.jpg", "b.jpg"]}
    mc = MessageContent.from_dict(data)
    assert mc.text == "From dict"
    assert mc.images == ["a.jpg", "b.jpg"]

    # None and empty inputs
    mc_none = MessageContent.from_dict(None)
    assert mc_none.text == ""
    assert mc_none.images == []

    mc_null_fields = MessageContent.from_dict({"text": None, "images": None})
    assert mc_null_fields.text == ""
    assert mc_null_fields.images == []

    mc_single_img = MessageContent.from_dict({"text": "hi", "images": "single.png"})
    assert mc_single_img.text == "hi"
    assert mc_single_img.images == ["single.png"]


def test_message_content_from_json():
    # Valid JSON dict
    json_str = '{"text": "Parsed JSON", "images": ["c.jpg"]}'
    mc = MessageContent.from_json(json_str)
    assert mc.text == "Parsed JSON"
    assert mc.images == ["c.jpg"]

    # Plain legacy text
    raw_str = "Plain legacy text without JSON"
    mc2 = MessageContent.from_json(raw_str)
    assert mc2.text == raw_str
    assert mc2.images == []

    # Non-dict JSON (e.g. JSON string or integer)
    mc3 = MessageContent.from_json('"quoted string"')
    assert mc3.text == "quoted string"

    # None or empty
    mc_null = MessageContent.from_json(None)
    assert mc_null.text == ""
    assert mc_null.images == []


def test_message_content_from_raw():
    mc_orig = MessageContent(text="Existing")
    assert MessageContent.from_raw(mc_orig) is mc_orig

    mc_dict = MessageContent.from_raw({"text": "From raw dict", "images": ["d.jpg"]})
    assert mc_dict.text == "From raw dict"
    assert mc_dict.images == ["d.jpg"]

    mc_str = MessageContent.from_raw("From raw str")
    assert mc_str.text == "From raw str"

    mc_int = MessageContent.from_raw(12345)
    assert mc_int.text == "12345"

    mc_none = MessageContent.from_raw(None)
    assert mc_none.text == ""
    assert mc_none.images == []
