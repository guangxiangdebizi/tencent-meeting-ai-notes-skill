"""Run the public MCP workflow against synthetic fixtures and save usable deliverables."""

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


async def generate(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    params = StdioServerParameters(command=sys.executable, args=["-m", "meeting_notes.server"], cwd=ROOT,
                                   env={**os.environ, "MCP_TRANSPORT": "stdio", "PYTHONUTF8": "1"})
    async with Client(params) as client:
        prepared = []
        for name in ["yuanbao-weekly.md", "tencent-plain.txt"]:
            response = await client.call_tool("prepare_meeting_notes", {"text": (ROOT / "examples" / name).read_text(encoding="utf-8")})
            if response.is_error:
                raise RuntimeError(response.content)
            prepared.append(response.structured_content)
        merged = await client.call_tool("merge_action_items", {"meetings": [p["minutes"] for p in prepared], "week_start": "2026-11-23"})
        exported = await client.call_tool("export_meeting_minutes", {"minutes": prepared[0]["minutes"]})
        if merged.is_error or exported.is_error:
            raise RuntimeError("MCP export or merge failed")
        (destination / "prepared.json").write_text(json.dumps(prepared[0], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (destination / "minutes.md").write_text(prepared[0]["markdown"], encoding="utf-8")
        (destination / "weekly-actions.md").write_text(merged.structured_content["markdown"], encoding="utf-8")
        for artifact in exported.structured_content["files"]:
            shutil.copyfile(artifact["path"], destination / Path(artifact["path"]).name)
    print(f"Created minutes, weekly actions, DOCX and XLSX in {destination.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output" / "example")
    asyncio.run(generate(parser.parse_args().output_dir))
