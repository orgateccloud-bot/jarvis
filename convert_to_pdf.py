"""Convert ORGATEC IA docx report to PDF using python-docx + fpdf2."""
from docx import Document
from docx.oxml.ns import qn
from fpdf import FPDF

class OrgatecPDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font('DejaVu', 'B', 8)
            self.set_text_color(0, 102, 204)
            self.cell(0, 6, 'ORGATEC IA - Relatório Técnico', align='L')
            self.ln(2)
            self.set_draw_color(0, 102, 204)
            self.line(10, 14, 200, 14)
            self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font('DejaVu', 'I', 7)
        self.set_text_color(136, 136, 136)
        self.cell(0, 10, f'Página {self.page_no()}/{{nb}}', align='C')

def get_cell_shading(cell):
    tcPr = cell._tc.find(qn('w:tcPr'))
    if tcPr is not None:
        shd = tcPr.find(qn('w:shd'))
        if shd is not None:
            return shd.get(qn('w:fill'), '')
    return ''

def hex_to_rgb(h):
    h = h.lstrip('#')
    if len(h) != 6:
        return (34, 34, 34)
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def get_para_info(para):
    """Get paragraph formatting info."""
    info = {'alignment': 'L', 'is_list': False, 'is_heading': 0, 'is_page_break': False, 'is_divider': False}

    style_name = para.style.name if para.style else ''
    if 'Heading 1' in style_name:
        info['is_heading'] = 1
    elif 'Heading 2' in style_name:
        info['is_heading'] = 2
    elif 'Heading 3' in style_name:
        info['is_heading'] = 3

    pPr = para._p.find(qn('w:pPr'))
    if pPr is not None:
        jc = pPr.find(qn('w:jc'))
        if jc is not None:
            val = jc.get(qn('w:val'), '')
            if val == 'center': info['alignment'] = 'C'
            elif val == 'right': info['alignment'] = 'R'

        numPr = pPr.find(qn('w:numPr'))
        if numPr is not None:
            info['is_list'] = True

        pBdr = pPr.find(qn('w:pBdr'))
        if pBdr is not None and not para.text.strip():
            info['is_divider'] = True

    for run in para.runs:
        for child in run._r:
            if child.tag == qn('w:br'):
                if child.get(qn('w:type'), '') == 'page':
                    info['is_page_break'] = True

    return info

def get_run_format(run):
    props = {'color': (34, 34, 34), 'size': 10, 'bold': False, 'italic': False}
    rPr = run._r.find(qn('w:rPr'))
    if rPr is not None:
        color_el = rPr.find(qn('w:color'))
        if color_el is not None:
            props['color'] = hex_to_rgb(color_el.get(qn('w:val'), '222222'))
        sz_el = rPr.find(qn('w:sz'))
        if sz_el is not None:
            props['size'] = int(sz_el.get(qn('w:val'), '20')) / 2
        b_el = rPr.find(qn('w:b'))
        if b_el is not None:
            val = b_el.get(qn('w:val'), 'true')
            props['bold'] = val != 'false'
        i_el = rPr.find(qn('w:i'))
        if i_el is not None:
            val = i_el.get(qn('w:val'), 'true')
            props['italic'] = val != 'false'
    return props

def render_paragraph(pdf, para):
    info = get_para_info(para)
    text = para.text.strip()

    if info['is_page_break']:
        pdf.add_page()
        return

    if info['is_divider']:
        pdf.set_draw_color(0, 102, 204)
        y = pdf.get_y()
        pdf.line(10, y, 200, y)
        pdf.ln(4)
        return

    if not text:
        pdf.ln(2)
        return

    if info['is_heading'] == 1:
        pdf.ln(6)
        pdf.set_font('DejaVu', 'B', 16)
        pdf.set_text_color(0, 102, 204)
        pdf.multi_cell(0, 7, text, align='L')
        pdf.set_draw_color(0, 102, 204)
        pdf.line(10, pdf.get_y() + 1, 200, pdf.get_y() + 1)
        pdf.ln(4)
        return

    if info['is_heading'] == 2:
        pdf.ln(4)
        pdf.set_font('DejaVu', 'B', 13)
        pdf.set_text_color(0, 68, 153)
        pdf.multi_cell(0, 6, text, align='L')
        pdf.ln(2)
        return

    if info['is_heading'] == 3:
        pdf.ln(3)
        pdf.set_font('DejaVu', 'B', 11)
        pdf.set_text_color(0, 68, 153)
        pdf.multi_cell(0, 6, text, align='L')
        pdf.ln(2)
        return

    if info['is_list']:
        pdf.set_font('DejaVu', '', 10)
        pdf.set_text_color(34, 34, 34)
        x = pdf.get_x()
        pdf.cell(10, 5, '')  # indent
        pdf.cell(5, 5, chr(8226))  # bullet
        pdf.multi_cell(170, 5, text, align='L')
        pdf.ln(1)
        return

    # Regular paragraph - use run formatting
    if len(para.runs) > 0:
        # Check if all runs have same formatting for simpler output
        first_fmt = get_run_format(para.runs[0])

        # For cover page items with special formatting, render with first run style
        style = ''
        if first_fmt['bold']: style += 'B'
        if first_fmt['italic']: style += 'I'
        pdf.set_font('DejaVu', style, first_fmt['size'])
        pdf.set_text_color(*first_fmt['color'])
        pdf.multi_cell(0, first_fmt['size'] * 0.6, text, align=info['alignment'])
        pdf.ln(1)
    else:
        pdf.set_font('DejaVu', '', 10)
        pdf.set_text_color(34, 34, 34)
        pdf.multi_cell(0, 5, text, align=info['alignment'])
        pdf.ln(1)

def render_table(pdf, table):
    rows = table.rows
    if not rows:
        return

    num_cols = len(rows[0].cells)
    page_w = 190  # usable width

    # Calculate column widths based on content
    col_widths = []
    if num_cols == 3:
        col_widths = [50, 50, 90]
    elif num_cols == 2:
        col_widths = [95, 95]
    elif num_cols == 4:
        col_widths = [35, 45, 55, 55]
    else:
        col_widths = [page_w / num_cols] * num_cols

    for i, row in enumerate(rows):
        cells = row.cells
        # Calculate row height
        max_lines = 1
        for j, cell in enumerate(cells):
            cell_text = ' '.join(p.text for p in cell.paragraphs).strip()
            w = col_widths[j] - 4
            if w > 0 and cell_text:
                est_lines = max(1, int(len(cell_text) * 2.2 / w) + 1)
                max_lines = max(max_lines, est_lines)
        row_h = max(8, max_lines * 5)

        # Check if we need a new page
        if pdf.get_y() + row_h > 270:
            pdf.add_page()

        y_start = pdf.get_y()
        x_start = pdf.get_x()

        for j, cell in enumerate(cells):
            cell_text = ' '.join(p.text for p in cell.paragraphs).strip()
            bg = get_cell_shading(cell)
            is_header = bg.upper() in ('0066CC', '0066cc')

            x = x_start + sum(col_widths[:j])
            pdf.set_xy(x, y_start)

            # Background
            if is_header:
                pdf.set_fill_color(0, 102, 204)
                pdf.set_text_color(255, 255, 255)
                pdf.set_font('DejaVu', 'B', 9)
            elif bg and bg.upper() != 'FFFFFF':
                r, g, b = hex_to_rgb(bg)
                pdf.set_fill_color(r, g, b)
                pdf.set_text_color(34, 34, 34)
                pdf.set_font('DejaVu', '', 9)
            else:
                pdf.set_fill_color(255, 255, 255)
                pdf.set_text_color(34, 34, 34)
                pdf.set_font('DejaVu', '', 9)

            # Draw cell background
            pdf.rect(x, y_start, col_widths[j], row_h, 'F')

            # Draw cell border
            pdf.set_draw_color(204, 204, 204)
            pdf.rect(x, y_start, col_widths[j], row_h, 'D')

            # Cell text
            pdf.set_xy(x + 2, y_start + 2)
            pdf.multi_cell(col_widths[j] - 4, 4, cell_text, align='L')

        pdf.set_y(y_start + row_h)

    pdf.ln(4)

def convert(docx_path, pdf_path):
    doc = Document(docx_path)
    pdf = OrgatecPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    # Add Unicode font
    pdf.add_font('DejaVu', '', r'C:\Windows\Fonts\arial.ttf', uni=True)
    pdf.add_font('DejaVu', 'B', r'C:\Windows\Fonts\arialbd.ttf', uni=True)
    pdf.add_font('DejaVu', 'I', r'C:\Windows\Fonts\ariali.ttf', uni=True)
    pdf.add_font('DejaVu', 'BI', r'C:\Windows\Fonts\arialbi.ttf', uni=True)
    pdf.add_page()

    body = doc.element.body
    from docx.text.paragraph import Paragraph
    from docx.table import Table as DocxTable

    for child in body:
        tag = child.tag
        if tag == qn('w:p'):
            para = Paragraph(child, doc)
            render_paragraph(pdf, para)
        elif tag == qn('w:tbl'):
            tbl = DocxTable(child, doc)
            render_table(pdf, tbl)

    pdf.output(pdf_path)
    print(f"PDF gerado com sucesso: {pdf_path}")
    print(f"Total de páginas: {pdf.page_no()}")

if __name__ == '__main__':
    src = r"C:\Users\Veloso\Downloads\files (3)\relatorio-orgatec.docx"
    dst = r"C:\Users\Veloso\Downloads\files (3)\relatorio-orgatec.pdf"
    convert(src, dst)
