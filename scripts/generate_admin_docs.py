#!/usr/bin/env python3
"""
Generate Digital Future NH PAC administrative docs:
  1. Cover letter explaining the PAC (DOCX + PDF)
  2. Wire transfer instructions for TD Bank NH (DOCX + PDF)

Both documents use the brand-book horizontal logo top-left,
Space Grotesk-style headings (Inter fallback for Word), and the
brand color #0A1128.
"""
from docx import Document
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs'
OUT.mkdir(exist_ok=True)
LOGO = ROOT / 'images' / 'logo-horizontal-trans.png'

NAVY = RGBColor(0x0A, 0x11, 0x28)
GRAY = RGBColor(0x4B, 0x55, 0x66)

TODAY = "April 29, 2026"

def add_logo(doc, width_in=2.6):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run()
    run.add_picture(str(LOGO), width=Inches(width_in))
    p.paragraph_format.space_after = Pt(6)

def set_default_font(doc, name='Calibri', size=11):
    style = doc.styles['Normal']
    style.font.name = name
    style.font.size = Pt(size)
    rpr = style.element.rPr
    rfonts = rpr.find(qn('w:rFonts')) if rpr is not None else None
    if rfonts is None and rpr is not None:
        rfonts = OxmlElement('w:rFonts')
        rpr.append(rfonts)
    if rfonts is not None:
        for k in ('w:ascii','w:hAnsi','w:cs','w:eastAsia'):
            rfonts.set(qn(k), name)

def heading(doc, text, size=18, color=NAVY, space_before=12, space_after=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.font.color.rgb = color
    r.font.bold = True
    return p

def para(doc, text, size=11, color=None, bold=False, space_after=8):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.font.bold = bold
    if color is not None:
        r.font.color.rgb = color
    return p

def divider(doc, color='0A1128'):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(8)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '8')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), color)
    pBdr.append(bottom)
    pPr.append(pBdr)

def shaded_para(doc, text, fill='F2F4F7', size=10, color=NAVY):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(8)
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill)
    pPr.append(shd)
    pf = p.paragraph_format
    pf.left_indent = Inches(0.15); pf.right_indent = Inches(0.15)
    r = p.add_run(text)
    r.font.size = Pt(size); r.font.color.rgb = color
    return p

def margins(doc, top=1.0, bottom=1.0, left=1.0, right=1.0):
    for section in doc.sections:
        section.top_margin = Inches(top)
        section.bottom_margin = Inches(bottom)
        section.left_margin = Inches(left)
        section.right_margin = Inches(right)

def footer(doc, text):
    section = doc.sections[0]
    fp = section.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run(text)
    r.font.size = Pt(8); r.font.color.rgb = GRAY


# ---------- Cover Letter (one page) ----------
def build_cover_letter():
    doc = Document()
    set_default_font(doc, size=10)
    margins(doc, top=0.5, bottom=0.5, left=0.85, right=0.85)

    add_logo(doc, width_in=2.0)
    divider(doc)

    para(doc, TODAY, color=GRAY, size=10, space_after=8)

    para(doc, "To Whom It May Concern:", bold=True, space_after=6)

    para(doc,
        "Thank you for taking a moment with this letter. Digital Future NH PAC is a "
        "newly registered, non-partisan New Hampshire political action committee. We "
        "raise money, endorse New Hampshire candidates, and contribute to candidates "
        "who defend digital property, financial privacy, and the right of New Hampshire "
        "residents to build and use new technology.",
        size=10, space_after=6)

    para(doc,
        "We are organized under New Hampshire RSA 664 and report contributions to the "
        "New Hampshire Secretary of State at the thresholds the law requires. We accept "
        "contributions in U.S. dollars and in Bitcoin, with crypto contributions valued "
        "at the spot rate at time of receipt and reported the same way as cash.",
        size=10, space_after=6)

    heading(doc, "What we are working on", size=11, space_before=4, space_after=2)
    para(doc,
        "New Hampshire is already the strongest state in the country on digital-asset "
        "policy. It was the first state to enact a Strategic Bitcoin Reserve law (HB 302, "
        "2025, Chapter 4) and the first to grant decentralized autonomous organizations "
        "legal personhood through a permissionless-blockchain registry (RSA 301-B:14, "
        "effective July 2025). Our job is to help keep that ground &mdash; by endorsing "
        "and contributing to candidates from any party who will defend self-custody, "
        "oppose central bank digital currencies, protect the right to mine and run nodes, "
        "and recognize smart contracts under state contract law.".replace('&mdash;', '—'),
        size=10, space_after=6)

    heading(doc, "PAC information", size=11, space_before=4, space_after=2)

    info_lines = [
        ("Committee name", "Digital Future NH PAC"),
        ("State of registration", "New Hampshire (RSA 664)"),
        ("EIN", "42-2221221"),
        ("Mailing address", "248 Carley Road, Peterborough, NH 03458"),
        ("Chair", "Christopher Maidment"),
        ("Phone", "540-598-1130 (m)"),
        ("Email", "info@digitalfuturenh.com"),
        ("Website", "digitalfuturenh.com"),
    ]
    table = doc.add_table(rows=len(info_lines), cols=2)
    table.autofit = False
    table.columns[0].width = Inches(2.0)
    table.columns[1].width = Inches(4.7)
    for i, (k, v) in enumerate(info_lines):
        c0 = table.rows[i].cells[0]
        c1 = table.rows[i].cells[1]
        c0.width = Inches(2.0); c1.width = Inches(4.7)
        p0 = c0.paragraphs[0]; p0.paragraph_format.space_after = Pt(0)
        r0 = p0.add_run(k)
        r0.font.size = Pt(9.5); r0.font.bold = True; r0.font.color.rgb = NAVY
        p1 = c1.paragraphs[0]; p1.paragraph_format.space_after = Pt(0)
        r1 = p1.add_run(v)
        r1.font.size = Pt(9.5); r1.font.color.rgb = NAVY

    para(doc,
        "If you need anything further to open or maintain a relationship with the PAC "
        "&mdash; W-9, Secretary of State filing confirmation, EIN letter, or a treasurer "
        "signature card &mdash; please reach out and we will turn it around the same "
        "day.".replace('&mdash;', '—'),
        size=10, space_after=4)

    para(doc, "Sincerely,", size=10, space_after=30)

    # Signature line
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(1)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    top = OxmlElement('w:top')
    top.set(qn('w:val'), 'single'); top.set(qn('w:sz'), '6')
    top.set(qn('w:space'), '1'); top.set(qn('w:color'), '0A1128')
    pBdr.append(top); pPr.append(pBdr)
    r = p.add_run("Christopher Maidment")
    r.font.bold = True; r.font.color.rgb = NAVY; r.font.size = Pt(10)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run("Chair, Digital Future NH PAC")
    r.font.size = Pt(9.5); r.font.color.rgb = GRAY

    footer(doc,
        "Paid for by NH Digital Future PAC, 248 Carley Road, Peterborough, NH 03458. Chris Maidment, Chair. Not authorized by any candidate or candidate's committee. Contributions are not tax deductible.")

    out = OUT / 'DigitalFutureNH_Cover_Letter.docx'
    doc.save(out)
    return out


# ---------- Wire Instructions (one page) ----------
def build_wire_instructions():
    doc = Document()
    set_default_font(doc, size=10)
    margins(doc, top=0.5, bottom=0.5, left=0.85, right=0.85)

    add_logo(doc, width_in=2.0)
    divider(doc)

    heading(doc, "Wire Transfer Instructions", size=18, space_before=0, space_after=2)
    para(doc, f"Issued {TODAY}", color=GRAY, size=9, space_after=8)

    heading(doc, "Beneficiary (account holder)", size=11, space_before=4, space_after=2)
    _kv_table(doc, [
        ("Name on account", "Digital Future NH PAC"),
        ("Mailing address", "248 Carley Road, Peterborough, NH 03458"),
        ("EIN", "42-2221221"),
    ])

    heading(doc, "Beneficiary bank", size=11, space_before=8, space_after=2)
    _kv_table(doc, [
        ("Bank name", "TD Bank, N.A."),
        ("Bank location", "Concord, New Hampshire"),
        ("Account number", "9248656542"),
        ("Account type", "Business checking"),
        ("Reference / memo", "Digital Future NH PAC contribution"),
    ])

    heading(doc, "Routing numbers", size=11, space_before=8, space_after=2)
    _kv_table(doc, [
        ("FedWire ABA (incoming wires)", "031101266"),
        ("ACH routing (electronic transfers)", "011400071"),
    ])

    heading(doc, "Notes for senders", size=11, space_before=8, space_after=2)
    bullets = [
        "Include the sender's full name, address, and (above the NH disclosure threshold) occupation and employer in the wire memo.",
        "Anonymous contributions above the NH statutory threshold will be returned.",
        "Corporate-treasury contributions earmarked for specific candidates or bills will not be accepted.",
        "Foreign-national contributions are prohibited under federal law and will be rejected.",
        "After sending, email the wire confirmation to info@digitalfuturenh.com for a contribution receipt.",
    ]
    for b in bullets:
        p = doc.add_paragraph(b, style='List Bullet')
        p.paragraph_format.space_after = Pt(1)
        for r in p.runs:
            r.font.size = Pt(9)

    heading(doc, "Contact", size=11, space_before=8, space_after=2)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run("Christopher Maidment, Chair  ·  ")
    r.font.size = Pt(10); r.font.color.rgb = NAVY; r.font.bold = True
    r = p.add_run("540-598-1130 (m)  ·  info@digitalfuturenh.com")
    r.font.size = Pt(10); r.font.color.rgb = GRAY

    footer(doc,
        "Paid for by NH Digital Future PAC, 248 Carley Road, Peterborough, NH 03458. Chris Maidment, Chair. Not authorized by any candidate or candidate's committee. Contributions are not tax deductible.")

    out = OUT / 'DigitalFutureNH_Wire_Instructions.docx'
    doc.save(out)
    return out


def _kv_table(doc, rows):
    t = doc.add_table(rows=len(rows), cols=2)
    t.autofit = False
    t.columns[0].width = Inches(2.4)
    t.columns[1].width = Inches(4.1)
    for i, (k, v) in enumerate(rows):
        c0 = t.rows[i].cells[0]; c0.width = Inches(2.4)
        c1 = t.rows[i].cells[1]; c1.width = Inches(4.1)
        p0 = c0.paragraphs[0]; p0.paragraph_format.space_after = Pt(2)
        r0 = p0.add_run(k); r0.font.size = Pt(10); r0.font.bold = True; r0.font.color.rgb = NAVY
        p1 = c1.paragraphs[0]; p1.paragraph_format.space_after = Pt(2)
        r1 = p1.add_run(v); r1.font.size = Pt(10); r1.font.color.rgb = NAVY


def docx_to_pdf(docx_path):
    soffice = '/Applications/LibreOffice.app/Contents/MacOS/soffice'
    subprocess.run(
        [soffice, '--headless', '--convert-to', 'pdf', '--outdir', str(OUT), str(docx_path)],
        check=True, capture_output=True)
    return docx_path.with_suffix('.pdf')


if __name__ == '__main__':
    cl = build_cover_letter()
    wi = build_wire_instructions()
    print('DOCX written:')
    print(' ', cl)
    print(' ', wi)
    print('Converting to PDF...')
    for d in (cl, wi):
        p = docx_to_pdf(d)
        print('  ->', p)
