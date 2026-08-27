# The Board Briefing template

BRD Phase 1 deliverable: the structure every briefing follows, and the editorial
standard behind it. The schema in `backend/boardlens/brief/schema.py` is the
machine-readable version of this document — the two must stay in step.

---

## Editorial standard

The reader is an experienced director with limited preparation time. They do not
need the pack summarised back to them; they need the small number of things that
should change how they spend the meeting. Everything below follows from that.

- **Independent, not adversarial.** The briefing serves the board, not
  management — but it does not manufacture concern where the pack supports
  management's position.
- **Specific over comprehensive.** One quantified finding beats five general
  ones. "Receivables over 180 days rose from INR 41 cr to INR 78 cr", not
  "working capital has deteriorated".
- **The pack's own vocabulary.** Line items, entities and committees are named
  as the pack names them, so the director can match the briefing to the papers
  in front of them.
- **Figures reproduced, never restated.** No conversion, no annualising, no
  re-basing.
- **Absence is a finding.** "The pack gives no explanation for the 360bp margin
  decline" is more useful than a plausible explanation constructed to fill the
  gap.
- **Every statement is traceable.** Each item carries chunk IDs that resolve to
  a document and page. Anything that cannot be supported is not said.

---

## Structure

Fixed, in this order. Section counts follow the BRD.

### Meeting context
Two to four sentences: the company, the meeting, the period covered, and what
the pack is principally about.

### 1. Critical risks — *exactly three*

Not the three largest in the risk register: the three that most warrant board
time **at this meeting**. A well-managed large risk may not make the list; a
smaller risk that has just changed state may.

| Field | Content |
|---|---|
| Title | Under 12 words |
| Severity | critical / high / medium / low |
| Why now | Why this demands attention at this meeting rather than as a standing concern |
| Exposure | Quantified where the pack allows; "not quantified in the pack" otherwise |
| Management position | What the pack says, or "not addressed in the pack" |
| What the pack does not say | The gap the board should notice |

### 2. Unresolved actions — *exactly five*

Drawn from the reconciled action register, chosen by **consequence, not age**.
The complete register is annexed to every export, so these five are the ones
that need airtime.

| Field | Content |
|---|---|
| Action | The board's own wording, not paraphrased |
| Owner | As recorded; "not recorded" if the minutes gave none |
| Raised / committed | As recorded |
| Status | open / in progress / completed / superseded / **not addressed in this pack** |
| Basis for status | What in the *current* pack shows it was or was not closed |
| Cycles open | How many meeting cycles it has been carried |

**On `not addressed in this pack`:** this is the most important status the
briefing can assign. It means the board directed something and the current pack
is silent on it — the item has not been reported back. Such items carry no
citation, because there is nothing to cite; that is the point, and the
verification pass does not penalise it.

### 3. Material performance changes — *three to six*

Materiality is relative to this business, not absolute.

| Field | Content |
|---|---|
| Metric | Named as the pack names it |
| Movement | Both figures **and** the basis of comparison |
| Direction | improvement / deterioration / mixed / neutral |
| Why it matters | Scale, covenant proximity, guidance impact, or trend break |
| Explanation offered | Management's explanation, or "no explanation given in the pack" |

An unexplained material movement is itself a finding.

### 4. Questions for management — *five to eight*

The sharpest output in the briefing. Each must be:

- **Answerable in the room** — not rhetorical, not a research project.
- **Specific enough that a prepared executive cannot deflect it.**
- **Grounded in something in the pack.**

A question that could be asked of any company at any meeting does not belong.
Each carries the role best placed to answer (CFO, CRO, MD) and a priority.

> *Example of the standard:* "What is the projected DSCR for each of the next
> four quarters after the Kalyani and Nashik line 3 commitments are drawn?" —
> not "How is the company managing its debt?"

### 5. Decisions required — *all of them*

Every decision the pack puts to this meeting.

| Field | Content |
|---|---|
| Decision | As the pack frames it |
| Proposed by | Who is putting it to the board |
| Financial impact | Quantified, or "not quantified in the pack" |
| Basis for approval | What the board is asked to rely on |
| **Is the board equipped to decide** | Whether the pack contains what is needed; names what is missing if not |
| Governance considerations | Related-party angle, conflicts, statutory approval, disclosure obligation, or "none identified" |

The readiness field is what distinguishes this from an agenda. A board being
asked to approve an acquisition without the independent valuation it directed at
the last meeting should be told so before the item is called.

### Coverage and limitations

What could not be assessed and why: unparsed scans, absent prior minutes,
documents that reached synthesis only as a digest. "Full pack assessed" appears
only when it is genuinely true.

A director who knows the limits of the briefing trusts the rest of it.

---

## Annexures

Present in every DOCX and PDF export.

- **Annexure A — Complete action register.** Every tracked action for this
  board, open and closed, with owner, dates, status and cycles open. Section 2
  is a selection; this is the whole.
- **Annexure B — Source index.** Every reference used in the briefing, with the
  passage it was drawn from.

Any statement whose citation did not resolve is listed under *Statements
requiring reviewer attention* and shown in red in both exports. It is retained
rather than deleted, so the reviewer judges it — and it must be confirmed or
removed before the briefing is circulated to directors.

---

## Review before circulation

BoardLens produces a **draft**. The company secretary reviews it, resolves any
flagged statements, and circulates. The classification chosen at pack creation
is stamped on every page of the result.
