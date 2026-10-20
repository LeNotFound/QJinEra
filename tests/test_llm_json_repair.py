"""
Unit tests for LLM JSON repair and API/JSON error logging separation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from services import llm


def test_repair_json_standard_valid():
    raw = '{"messages": ["hello"], "confidence": 0.9}'
    assert llm._parse_json(raw) == {"messages": ["hello"], "confidence": 0.9}


def test_repair_json_markdown_code_fences():
    raw = '''```json
    {
      "messages": ["test markdown fence"],
      "energy_cost": 2
    }
    ```'''
    res = llm._parse_json(raw)
    assert res == {"messages": ["test markdown fence"], "energy_cost": 2}


def test_repair_json_leading_plus_numbers():
    # The exact issue observed with Gemini when prompt had +1.0 or +2~+10
    raw = '''{
      "messages": ["hello"],
      "dopamine_delta": +1.0,
      "energy_cost": +5,
      "float_val": +0.25,
      "nested": {
        "score": +10
      },
      "list_vals": [+1, +2.5, -3]
    }'''
    res = llm._parse_json(raw)
    assert res["dopamine_delta"] == 1.0
    assert res["energy_cost"] == 5
    assert res["float_val"] == 0.25
    assert res["nested"]["score"] == 10
    assert res["list_vals"] == [1, 2.5, -3]


def test_repair_json_trailing_commas_and_comments():
    raw = '''{
      // single line comment
      "messages": [
        "hi",
      ],
      "summary": "done",
    }'''
    res = llm._parse_json(raw)
    assert res == {"messages": ["hi"], "summary": "done"}


def test_repair_json_surrounding_conversational_text():
    raw = '''Here is your response:
    {
      "should_intervene": true,
      "reason": "greetings"
    }
    Hope this helps!'''
    res = llm._parse_json(raw)
    assert res == {"should_intervene": True, "reason": "greetings"}


@pytest.mark.asyncio
async def test_call_api_network_error_logging():
    # Simulate APIConnectionError / network failure
    mock_request = MagicMock()
    api_err = openai.APIConnectionError(request=mock_request)

    with patch.object(llm._client.chat.completions, "create", new_callable=AsyncMock, side_effect=api_err), \
         patch.object(llm.logger, "error") as mock_logger_error:

        res = await llm._call("gemini-test", "system prompt", "user message", json_mode=True)
        assert res is None

        # Verify error log specifically indicates API request failure
        mock_logger_error.assert_called_once()
        log_msg = mock_logger_error.call_args[0][0]
        assert "API 请求失败" in log_msg


@pytest.mark.asyncio
async def test_call_json_decode_error_logging_includes_raw_content():
    # Simulate API returning malformed unrepairable content
    bad_content = 'This is completely invalid and not JSON at all: {"broken: true'
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=bad_content))]

    with patch.object(llm._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_resp), \
         patch.object(llm.logger, "error") as mock_logger_error:

        res = await llm._call("gemini-test", "system prompt", "user message", json_mode=True)
        assert res is None

        # Verify error log specifically indicates JSON parsing failure and outputs raw content
        mock_logger_error.assert_called_once()
        call_args = mock_logger_error.call_args[0]
        log_fmt = call_args[0]
        assert "JSON 解析失败" in log_fmt
        # Raw content must be passed in arguments for logging
        assert bad_content in call_args


@pytest.mark.asyncio
async def test_call_empty_content_logging():
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=""))]

    with patch.object(llm._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_resp), \
         patch.object(llm.logger, "error") as mock_logger_error:

        res = await llm._call("gemini-test", "system prompt", "user message", json_mode=True)
        assert res is None
        mock_logger_error.assert_called_once()
        assert "返回内容为空" in mock_logger_error.call_args[0][0]


@pytest.mark.asyncio
async def test_call_gemini_repaired_successfully():
    # When Gemini returns +1.0 in dopamine_delta, _call automatically repairs and parses it
    gemini_content = '{\n  "messages": ["你好呀！"],\n  "summary": "打招呼",\n  "dopamine_delta": +1.0,\n  "energy_cost": +2\n}'
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=gemini_content))]

    with patch.object(llm._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_resp), \
         patch.object(llm.logger, "error") as mock_logger_error:

        res = await llm._call("gemini-test", "system prompt", "user message", json_mode=True)
        assert res is not None
        assert res["messages"] == ["你好呀！"]
        assert res["dopamine_delta"] == 1.0
        assert res["energy_cost"] == 2
        mock_logger_error.assert_not_called()


def test_repair_json_markdown_code_fences_with_nested_backticks():
    # When bot outputs a reply containing markdown code fence ```python ... ```
    raw = '''```json
    {
      "messages": ["以下是代码示例：\\n```python\\nprint('hello')\\n```"],
      "energy_cost": 2
    }
    ```'''
    res = llm._parse_json(raw)
    assert res["messages"] == ["以下是代码示例：\n```python\nprint('hello')\n```"]
    assert res["energy_cost"] == 2


def test_repair_json_inline_comments_and_url_preservation():
    # Preserves URL // in string, strips inline and block comments outside strings
    raw = '''{
      "url": "https://example.com/api?q=1//2",
      "messages": [
        "hi" // end of line comment
      ], /* block comment */
      "dopamine_delta": +2.5,
      "energy_cost": 3
    }'''
    res = llm._parse_json(raw)
    assert res["url"] == "https://example.com/api?q=1//2"
    assert res["messages"] == ["hi"]
    assert res["dopamine_delta"] == 2.5
    assert res["energy_cost"] == 3


def test_repair_json_string_literal_preservation():
    # Ensures + signs, colons, commas and braces INSIDE strings are never stripped
    raw = '''{
      "messages": ["分数: +5分", "看这个符号: , } 还有 {括号}"],
      "dopamine_delta": +1.0
    }'''
    res = llm._parse_json(raw)
    assert res["messages"] == ["分数: +5分", "看这个符号: , } 还有 {括号}"]
    assert res["dopamine_delta"] == 1.0


def test_repair_json_conversational_text_after_json_with_braces():
    # Precision container extractor stops at root closing brace even if following text contains {braces}
    raw = '''这是你要的分析：
    {
      "messages": ["收到！"],
      "summary": "正常响应"
    }
    提示：请保留模板中的 {placeholder} 占位符以便后续替换！'''
    res = llm._parse_json(raw)
    assert res == {"messages": ["收到！"], "summary": "正常响应"}


def test_repair_json_python_literals_and_leading_dots():
    # Handles True/False/None and +.5 / .5
    raw = '''{
      "should_intervene": True,
      "focus_user": None,
      "active": False,
      "delta": +.5,
      "cost": .25
    }'''
    res = llm._parse_json(raw)
    assert res["should_intervene"] is True
    assert res["focus_user"] is None
    assert res["active"] is False
    assert res["delta"] == 0.5
    assert res["cost"] == 0.25


def test_repair_json_single_quotes_fallback():
    raw = "{'messages': ['你好世界'], 'summary': '测试'}"
    res = llm._parse_json(raw)
    assert res == {"messages": ["你好世界"], "summary": "测试"}


@pytest.mark.asyncio
async def test_call_empty_choices_logging():
    # When API returns empty choices list []
    mock_resp = MagicMock()
    mock_resp.choices = []

    with patch.object(llm._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_resp), \
         patch.object(llm.logger, "error") as mock_logger_error:

        res = await llm._call("gemini-test", "system prompt", "user message", json_mode=True)
        assert res is None
        mock_logger_error.assert_called_once()
        assert "返回内容为空" in mock_logger_error.call_args[0][0]

