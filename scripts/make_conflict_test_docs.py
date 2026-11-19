"""Build the two Northwind policy-conflict test PDFs.

The documents are deliberately realistic two-page corporate artifacts: policy
clauses are mixed with a COO message, an org chart, service standards, office
details, people metrics, a procurement dashboard, a risk register, committee
minutes, glossaries and document history.  That non-policy material is there to
exercise extraction and retrieval without creating extra normative statements.

Every policy statement is rendered on one line.  The PDF parser joins physical
lines with newlines, so a one-line statement keeps the model's verbatim evidence
quote stable and avoids false rejection of an otherwise correct extraction.

Run:  .venv/bin/python scripts/make_conflict_test_docs.py
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "fixtures" / "conflict_testing"
MANIFESTS = OUT / "manifests"

# A4 portrait.
PAGE_W, PAGE_H = 595, 842
MARGIN_X = 46
CONTENT_W = PAGE_W - 2 * MARGIN_X
CONTENT_BOTTOM = 786

INK = (0.12, 0.15, 0.19)
MUTED = (0.39, 0.44, 0.50)
ACCENT = (0.05, 0.31, 0.32)
ACCENT_SOFT = (0.90, 0.95, 0.94)
LINE = (0.80, 0.84, 0.86)
TABLE_HEAD = (0.93, 0.95, 0.96)
WARN = (0.55, 0.36, 0.09)

BODY = pymupdf.Font("helv")
BOLD = pymupdf.Font("hebo")
ITALIC = pymupdf.Font("heit")


def wrap(text: str, font: pymupdf.Font, size: float, width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if font.text_length(trial, size) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


class Layout:
    def __init__(self, title: str, subtitle: str, *, document_code: str, classification: str):
        self.doc = pymupdf.open()
        self.title = title
        self.subtitle = subtitle
        self.document_code = document_code
        self.classification = classification
        self.page = None
        self.y = 0.0
        self.page_number = 0
        self.new_page(first=True)

    # ------------------------------------------------------------------ pages
    def new_page(self, *, first: bool = False) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.page_number += 1
        page = self.page

        # Brand mark and running header.
        page.draw_rect(
            pymupdf.Rect(MARGIN_X, 30, MARGIN_X + 23, 53),
            color=None,
            fill=ACCENT,
            radius=0.18,
        )
        page.insert_text((MARGIN_X + 7.0, 46.5), "N", fontsize=13, fontname="hebo", color=(1, 1, 1))
        page.insert_text((MARGIN_X + 32, 41.5), "NORTHWIND TRADING BANGLADESH", fontsize=7.6, fontname="hebo", color=INK)
        page.insert_text((MARGIN_X + 32, 50.0), self.document_code, fontsize=6.6, fontname="helv", color=MUTED)
        label = self.classification.upper()
        label_width = BOLD.text_length(label, 6.4)
        page.insert_text((PAGE_W - MARGIN_X - label_width, 41.5), label, fontsize=6.4, fontname="hebo", color=WARN)
        page.draw_line(
            pymupdf.Point(MARGIN_X, 61),
            pymupdf.Point(PAGE_W - MARGIN_X, 61),
            color=LINE,
            width=0.7,
        )

        if first:
            self.y = 92.0
        else:
            page.insert_text(
                (MARGIN_X, 76),
                f"{self.title}  |  continued",
                fontsize=8.0,
                fontname="hebo",
                color=MUTED,
            )
            self.y = 92.0

    def finish(self) -> bytes:
        total = self.doc.page_count
        for index, page in enumerate(self.doc, start=1):
            page.draw_line(
                pymupdf.Point(MARGIN_X, 802),
                pymupdf.Point(PAGE_W - MARGIN_X, 802),
                color=LINE,
                width=0.6,
            )
            page.insert_text(
                (MARGIN_X, 814),
                "Northwind Trading Bangladesh  |  " + self.classification,
                fontsize=6.6,
                fontname="helv",
                color=MUTED,
            )
            page.insert_text(
                (PAGE_W - MARGIN_X - 42, 814),
                f"Page {index} of {total}",
                fontsize=6.6,
                fontname="helv",
                color=MUTED,
            )
        assert total == 2, f"{self.title}: generated {total} pages (target 2)"
        return self.doc.tobytes(garbage=4, deflate=True)

    # --------------------------------------------------------------- elements
    def ensure(self, height: float) -> None:
        if self.y + height > CONTENT_BOTTOM:
            self.new_page()

    def page_break(self) -> None:
        if self.y > 100:
            self.new_page()

    def title_block(self) -> None:
        page = self.page
        page.insert_text((MARGIN_X, self.y + 21), self.title, fontsize=22, fontname="hebo", color=INK)
        self.y += 31
        page.insert_text((MARGIN_X, self.y + 8), self.subtitle, fontsize=9.6, fontname="helv", color=ACCENT)
        self.y += 19
        page.insert_text(
            (MARGIN_X, self.y + 7),
            "Version 1.0  |  Effective 1 January 2026  |  Bangladesh",
            fontsize=7.4,
            fontname="helv",
            color=MUTED,
        )
        self.y += 18

    def section(self, number: str, title: str) -> None:
        self.ensure(30)
        self.y += 5
        # The PDF parser recognizes numbered headings as "5 Title", without a
        # trailing period after the section number. "5.1 Clause" still works.
        label = f"{number} {title}" if number else title
        self.page.insert_text((MARGIN_X, self.y + 9.5), label, fontsize=10.6, fontname="hebo", color=ACCENT)
        self.y += 14
        self.page.draw_line(
            pymupdf.Point(MARGIN_X, self.y + 1),
            pymupdf.Point(PAGE_W - MARGIN_X, self.y + 1),
            color=LINE,
            width=0.55,
        )
        self.y += 8

    def para(self, text: str, *, size: float = 8.25, leading: float = 10.7,
             color: tuple[float, float, float] = INK, indent: float = 0.0,
             gap: float = 5.0, font: pymupdf.Font = BODY, fontname: str = "helv") -> None:
        lines = wrap(text, font, size, CONTENT_W - indent)
        self.ensure(len(lines) * leading + gap)
        for line in lines:
            self.page.insert_text(
                (MARGIN_X + indent, self.y + size),
                line,
                fontsize=size,
                fontname=fontname,
                color=color,
            )
            self.y += leading
        self.y += gap

    def note(self, text: str, *, label: str = "Note") -> None:
        size = 7.9
        leading = 10.2
        lines = wrap(text, BODY, size, CONTENT_W - 20)
        height = len(lines) * leading + 12
        self.ensure(height + 4)
        rect = pymupdf.Rect(MARGIN_X, self.y, PAGE_W - MARGIN_X, self.y + height)
        self.page.draw_rect(rect, color=None, fill=ACCENT_SOFT, radius=0.02)
        self.page.draw_rect(rect, color=ACCENT, fill=None, width=1.4, radius=0.02)
        y = self.y + 8
        self.page.insert_text((MARGIN_X + 10, y + 7), label, fontsize=7.0, fontname="hebo", color=ACCENT)
        self.page.insert_text((MARGIN_X + 10 + BOLD.text_length(label, 7.0) + 7, y + 7),
                              lines[0], fontsize=size, fontname="helv", color=INK)
        y += leading
        for line in lines[1:]:
            self.page.insert_text((MARGIN_X + 10, y + 7), line, fontsize=size, fontname="helv", color=INK)
            y += leading
        self.y += height + 6

    def clause(self, number: str, text: str, *, size: float = 7.95) -> None:
        line = f"{number} {text}"
        width = BODY.text_length(line, size)
        if width > CONTENT_W:
            size = max(7.0, size * CONTENT_W / width)
        self.ensure(size * 1.65)
        self.page.insert_text(
            (MARGIN_X, self.y + size),
            line,
            fontsize=size,
            fontname="helv",
            color=INK,
        )
        self.y += size * 1.62 + 2.0

    def table(self, headers: list[str], rows: list[list[str]], *,
              widths: list[float] | None = None,
              size: float = 7.1, pad: float = 3.6,
              caption: str | None = None) -> None:
        if widths is None:
            widths = [1.0 / len(headers)] * len(headers)
        assert len(widths) == len(headers)
        col_widths = [CONTENT_W * w for w in widths]
        leading = size * 1.32

        wrapped_rows: list[list[list[str]]] = []
        for row in rows:
            wrapped_rows.append([
                wrap(cell, BODY, size, col_widths[i] - 2 * pad) for i, cell in enumerate(row)
            ])
        header_lines = [
            wrap(cell, BOLD, size, col_widths[i] - 2 * pad) for i, cell in enumerate(headers)
        ]
        header_height = max(1, max(len(lines) for lines in header_lines)) * leading + 2 * pad
        row_heights = [
            max(1, max(len(lines) for lines in row)) * leading + 2 * pad for row in wrapped_rows
        ]
        caption_height = 13 if caption else 0
        total = caption_height + header_height + sum(row_heights) + 1

        self.ensure(total + 5)
        if caption:
            self.page.insert_text((MARGIN_X, self.y + 7.5), caption, fontsize=7.4, fontname="hebo", color=MUTED)
            self.y += caption_height

        top = self.y
        # Header band.
        self.page.draw_rect(
            pymupdf.Rect(MARGIN_X, top, PAGE_W - MARGIN_X, top + header_height),
            color=None,
            fill=TABLE_HEAD,
        )
        x = MARGIN_X
        for i, lines in enumerate(header_lines):
            y = top + pad
            for line in lines:
                self.page.insert_text((x + pad, y + size), line, fontsize=size, fontname="hebo", color=INK)
                y += leading
            x += col_widths[i]
        y = top + header_height

        for row_index, (row, height) in enumerate(zip(wrapped_rows, row_heights)):
            if row_index % 2 == 1:
                self.page.draw_rect(
                    pymupdf.Rect(MARGIN_X, y, PAGE_W - MARGIN_X, y + height),
                    color=None,
                    fill=(0.975, 0.98, 0.98),
                )
            x = MARGIN_X
            for i, lines in enumerate(row):
                cell_y = y + pad
                for line in lines:
                    self.page.insert_text((x + pad, cell_y + size), line, fontsize=size, fontname="helv", color=INK)
                    cell_y += leading
                x += col_widths[i]
            y += height
            self.page.draw_line(
                pymupdf.Point(MARGIN_X, y),
                pymupdf.Point(PAGE_W - MARGIN_X, y),
                color=LINE,
                width=0.4,
            )

        self.page.draw_rect(
            pymupdf.Rect(MARGIN_X, top, PAGE_W - MARGIN_X, y),
            color=LINE,
            fill=None,
            width=0.5,
        )
        self.y = y + 8


# --------------------------------------------------------------------------- content
COO_MESSAGE = (
    "Northwind moves goods and ideas across the region, and our people make that possible. "
    "This handbook sets out the standards we expect at work and the support you can expect from us. "
    "It is a practical reference, not a substitute for judgement. We review it every year with "
    "employee representatives, and we welcome questions at any time."
)

ABOUT = (
    "Northwind Trading Bangladesh is a logistics and consumer-goods company with 420 employees. "
    "We operate from Dhaka (head office), Chattogram (port operations) and Sylhet (regional sales). "
    "The company is organised into three business units: Freight, Consumer Goods and Digital Services."
)

MAINTENANCE = (
    "People & Culture owns this handbook. The intranet copy is the controlled version and is updated "
    "after each annual review. Printed copies are for reference only. Questions about a specific "
    "clause should go to the People & Culture helpdesk."
)

TRAVEL_INTRO = (
    "The travel desk arranges flights, hotels and ground transport. Claims are submitted through the "
    "expense system with receipts attached. The table below records the travel desk's service standards."
)

LEAVE_INTRO = (
    "Leave is recorded in the HR system and approved by your line manager. The people team publishes "
    "the leave calendar each November for the following year."
)

CONDUCT_INTRO = (
    "Our workplaces include offices, warehouses and client sites. Local safety instructions always "
    "take priority in an emergency."
)

DOC1_CLAUSES = {
    "3.1": "Employees must submit travel claims within 30 calendar days of returning.",
    "3.2": "Employees may submit travel claims up to 60 calendar days after returning.",
    "3.3": "For overseas travel, employees must submit travel claims within 60 calendar days.",
    "3.4": "Employees may claim economy-class airfare only; premium cabins are not reimbursable.",
    "4.1": "Full-time employees are entitled to 25 working days of annual leave each year.",
    "4.2": "Full-time employees are entitled to at most 20 working days of annual leave each year.",
    "5.1": "Warehouse employees must wear high-visibility vests and safety shoes on the loading floor.",
    "5.2": "Office-based employees must wear business casual attire in client-facing areas.",
}

DOC2_CLAUSES = {
    "2.1": "Employees may book premium economy airfare at company expense for all business flights.",
    "2.2": "Employees must stay in hotels rated four stars or higher on company business.",
    "2.3": "Employees travelling to high-risk countries must complete the security briefing first.",
    "3.1": "Employees must never send customer data to personal email accounts.",
    "3.2": "Employees may send customer data to personal email accounts when working remotely.",
    "3.3": "Employees must use passwords of at least 12 characters for all company systems.",
    "3.4": "Employees must use passwords of at least 16 characters for administrative accounts.",
    "3.5": "Employees may share customer data with approved vendors through the secure portal.",
    "3.6": "Employees must report suspected breaches to Security Operations within one hour.",
    "4.1": "Purchases above EUR 500 require written approval from the employee's manager.",
    "4.2": "Purchases up to EUR 2,000 may be ordered by any employee without prior approval.",
    "4.3": "Employees must obtain three written quotations for purchases above EUR 5,000.",
    "4.4": "Purchases above EUR 50,000 require approval from the Board Audit Committee.",
    "4.5": "Purchases above EUR 50,000 may use the Appendix C exception without board approval.",
    "5.1": "All visitors must sign in at reception and wear a visitor badge at all times.",
    "5.2": "Employees must not allow visitors into server rooms without approval from Security.",
    "5.3": "Contractors must complete a security induction before receiving an access card.",
}

DOC2_PURPOSE = (
    "This procedure supports the Northwind Information Security Policy and the Procurement Policy. "
    "It applies to all employees in Bangladesh and to contractors working on Northwind premises. "
    "Read it together with the group policies and the local delegation of authority. The procedure is "
    "maintained by Corporate Security and Procurement; the intranet copy is the controlled version."
)

SECURITY_INTRO = (
    "Security controls apply to company systems, customer records and physical sites. Report suspected "
    "incidents immediately; do not wait for a confirmed breach."
)

PROCUREMENT_INTRO = (
    "Purchasing follows the delegation of authority. The procurement team reviews open orders every "
    "Monday and publishes a monthly spend summary for budget owners."
)

PHYSICAL_INTRO = (
    "Reception controls access to every Northwind site. Visitors and contractors must follow the "
    "instructions of the security team while on the premises."
)

DOC1_TRAVEL_STANDARDS = [
    ["Standard", "Service level"],
    ["Booking confirmation", "Two working days after an approved request"],
    ["Hotel changes", "Handled by the travel desk before departure"],
    ["Receipt checks", "Finance reviews claims in the expense system"],
    ["Emergency support", "Available 24 hours through the duty manager"],
]

DOC1_ORG = [
    ["Function", "Led by", "People"],
    ["Executive Office", "Chief Executive Officer", "6"],
    ["Freight", "Chief Operating Officer", "148"],
    ["Consumer Goods", "Managing Director", "121"],
    ["Digital Services", "Chief Technology Officer", "55"],
    ["People & Culture", "Chief People Officer", "32"],
]

DOC1_LEAVE_GLANCE = [
    ["Topic", "Reference"],
    ["Full-time allowance", "See Section 4.1"],
    ["Part-time allowance", "Pro-rata to contracted hours"],
    ["Carry-forward", "Up to five working days"],
    ["Approval route", "Line manager in the HR system"],
]

DOC1_DIRECTORY = [
    ["Location", "Address", "Contact"],
    ["Dhaka head office", "Gulshan Avenue 12, Dhaka 1212", "Reception, extension 100"],
    ["Chattogram port office", "Port Road, Chattogram 4100", "Operations desk, extension 210"],
    ["Sylhet regional sales", "Zindabazar, Sylhet 3100", "Sales desk, extension 320"],
]

DOC1_METRICS = [
    ["Measure", "Result (2025)"],
    ["Average headcount", "420"],
    ["Voluntary attrition", "8.4%"],
    ["Internal promotions", "37"],
    ["Training hours per employee", "26"],
    ["Engagement survey participation", "91%"],
]

DOC2_SPEND = [
    ["Category", "Q3 2026 spend", "Change vs Q2"],
    ["Freight operations", "BDT 42.6m", "+3.1%"],
    ["Consumer goods", "BDT 28.1m", "-1.4%"],
    ["Digital services", "BDT 9.4m", "+6.8%"],
    ["Facilities", "BDT 6.2m", "+0.5%"],
]

DOC2_RISKS = [
    ["Risk", "Owner", "Rating", "Mitigation"],
    ["Personal email data leakage", "CISO", "High", "Data-loss rules and quarterly training"],
    ["Unapproved purchases", "CFO", "Medium", "Monthly spend review"],
    ["Visitor access to server rooms", "Head of Security", "Medium", "Badge audit and escort checks"],
    ["Vendor portal access", "Procurement lead", "Medium", "Quarterly access review"],
]

DOC2_MINUTES = (
    "The Security Steering Committee met on 12 November 2026 at Dhaka head office. Present: the CISO, "
    "the CFO, the Head of Security and the Procurement lead. The committee reviewed the Q3 phishing "
    "simulation results (12% click rate, down from 19%) and the monthly spend summary. Action items: "
    "Priya to update the visitor badge log by 30 November; Rafiq to review vendor portal access by "
    "15 December; Finance to publish the 2027 procurement calendar. The next meeting is in January."
)

DOC1_FAQ = [
    ("Where do I submit a travel claim?",
     "Use the expense system and attach the receipts. The travel desk can help with missing bookings."),
    ("Who approves annual leave?",
     "Your line manager approves leave in the HR system. The people team maintains the leave calendar."),
    ("Where is the controlled handbook?",
     "The intranet copy is controlled. Printed copies are for reference only."),
    ("How do I report a security incident?",
     "Follow the corporate security procedure on the intranet and contact the Security Operations Centre."),
]


def build_handbook() -> bytes:
    layout = Layout(
        "Employee Handbook 2026",
        "People, travel and workplace policies",
        document_code="People & Culture  |  Handbook 01",
        classification="Internal",
    )
    layout.title_block()
    layout.table(
        ["Document owner", "People & Culture", "Approved by", "Chief Operating Officer"],
        [
            ["Version", "1.0", "Effective from", "January 1, 2026"],
            ["Classification", "Internal", "Review cycle", "Annual"],
        ],
        widths=[0.16, 0.34, 0.16, 0.34],
        size=7.0,
    )

    layout.section("", "A message from the COO")
    layout.para(COO_MESSAGE, size=8.2, leading=10.6, color=INK, gap=4)

    layout.section("1", "About Northwind")
    layout.para(ABOUT, gap=3)
    layout.table(["Function", "Led by", "People"], DOC1_ORG[1:], widths=[0.30, 0.48, 0.22], size=7.0)

    layout.section("2", "How this handbook is maintained")
    layout.para(MAINTENANCE, gap=3)

    layout.section("3", "Travel and expenses")
    layout.para(TRAVEL_INTRO, gap=3)
    layout.clause("3.1", DOC1_CLAUSES["3.1"])
    layout.clause("3.2", DOC1_CLAUSES["3.2"])
    layout.clause("3.3", DOC1_CLAUSES["3.3"])
    layout.clause("3.4", DOC1_CLAUSES["3.4"])
    layout.table(["Standard", "Service level"], DOC1_TRAVEL_STANDARDS[1:], widths=[0.32, 0.68],
                 caption="Travel desk service standards", size=7.0)

    layout.page_break()
    layout.section("4", "Annual leave")
    layout.para(LEAVE_INTRO, gap=3)
    layout.clause("4.1", DOC1_CLAUSES["4.1"])
    layout.clause("4.2", DOC1_CLAUSES["4.2"])

    layout.section("5", "Workplace and conduct")
    layout.para(CONDUCT_INTRO, gap=3)
    layout.clause("5.1", DOC1_CLAUSES["5.1"])
    layout.clause("5.2", DOC1_CLAUSES["5.2"])

    layout.section("6", "Office directory")
    layout.table(["Location", "Address", "Contact"], DOC1_DIRECTORY[1:], widths=[0.24, 0.46, 0.30], size=6.9)

    layout.section("7", "People metrics (2025)")
    layout.table(["Measure", "Result (2025)"], DOC1_METRICS[1:], widths=[0.68, 0.32], size=6.9)

    layout.section("8", "Glossary")
    for term, definition in [
        ("FTE", "Full-time equivalent; a 40-hour contracted week."),
        ("Travel desk", "The team that books flights, hotels and ground transport."),
        ("Working day", "Monday to Friday, excluding public holidays in Bangladesh."),
        ("Expense system", "The intranet application used to submit claims and receipts."),
    ]:
        layout.para(f"{term}. {definition}", size=7.9, leading=10.1, gap=1.5)

    layout.section("9", "Frequently asked questions")
    for question, answer in DOC1_FAQ:
        layout.para(question, size=8.0, leading=10.2, gap=0.5, font=BOLD, fontname="hebo")
        layout.para(answer, size=7.9, leading=10.1, gap=3.0)

    layout.section("10", "Document history")
    layout.table(
        ["Version", "Date", "Change"],
        [
            ["1.0", "15-Dec-2025", "Annual refresh approved by the COO"],
            ["0.9", "2-Nov-2025", "Draft for employee consultation"],
        ],
        widths=[0.14, 0.24, 0.62],
        size=6.9,
    )
    return layout.finish()


def build_procedure() -> bytes:
    layout = Layout(
        "Corporate Security & Procurement",
        "Information security, purchasing and travel security",
        document_code="Corporate Security  |  Procedure 04",
        classification="Confidential",
    )
    layout.title_block()
    layout.table(
        ["Document owner", "Corporate Security", "Approved by", "Chief Financial Officer"],
        [
            ["Version", "1.0", "Effective from", "January 1, 2026"],
            ["Classification", "Confidential", "Review cycle", "Every six months"],
        ],
        widths=[0.18, 0.32, 0.18, 0.32],
        size=7.0,
    )

    layout.section("1", "Purpose and scope")
    layout.para(DOC2_PURPOSE, gap=3)

    layout.section("2", "Business travel security")
    layout.para(
        "The security team publishes country risk ratings each quarter. The travel desk confirms that "
        "a briefing is booked before releasing international tickets.",
        gap=3,
    )
    layout.clause("2.1", DOC2_CLAUSES["2.1"])
    layout.clause("2.2", DOC2_CLAUSES["2.2"])
    layout.clause("2.3", DOC2_CLAUSES["2.3"])

    layout.section("3", "Information security")
    layout.para(SECURITY_INTRO, gap=3)
    layout.clause("3.1", DOC2_CLAUSES["3.1"])
    layout.clause("3.2", DOC2_CLAUSES["3.2"])
    layout.clause("3.3", DOC2_CLAUSES["3.3"])
    layout.clause("3.4", DOC2_CLAUSES["3.4"])
    layout.clause("3.5", DOC2_CLAUSES["3.5"])
    layout.clause("3.6", DOC2_CLAUSES["3.6"])

    layout.section("4", "Procurement and purchasing")
    layout.para(PROCUREMENT_INTRO, gap=3)
    layout.clause("4.1", DOC2_CLAUSES["4.1"])
    layout.clause("4.2", DOC2_CLAUSES["4.2"])
    layout.clause("4.3", DOC2_CLAUSES["4.3"])
    layout.clause("4.4", DOC2_CLAUSES["4.4"])
    layout.clause("4.5", DOC2_CLAUSES["4.5"])

    layout.section("5", "Physical security and visitors")
    layout.para(PHYSICAL_INTRO, gap=3)
    layout.clause("5.1", DOC2_CLAUSES["5.1"])
    layout.clause("5.2", DOC2_CLAUSES["5.2"])
    layout.clause("5.3", DOC2_CLAUSES["5.3"])

    layout.page_break()
    layout.section("6", "Procurement spend dashboard")
    layout.table(["Category", "Q3 2026 spend", "Change vs Q2"], DOC2_SPEND[1:], widths=[0.44, 0.30, 0.26],
                 caption="Management information, not a policy statement", size=6.9)

    layout.section("7", "Risk register excerpt")
    layout.table(["Risk", "Owner", "Rating", "Mitigation"], DOC2_RISKS[1:],
                 widths=[0.34, 0.20, 0.12, 0.34], size=6.7)
    layout.para("The full register is reviewed by the Audit Committee each quarter.", size=7.8, leading=10.0, gap=3)

    layout.section("8", "Security Steering Committee minutes")
    layout.para(DOC2_MINUTES, size=7.9, leading=10.3, gap=3)

    layout.section("9", "Glossary")
    for term, definition in [
        ("CISO", "Chief Information Security Officer."),
        ("DLP", "Data-loss prevention controls on company systems."),
        ("SOC", "Security Operations Centre; the team that handles incidents."),
        ("Appendix C", "The Audit Committee's exception schedule, maintained separately."),
    ]:
        layout.para(f"{term}. {definition}", size=7.8, leading=10.0, gap=1.5)

    layout.section("10", "Document history")
    layout.table(
        ["Version", "Date", "Change"],
        [
            ["1.0", "18-Dec-2025", "Procedure approved by the CFO"],
            ["0.8", "5-Nov-2025", "Consultation draft with Security and Finance"],
        ],
        widths=[0.14, 0.24, 0.62],
        size=6.9,
    )

    layout.section("11", "Contacts")
    layout.para(
        "Procedure owner: Corporate Security. Procurement helpdesk: extension 240. "
        "Security Operations Centre: extension 911 or soc@northwind.example.",
        size=7.9,
        leading=10.2,
        gap=0,
    )
    return layout.finish()


# --------------------------------------------------------------------------- manifests
def manifest(source_identity: str, authority: str, family: str, published: str) -> dict:
    return {
        "schema_version": "1",
        "tenant_id": "meridian_demo",
        "region": "DHAKA",
        "source_identity": source_identity,
        "version_label": "v1",
        "source_type": "pdf",
        "subject": "general_policy",
        "authority": authority,
        "policy_family": family,
        "scope": {
            "kind": "policy",
            "description": "All Northwind Trading Bangladesh employees",
            "attributes": {},
        },
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": None,
        "publication_time": published,
        "sensitivity": "demo_shareable",
        "permissions": {"office_export": False, "hosted_model": True},
    }


# --------------------------------------------------------------------------- expectations
EXPECTED = {
    "description": (
        "Expected outcomes for the two Northwind conflict-test PDFs. Conflict matches are "
        "model-assisted and require human review; decoys must not become conflict findings."
    ),
    "upload_order": [
        "northwind_employee_handbook_2026",
        "northwind_security_procurement_procedure_2026",
    ],
    "scope_note": (
        "Upload both documents with the same applicability (All Northwind Trading Bangladesh "
        "employees) and the same effective date (1 January 2026). Do not use Replace; these are "
        "independent documents, not versions of one policy."
    ),
    "expected_conflicts": [
        {
            "id": "travel_claim_deadline",
            "documents": ["northwind_employee_handbook_2026"],
            "conflict_type": "deadline versus permission",
            "left_terms": ["within 30 calendar days"],
            "right_terms": ["up to 60 calendar days"],
            "expected_finding_type": "contradiction",
            "expected_severity": "review",
            "why": "A domestic claim submitted on day 45 satisfies the 60-day permission but violates the 30-day requirement.",
        },
        {
            "id": "annual_leave_entitlement",
            "documents": ["northwind_employee_handbook_2026"],
            "conflict_type": "numeric entitlement",
            "left_terms": ["25 working days"],
            "right_terms": ["at most 20 working days"],
            "expected_finding_type": "contradiction",
            "expected_severity": "review",
            "why": "The same full-time employee cannot be entitled to 25 days and capped at 20 days in the same year.",
        },
        {
            "id": "personal_email_customer_data",
            "documents": ["northwind_security_procurement_procedure_2026"],
            "conflict_type": "prohibition versus permission",
            "left_terms": ["never send customer data"],
            "right_terms": ["may send customer data", "working remotely"],
            "expected_finding_type": "contradiction",
            "expected_severity": "review",
            "why": "The procedure both prohibits and permits the same channel for the same customer data.",
        },
        {
            "id": "purchase_approval_threshold",
            "documents": ["northwind_security_procurement_procedure_2026"],
            "conflict_type": "approval threshold",
            "left_terms": ["EUR 500", "written approval"],
            "right_terms": ["up to EUR 2,000", "without prior approval"],
            "expected_finding_type": "contradiction",
            "expected_severity": "review",
            "why": "A EUR 1,500 purchase is above the approval threshold but also inside the no-approval allowance.",
        },
        {
            "id": "cross_document_airfare_class",
            "documents": [
                "northwind_employee_handbook_2026",
                "northwind_security_procurement_procedure_2026",
            ],
            "conflict_type": "policy versus procedure / reimbursement class",
            "left_terms": ["economy-class airfare only"],
            "right_terms": ["premium economy"],
            "expected_finding_type": "compliance_gap",
            "expected_severity": "review",
            "why": "The handbook makes premium cabins non-reimbursable while the procedure allows premium economy at company expense for every business flight.",
        },
    ],
    "expected_needs_review": [
        {
            "id": "appendix_c_exception",
            "documents": ["northwind_security_procurement_procedure_2026"],
            "conflict_type": "missing exception context",
            "left_terms": ["Board Audit Committee"],
            "right_terms": ["Appendix C exception"],
            "expected_finding_type": "needs_review",
            "why": "Appendix C is not supplied, so a reviewer must decide whether the exception applies; this must not be published as a confirmed conflict.",
        }
    ],
    "expected_no_conflict": [
        {
            "id": "overseas_deadline_exception",
            "documents": ["northwind_employee_handbook_2026"],
            "left_terms": ["within 30 calendar days"],
            "right_terms": ["For overseas travel"],
            "why": "The overseas clause is an explicit exception; the 60-day deadline for overseas trips is compatible with the 30-day general rule.",
        },
        {
            "id": "password_minimums",
            "documents": ["northwind_security_procurement_procedure_2026"],
            "left_terms": ["at least 12 characters"],
            "right_terms": ["at least 16 characters"],
            "why": "Both minimums can hold: all accounts need 12 characters and administrative accounts need 16.",
        },
        {
            "id": "secure_transfer_portal",
            "documents": ["northwind_security_procurement_procedure_2026"],
            "left_terms": ["personal email accounts"],
            "right_terms": ["approved vendors", "secure portal"],
            "why": "Approved vendors using a controlled portal are a different channel from personal email.",
        },
        {
            "id": "warehouse_dress",
            "documents": ["northwind_employee_handbook_2026"],
            "left_terms": ["high-visibility vests"],
            "right_terms": ["business casual attire"],
            "why": "Warehouse safety clothing and office dress code apply to different roles and locations.",
        },
    ],
    "non_policy_content": [
        "COO message",
        "company overview and org chart",
        "handbook maintenance and controlled-copy note",
        "travel desk service standards",
        "leave-at-a-glance table",
        "office directory",
        "people metrics",
        "glossary",
        "FAQ",
        "document history",
        "procurement spend dashboard",
        "risk register excerpt",
        "Security Steering Committee minutes",
        "contacts",
    ],
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)

    handbook_path = OUT / "northwind_employee_handbook_2026.pdf"
    procedure_path = OUT / "northwind_security_procurement_procedure_2026.pdf"
    handbook_path.write_bytes(build_handbook())
    procedure_path.write_bytes(build_procedure())

    (MANIFESTS / "northwind_employee_handbook_2026.json").write_text(
        json.dumps(manifest(
            "northwind_employee_handbook_2026", "policy", "people_travel",
            "2025-12-15T00:00:00Z",
        ), indent=2) + "\n",
        encoding="utf-8",
    )
    (MANIFESTS / "northwind_security_procurement_procedure_2026.json").write_text(
        json.dumps(manifest(
            "northwind_security_procurement_procedure_2026", "procedure",
            "corporate_security_procurement", "2025-12-18T00:00:00Z",
        ), indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / "expected_findings.json").write_text(
        json.dumps(EXPECTED, indent=2) + "\n",
        encoding="utf-8",
    )

    # Verify the artifacts the rest of the test relies on.
    from meridian.ingestion.pdf import parse_pdf_bytes

    for path, expected_clauses in (
        (handbook_path, DOC1_CLAUSES),
        (procedure_path, DOC2_CLAUSES),
    ):
        with pymupdf.open(path) as document:
            page_count = document.page_count
        assert page_count == 2, f"{path.name}: {page_count} pages"
        parsed = parse_pdf_bytes(path.read_bytes())
        text = "\n".join(clause.text for clause in parsed.clauses)
        missing = [statement for statement in expected_clauses.values() if statement not in text]
        if missing:
            raise SystemExit(f"{path.name}: statements missing from parsed text:\n" + "\n".join(missing))
        print(f"{path.name}: {page_count} pages, {len(parsed.clauses)} clauses, "
              f"{len(expected_clauses)} policy statements verified")

    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
