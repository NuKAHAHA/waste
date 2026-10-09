"""Export the assignment DOCX with actual installed Times New Roman fonts.

Optional authoring tool, not a dependency of the scientific module.
Windows: pip install python-docx==1.2.0 reportlab==4.4.4
Then: python tools/export_report.py
The workflow uses Windows' installed fonts without distributing font binaries.
"""
import os
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from docx.oxml.ns import qn
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/report/Assignment_3_Smart_Waste_Report_RU.docx'
TARGET = SOURCE.with_suffix('.pdf')


def export():
    """Preserve report text and explicit page breaks; embed TNR font subsets."""
    font_dir = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for name, file in (('TNR', 'times.ttf'), ('TNR-Bold', 'timesbd.ttf')):
        path = font_dir / file
        if not path.is_file():
            raise RuntimeError(f'Actual Times New Roman font required: {path}')
        pdfmetrics.registerFont(TTFont(name, str(path)))
        face = pdfmetrics.getFont(name).face.name
        if b'TimesNewRoman' not in face.replace(b'-', b''):
            raise RuntimeError(f'Unexpected font face: {face}')
    pdfmetrics.registerFontFamily('TNR', normal='TNR', bold='TNR-Bold')
    body = ParagraphStyle('body', fontName='TNR', fontSize=12, leading=18,
                          alignment=TA_JUSTIFY, firstLineIndent=0.75*cm, spaceAfter=6)
    left = ParagraphStyle('left', parent=body, alignment=TA_LEFT, firstLineIndent=0)
    heading = ParagraphStyle('heading', parent=left, fontName='TNR-Bold', fontSize=14,
                             leading=21, spaceAfter=12, keepWithNext=True)
    title = ParagraphStyle('title', parent=heading, fontSize=18, leading=27)
    table_body = ParagraphStyle('table', parent=left, spaceAfter=0)
    table_head = ParagraphStyle('table-head', parent=table_body, fontName='TNR-Bold')
    source = Document(SOURCE)
    story = []
    references = False
    for element in source.element.body:
        if element.tag == qn('w:p'):
            para = DocxParagraph(element, source)
            if element.xpath('.//w:br[@w:type="page"]'):
                story.append(PageBreak())
                continue
            text = para.text
            if not text.strip():
                continue
            if text.startswith('11 Источники'):
                references = True
            if para.style.name == 'Title':
                style = title
            elif para.style.name.startswith('Heading'):
                style = heading
            elif references or text.startswith('Магистрант:'):
                style = left
            else:
                style = body
            story.append(Paragraph(escape(text).replace('\n', '<br/>'), style))
        elif element.tag == qn('w:tbl'):
            table = DocxTable(element, source)
            data = [[Paragraph(escape(cell.text), table_head if i == 0 else table_body)
                     for cell in row.cells] for i, row in enumerate(table.rows)]
            rendered = Table(data, colWidths=[17*cm / len(data[0])] * len(data[0]),
                             repeatRows=1, hAlign='LEFT')
            rendered.setStyle(TableStyle([
                ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 5),
                ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(rendered)

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('TNR', 12)
        canvas.drawCentredString(10.5*cm, 1*cm, str(document.page))
        canvas.restoreState()

    document = SimpleDocTemplate(str(TARGET), pagesize=(21*cm, 29.7*cm),
                                 leftMargin=2*cm, rightMargin=2*cm,
                                 topMargin=2*cm, bottomMargin=2*cm,
                                 title=source.core_properties.title,
                                 author=source.core_properties.author,
                                 pageCompression=1, invariant=1)
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    if document.page != 12:
        raise RuntimeError(f'Expected 12 pages, got {document.page}')
    print(f'Exported {document.page} pages with actual Times New Roman: {TARGET}')


if __name__ == '__main__':
    export()

