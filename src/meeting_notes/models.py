from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_BYTES = 256 * 1024


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Evidence(Model):
    text: str = Field(min_length=1, max_length=MAX_BYTES)
    source_ref: str = Field(min_length=1, max_length=80)
    source_text: str = Field(min_length=1, max_length=MAX_BYTES)
    section: str = Field(default="", max_length=500)


class Action(Evidence):
    owner: str = Field(default="待定", min_length=1, max_length=200)
    due_text: str = Field(default="待定", min_length=1, max_length=200)
    status: Literal["待办", "进行中", "已完成", "待定"] = "待办"


class MeetingMinutes(Model):
    title: str = Field(default="未命名会议", min_length=1, max_length=500)
    meeting_date: str = Field(default="待定", min_length=1, max_length=100)
    participants: list[str] = Field(default_factory=list, max_length=500)
    topics: list[Evidence] = Field(default_factory=list, max_length=4096)
    decisions: list[Evidence] = Field(default_factory=list, max_length=4096)
    actions: list[Action] = Field(default_factory=list, max_length=4096)
    unresolved: list[Evidence] = Field(default_factory=list, max_length=4096)
    other_notes: list[Evidence] = Field(default_factory=list, max_length=4096)

    @field_validator("participants")
    @classmethod
    def participant_lengths(cls, names: list[str]) -> list[str]:
        if any(not n.strip() or len(n) > 200 for n in names):
            raise ValueError("参会人姓名必须为 1-200 个字符")
        return names


class Prepared(Model):
    minutes: MeetingMinutes
    markdown: str
    warnings: list[str]


class Artifact(Model):
    format: Literal["docx", "xlsx"]
    path: str
    downloadUrl: str | None = None
    bytes: int
    sha256: str


class Exported(Model):
    files: list[Artifact]
    action_count: int


class MergedAction(Action):
    meeting_title: str
    meeting_date: str
    meeting_index: int
    due_date: str = "待定"


class ActionGroup(Model):
    key: str
    items: list[MergedAction]


class Merged(Model):
    week_start: str | None
    week_end: str | None
    items: list[MergedAction]
    by_owner: list[ActionGroup]
    by_date: list[ActionGroup]
    markdown: str
    warnings: list[str]
