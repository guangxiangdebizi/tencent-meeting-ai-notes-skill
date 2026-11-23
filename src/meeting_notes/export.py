import hashlib
import json
import uuid
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .models import Artifact, Exported, MeetingMinutes
from .parser import NotesError, check_size


def validate_minutes(minutes: MeetingMinutes) -> None:
    for text in [minutes.title, minutes.meeting_date, *minutes.participants,
                 *(v for group in [minutes.topics, minutes.decisions, minutes.actions, minutes.unresolved, minutes.other_notes]
                   for item in group for v in item.model_dump().values())]:
        if isinstance(text, str):
            check_size(text)
    value = json.dumps(minutes.model_dump(), ensure_ascii=False)
    # Source quotations and display text both count; never silently truncate an export.
    if len(value.encode("utf-8")) > 2 * 1024 * 1024:
        raise NotesError("INPUT_TOO_LARGE", "单场结构化纪要超过 2 MiB。", "将超长会议拆成较小的纪要。")
    for action in minutes.actions:
        if any(len(str(v)) > 32767 for v in action.model_dump().values()) or len(action.source_ref) + len(action.source_text) + 1 > 32767:
            raise NotesError("CELL_TOO_LARGE", "待办或原文依据超过 XLSX 单元格 32767 字符上限。", "拆分该待办及其依据后重试。")


def write_docx(minutes: MeetingMinutes, target: Path) -> None:
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(2.2)
    section.left_margin = section.right_margin = Cm(2.3)
    for name in ["Normal", "Title", "Heading 1", "Heading 2"]:
        style = doc.styles[name]
        style.font.name = "Arial"
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "SimSun")
    normal = doc.styles["Normal"]
    normal.font.size = Pt(10.5)
    normal.paragraph_format.line_spacing = 1.25
    normal.paragraph_format.space_after = Pt(6)
    for name in ["Heading 1", "Heading 2"]:
        doc.styles[name].font.color.rgb = RGBColor.from_string("17365D")
    header = section.header.paragraphs[0]
    header.text = "会议纪要  /  MEETING MINUTES"
    header.runs[0].font.size = Pt(9)
    header.runs[0].font.color.rgb = RGBColor.from_string("64748B")
    title = doc.add_paragraph(minutes.title, "Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"会议日期：{minutes.meeting_date}")
    doc.add_paragraph(f"参会人：{'、'.join(minutes.participants) or '待定'}")
    for heading, items in [("一、议题小结", minutes.topics), ("二、会议决策", minutes.decisions)]:
        doc.add_heading(heading, 1)
        if not items:
            doc.add_paragraph("原文未明确列出。")
        for item in items:
            doc.add_paragraph(item.text, "List Bullet")
    doc.add_heading("三、待办与责任分工", 1)
    table = doc.add_table(rows=1, cols=4)
    table.style = "Light Shading Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for c, label in zip(table.rows[0].cells, ["负责人", "事项", "期限", "状态"]):
        c.text = label
    repeat = OxmlElement("w:tblHeader")
    table.rows[0]._tr.get_or_add_trPr().append(repeat)
    for item in minutes.actions:
        for c, value in zip(table.add_row().cells, [item.owner, item.text, item.due_text, item.status]):
            c.text = value
    if not minutes.actions:
        table.add_row().cells[1].text = "原文未明确列出。"
    for heading, items in [("四、未决问题", minutes.unresolved), ("五、其他记录", minutes.other_notes)]:
        doc.add_heading(heading, 1)
        if not items:
            doc.add_paragraph("原文未明确列出。")
        for item in items:
            doc.add_paragraph(item.text, "List Bullet")
    evidence = [*minutes.topics, *minutes.decisions, *minutes.actions, *minutes.unresolved, *minutes.other_notes]
    if evidence:
        doc.add_heading("原文依据", 1)
        for item in evidence:
            doc.add_paragraph(f"{item.source_ref} · {item.section or '正文'}", "Heading 2")
            doc.add_paragraph(item.source_text)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("第 ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    footer.add_run(" 页")
    doc.core_properties.title = minutes.title
    doc.core_properties.subject = "会议纪要"
    doc.core_properties.author = ""
    doc.save(target)


def write_xlsx(minutes: MeetingMinutes, target: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "待办跟踪表"
    sheet.append(["负责人", "事项", "期限", "状态", "原文依据"])
    for action in minutes.actions:
        sheet.append([action.owner, action.text, action.due_text, action.status,
                      f"{action.source_ref}｜{action.source_text}"])
    # Force literal strings, including formula-like note text.
    for row in sheet:
        for c in row:
            c.data_type = "s"
            c.font = Font(name="Microsoft YaHei", size=11)
            c.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = sheet.dimensions
    for letter, width in zip("ABCDE", [18, 52, 24, 14, 72]):
        sheet.column_dimensions[letter].width = width
    sheet.row_dimensions[1].height = 30
    for c in sheet[1]:
        c.font = Font(name="Microsoft YaHei", size=11, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="17365D")
    for row in sheet.iter_rows(min_row=2):
        line_count = max(max(len(str(c.value or "")) // width + 1,
                             str(c.value or "").count("\n") + 1) for c, width in zip(row, [9, 26, 12, 7, 36]))
        sheet.row_dimensions[row[0].row].height = min(300, max(42, line_count * 18))
        for c in row:
            if c.row % 2 == 0:
                c.fill = PatternFill("solid", fgColor="EAF0F7")
            if c.value == "待定":
                c.fill = PatternFill("solid", fgColor="FFF2CC")
    statuses = DataValidation(type="list", formula1='"待办,进行中,已完成,待定"')
    statuses.errorTitle, statuses.error = "请选择状态", "状态必须来自下拉列表。"
    statuses.showErrorMessage = True
    sheet.add_data_validation(statuses)
    statuses.add(f"D2:D{max(1000, sheet.max_row)}")
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight = 1, 0
    sheet.print_title_rows = "1:1"
    sheet.print_options.horizontalCentered = True
    sheet.oddHeader.center.text = minutes.title[:200].replace("&", "&&")
    sheet.oddFooter.center.text = "第 &P 页 / 共 &N 页"
    workbook.save(target)


def export(minutes: MeetingMinutes, output_dir: Path, public_base_url: str | None = None) -> Exported:
    validate_minutes(minutes)
    if public_base_url:
        url = urlsplit(public_base_url)
        if url.scheme not in {"https", "http"} or not url.netloc or url.query or url.fragment or url.username:
            raise NotesError("CONFIG_ERROR", "PUBLIC_BASE_URL 必须为不含查询、账号或片段的 HTTP(S) 基础地址。", "由部署方修正 PUBLIC_BASE_URL。")
    folder = output_dir.resolve() / uuid.uuid4().hex
    files = []
    try:
        folder.mkdir(parents=True, exist_ok=False)
        for fmt, writer, filename in [("docx", write_docx, "meeting-minutes.docx"), ("xlsx", write_xlsx, "action-items.xlsx")]:
            target = folder / filename
            writer(minutes, target)
            data = target.read_bytes()
            files.append(Artifact(format=fmt, path=str(target), bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                                  downloadUrl=f"{public_base_url.rstrip('/')}/files/{folder.name}/{filename}" if public_base_url else None))
    except (OSError, ValueError) as exc:
        # Only remove files owned by this failed export, never a caller-specified path.
        if folder.is_dir():
            with suppress(OSError):
                for name in ["meeting-minutes.docx", "action-items.xlsx"]:
                    (folder / name).unlink(missing_ok=True)
                folder.rmdir()
        raise NotesError("EXPORT_FAILED", "无法写入会议产物。", "检查 OUTPUT_DIR 的写权限和剩余空间后重试。") from exc
    return Exported(files=files, action_count=len(minutes.actions))
