import asyncio
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from docx import Document
from mcp import Client, StdioServerParameters
from openpyxl import load_workbook

from meeting_notes.export import export
from meeting_notes.merge import merge
from meeting_notes.models import Action, MeetingMinutes
from meeting_notes.parser import NotesError, prepare

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (ROOT / "examples/yuanbao-weekly.md").read_text(encoding="utf-8")
SECOND = (ROOT / "examples/tencent-plain.txt").read_text(encoding="utf-8")


def test_mixed_lists_and_source_readback():
    result = prepare(SAMPLE)
    m = result.minutes
    assert (m.title, m.meeting_date, m.participants) == ("星桥项目周会", "2026-11-23", ["张三", "李四", "王五"])
    assert len(m.topics) == 3 and len(m.decisions) == 2 and len(m.unresolved) == 1
    assert [(a.owner, a.due_text, a.status) for a in m.actions] == [
        ("张三", "周五前", "待办"), ("李四", "下周一前", "待办"),
        ("王五", "2026-11-24", "已完成"), ("待定", "待定", "待办")]
    assert [a.text for a in m.actions] == ["整理客户演示脚本", "给出配置页面原型", "更新验收清单", "整理未关闭问题清单"]
    for item in [*m.topics, *m.actions, *m.decisions, *m.unresolved]:
        start, end = map(int, item.source_ref.replace("L", "").split("-"))
        assert item.source_text == "\n".join(SAMPLE.splitlines()[start - 1:end]).strip()
    assert prepare(SAMPLE.replace("\n", "\r\n")) == result
    assert "下周一前" in result.markdown


def test_legacy_and_plain_exports():
    legacy = prepare((ROOT / "examples/sanitized-output.md").read_text(encoding="utf-8"))
    assert len(legacy.minutes.actions) == 2
    assert legacy.minutes.meeting_date == "2026-05-21"
    assert "123456789" not in legacy.model_dump_json()
    assert len(legacy.minutes.decisions) == 0
    plain = prepare(SECOND).minutes
    assert len(plain.actions) == 2
    assert plain.participants == ["张三", "赵六"]
    assert plain.actions[1].owner == "赵六" and plain.actions[1].status == "进行中"
    unstructured = prepare("建议张三周五交报告，但尚未确认。")
    assert not unstructured.minutes.actions and not unstructured.minutes.decisions
    assert unstructured.minutes.other_notes[0].text == "建议张三周五交报告，但尚未确认。"


def test_nested_sections_tables_and_no_deadline_guess():
    value = prepare("""# 协调会
## 待办
- 交付包
  - 整理安装文档
  - 复核发布清单
## 议题小结
- 是否增加回归测试尚待讨论
## 待办事项
| 负责人 | 事项 | 期限 | 状态 |
| --- | --- | --- | --- |
| 陈一 | 上传归档包 | 2026-11-27 | 进行中 |
| | 汇总意见 | | |
## 其他
- 整理2026-11-20会议的材料
""").minutes
    assert [a.text for a in value.actions] == ["交付包", "整理安装文档", "复核发布清单", "上传归档包", "汇总意见"]
    assert value.actions[-2].owner == "陈一" and value.actions[-2].status == "进行中"
    assert value.actions[-1].owner == "待定" and value.actions[-1].due_text == "待定"
    assert prepare("## 待办\n- 整理2026-11-20会议的材料").minutes.actions[0].due_text == "待定"
    assert len(value.other_notes) == 1


@pytest.mark.parametrize("value,code", [(" \n", "EMPTY_INPUT"), ("中" * 90000, "INPUT_TOO_LARGE"), ("abc\x00", "INVALID_TEXT")])
def test_input_errors(value, code):
    with pytest.raises(NotesError) as error:
        prepare(value)
    assert error.value.code == code


def test_merge_dates_and_nonconflation():
    a, b = prepare(SAMPLE).minutes, prepare(SECOND).minutes
    merged = merge([a, b, a], "2026-11-23")
    assert len(merged.items) == 5
    assert {g.key for g in merged.by_date} == {"2026-11-24", "2026-11-25", "2026-11-27", "待定"}
    assert len(next(g.items for g in merged.by_owner if g.key == "张三")) == 2
    assert len(merge([a], "2026-11-30").items) == 2
    assert merge([a], owner="不存在").items == []
    # Same title and date do not identify a meeting or justify collapsing different evidence.
    b.title, b.meeting_date = a.title, a.meeting_date
    assert len(merge([a, b]).items) == 6
    with pytest.raises(NotesError):
        merge([a], "2026-11-24")


def verify_files(payload, minutes, download=False):
    assert len(payload["files"]) == 2
    for artifact in payload["files"]:
        path = Path(artifact["path"])
        data = path.read_bytes()
        assert artifact["bytes"] == len(data) and artifact["sha256"] == hashlib.sha256(data).hexdigest()
        if download:
            with urllib.request.urlopen(artifact["downloadUrl"], timeout=10) as response:
                assert response.read() == data
                assert response.headers["Cache-Control"] == "no-store"
        if artifact["format"] == "docx":
            doc = Document(path)
            assert doc.paragraphs[0].text == minutes["title"]
            assert len(doc.tables[0].rows) == len(minutes["actions"]) + 1
            assert doc.tables[0].rows[1].cells[1].text == minutes["actions"][0]["text"]
            assert minutes["actions"][0]["source_text"] in [p.text for p in doc.paragraphs]
        else:
            workbook = load_workbook(path)
            sheet = workbook.active
            assert sheet.max_row == len(minutes["actions"]) + 1
            assert list(next(sheet.values)) == ["负责人", "事项", "期限", "状态", "原文依据"]
            for row, action in zip(list(sheet.values)[1:], minutes["actions"]):
                assert row[:4] == (action["owner"], action["text"], action["due_text"], action["status"])
                assert action["source_text"] in row[4]
            assert sheet.freeze_panes == "B2" and sheet.data_validations.count == 1
            workbook.close()


def test_export_literal_cells_and_empty(tmp_path):
    minutes = prepare(SAMPLE).minutes
    minutes.actions[0].text = '=HYPERLINK("https://invalid.example","click")'
    files = export(minutes, tmp_path).model_dump()
    verify_files(files, minutes.model_dump())
    workbook = load_workbook(files["files"][1]["path"])
    assert workbook.active["B2"].data_type == "s"
    workbook.close()
    empty = export(MeetingMinutes(), tmp_path)
    assert len(empty.files) == 2
    too_big = MeetingMinutes(actions=[Action(text="x" * 32768, source_text="original", source_ref="L1-L1")])
    with pytest.raises(NotesError, match="32767"):
        export(too_big, tmp_path)


async def exercise_client(client, download=False):
    async with client:
        tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == {"prepare_meeting_notes", "export_meeting_minutes", "merge_action_items"}
        assert all(t.input_schema and t.output_schema for t in tools)
        first = await client.call_tool("prepare_meeting_notes", {"text": SAMPLE})
        assert not first.is_error
        assert len(first.content) == 1 and len(first.content[0].text) < 150
        prepared = first.structured_content
        assert len(prepared["minutes"]["actions"]) == 4
        second = await client.call_tool("prepare_meeting_notes", {"text": SECOND})
        merged = await client.call_tool("merge_action_items", {"meetings": [prepared["minutes"], second.structured_content["minutes"]], "week_start": "2026-11-23"})
        assert not merged.is_error and len(merged.structured_content["items"]) == 5
        exported = await client.call_tool("export_meeting_minutes", {"minutes": prepared["minutes"]})
        assert not exported.is_error, exported.content
        verify_files(exported.structured_content, prepared["minutes"], download)
        invalid = await client.call_tool("prepare_meeting_notes", {"text": ""})
        assert invalid.is_error and invalid.structured_content["code"] == "EMPTY_INPUT"
        invalid_date = await client.call_tool("prepare_meeting_notes", {"text": SAMPLE, "meeting_date": "2026-02-30"})
        assert invalid_date.is_error and invalid_date.structured_content["code"] == "INVALID_DATE"
        assert all(not a["downloadUrl"] for a in exported.structured_content["files"]) != download


def test_real_stdio_client(tmp_path):
    env = {**os.environ, "MCP_TRANSPORT": "stdio", "OUTPUT_DIR": str(tmp_path), "PUBLIC_BASE_URL": "", "PYTHONUTF8": "1"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "meeting_notes.server"], env=env, cwd=ROOT)
    asyncio.run(exercise_client(Client(params, read_timeout_seconds=30)))


def test_real_http_client_and_download(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "MCP_TRANSPORT": "http", "HOST": "127.0.0.1", "PORT": str(port),
           "OUTPUT_DIR": str(tmp_path), "PUBLIC_BASE_URL": base, "PYTHONUTF8": "1"}
    with (tmp_path / "server.log").open("wb") as log:
        process = subprocess.Popen([sys.executable, "-m", "meeting_notes.server"], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    pytest.fail((tmp_path / "server.log").read_text(encoding="utf-8"))
                try:
                    with urllib.request.urlopen(base + "/health", timeout=1) as response:
                        assert json.load(response)["status"] == "ok"
                    break
                except (urllib.error.URLError, TimeoutError):
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.1)
            asyncio.run(exercise_client(Client(base + "/mcp", read_timeout_seconds=30), download=True))
            for path in ["/files/invalid/action-items.xlsx", "/files/" + "a" * 32 + "/secret.txt", "/files/" + "a" * 32 + "/action-items.xlsx"]:
                with pytest.raises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(base + path, timeout=5)
                assert error.value.code == 404
        finally:
            process.terminate()
            process.wait(timeout=15)
