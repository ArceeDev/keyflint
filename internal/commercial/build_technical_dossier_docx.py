"""
Compiles KEYFLINT_DOSSIER_TECNICO_COMPLETO.md into an executive Word (.docx) document.
Styled in accordance with B2B Quiet Luxury / Technical Document standards.
"""
import os
import re
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls

def set_cell_background(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)

def add_inline_runs(paragraph, text, base_font_size=10.5, is_code=False):
    # Regex to extract `code`, **bold**, *italic*
    # Simple tokenization
    pattern = re.compile(r'(\*\*.*?\*\*|\*.*?\*|`.*?`)')
    parts = pattern.split(text)
    for part in parts:
        if not part:
            continue
        if part.startswith('**') and part.endswith('**') and len(part) >= 4:
            r = paragraph.add_run(part[2:-2])
            r.font.bold = True
            r.font.name = 'Consolas' if is_code else 'Segoe UI'
            r.font.size = Pt(base_font_size)
            r.font.color.rgb = RGBColor(0x0B, 0x0D, 0x17)
        elif part.startswith('*') and part.endswith('*') and len(part) >= 2:
            r = paragraph.add_run(part[1:-1])
            r.font.italic = True
            r.font.name = 'Consolas' if is_code else 'Segoe UI'
            r.font.size = Pt(base_font_size)
            r.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        elif part.startswith('`') and part.endswith('`') and len(part) >= 2:
            r = paragraph.add_run(part[1:-1])
            r.font.name = 'Consolas'
            r.font.size = Pt(base_font_size - 0.5)
            r.font.color.rgb = RGBColor(0x1A, 0x36, 0x5D)
        else:
            r = paragraph.add_run(part)
            r.font.name = 'Consolas' if is_code else 'Segoe UI'
            r.font.size = Pt(base_font_size)
            r.font.color.rgb = RGBColor(0x22, 0x22, 0x22)

def build_docx(md_path, docx_path):
    with open(md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    doc = Document()

    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    normal_style = doc.styles['Normal']
    normal_style.font.name = 'Segoe UI'
    normal_style.font.size = Pt(10.5)
    normal_style.font.color.rgb = RGBColor(0x22, 0x22, 0x22)

    in_code_block = False
    code_lines = []
    in_table = False
    table_lines = []

    def flush_code(lines_list):
        if not lines_list:
            return
        tbl = doc.add_table(rows=1, cols=1)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = tbl.cell(0, 0)
        set_cell_background(cell, "F4F5F7")
        set_cell_margins(cell, top=140, bottom=140, left=180, right=180)
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.15
        
        full_code = "".join(lines_list).rstrip()
        r = p.add_run(full_code)
        r.font.name = 'Consolas'
        r.font.size = Pt(8.5)
        r.font.color.rgb = RGBColor(0x1F, 0x23, 0x28)
        
        spacer = doc.add_paragraph()
        spacer.paragraph_format.space_after = Pt(4)

    def flush_table(lines_list):
        if not lines_list:
            return
        # Parse markdown table
        rows_data = []
        for l in lines_list:
            stripped = l.strip()
            if not stripped or stripped.startswith('+') or stripped.startswith('|-') or '---' in stripped:
                continue
            cells = [c.strip() for c in stripped.strip('|').split('|')]
            if cells:
                rows_data.append(cells)
        if not rows_data:
            return
        
        num_cols = max(len(r) for r in rows_data)
        tbl = doc.add_table(rows=len(rows_data), cols=num_cols)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        
        for row_idx, row_cells in enumerate(rows_data):
            is_header = (row_idx == 0)
            for col_idx in range(num_cols):
                cell_text = row_cells[col_idx] if col_idx < len(row_cells) else ""
                cell = tbl.cell(row_idx, col_idx)
                set_cell_margins(cell, top=100, bottom=100, left=120, right=120)
                if is_header:
                    set_cell_background(cell, "0B0D17")
                elif row_idx % 2 == 1:
                    set_cell_background(cell, "F9FAFB")
                else:
                    set_cell_background(cell, "FFFFFF")
                
                p = cell.paragraphs[0]
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(2)
                r = p.add_run(cell_text)
                r.font.name = 'Segoe UI'
                r.font.size = Pt(9)
                if is_header:
                    r.font.bold = True
                    r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                else:
                    r.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
        
        spacer = doc.add_paragraph()
        spacer.paragraph_format.space_after = Pt(4)

    for line in lines:
        stripped = line.strip()

        # Code block toggle
        if stripped.startswith('```'):
            if in_code_block:
                flush_code(code_lines)
                code_lines = []
                in_code_block = False
            else:
                if in_table:
                    flush_table(table_lines)
                    table_lines = []
                    in_table = False
                in_code_block = True
                code_lines = []
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        # Markdown Table line
        if stripped.startswith('|') and '|' in stripped[1:]:
            if not in_table:
                in_table = True
                table_lines = []
            table_lines.append(line)
            continue
        else:
            if in_table:
                flush_table(table_lines)
                table_lines = []
                in_table = False

        if not stripped:
            continue

        # Headers
        if stripped.startswith('# '):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(18)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.keep_with_next = True
            r = p.add_run(stripped[2:])
            r.font.name = 'Segoe UI Semibold'
            r.font.size = Pt(22)
            r.font.bold = True
            r.font.color.rgb = RGBColor(0x0B, 0x0D, 0x17)
        elif stripped.startswith('## '):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(16)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.keep_with_next = True
            r = p.add_run(stripped[3:])
            r.font.name = 'Segoe UI Semibold'
            r.font.size = Pt(15)
            r.font.bold = True
            r.font.color.rgb = RGBColor(0x0B, 0x0D, 0x17)
        elif stripped.startswith('### '):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.keep_with_next = True
            r = p.add_run(stripped[4:])
            r.font.name = 'Segoe UI Semibold'
            r.font.size = Pt(12.5)
            r.font.bold = True
            r.font.color.rgb = RGBColor(0x23, 0x27, 0x38)
        elif stripped.startswith('#### '):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.keep_with_next = True
            r = p.add_run(stripped[5:])
            r.font.name = 'Segoe UI'
            r.font.size = Pt(11)
            r.font.bold = True
            r.font.color.rgb = RGBColor(0x4A, 0x55, 0x68)
        elif stripped.startswith('* ') or stripped.startswith('- '):
            bullet_text = stripped[2:]
            p = doc.add_paragraph(style='List Bullet')
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(2.5)
            p.paragraph_format.line_spacing = 1.15
            add_inline_runs(p, bullet_text, base_font_size=10.0)
        elif re.match(r'^\d+\.\s+', stripped):
            num_match = re.match(r'^(\d+\.\s+)(.*)$', stripped)
            prefix = num_match.group(1)
            body = num_match.group(2)
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.line_spacing = 1.15
            r_pre = p.add_run(prefix)
            r_pre.font.bold = True
            r_pre.font.size = Pt(10.0)
            add_inline_runs(p, body, base_font_size=10.0)
        elif stripped.startswith('> '):
            tbl = doc.add_table(rows=1, cols=1)
            cell = tbl.cell(0, 0)
            set_cell_background(cell, "F0F4F8")
            set_cell_margins(cell, top=80, bottom=80, left=140, right=140)
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            add_inline_runs(p, stripped[2:], base_font_size=9.5)
        elif stripped == '---':
            continue
        else:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(5)
            p.paragraph_format.line_spacing = 1.15
            add_inline_runs(p, stripped, base_font_size=10.5)

    if in_code_block:
        flush_code(code_lines)
    if in_table:
        flush_table(table_lines)

    os.makedirs(os.path.dirname(docx_path), exist_ok=True)
    doc.save(docx_path)
    print(f"Successfully generated DOCX at: {docx_path}")

if __name__ == '__main__':
    md = r"C:\Users\Usuario\teamwork_projects\monetizable_project\internal\commercial\KEYFLINT_DOSSIER_TECNICO_COMPLETO.md"
    docx = r"C:\Users\Usuario\teamwork_projects\monetizable_project\internal\commercial\KEYFLINT_DOSSIER_TECNICO_COMPLETO.docx"
    build_docx(md, docx)
    # Also save a copy to User root for easy Google Drive upload
    user_copy = r"C:\Users\Usuario\KEYFLINT_DOSSIER_TECNICO_COMPLETO.docx"
    import shutil
    shutil.copyfile(docx, user_copy)
    print(f"Copied to: {user_copy}")
