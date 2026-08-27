"""A fully-formed briefing used by the verification and export tests.

Handwritten rather than model-generated so the tests are deterministic and can
run with no API key. The content mirrors what a correct briefing over the
synthetic pack should look like, including one deliberately invalid citation.
"""

from __future__ import annotations

from boardlens.brief.schema import BoardBriefing

BRIEFING = BoardBriefing.model_validate(
    {
        "meeting_context": (
            "The 119th board meeting of Meridian Industries Limited covers the quarter "
            "ended 30 June 2026. The pack seeks approval for two capital commitments "
            "against a quarter in which margins contracted sharply and net debt rose."
        ),
        "critical_risks": [
            {
                "title": "Covenant headroom on debt service coverage",
                "severity": "critical",
                "why_now": (
                    "DSCR fell to 1.28x against a covenant floor of 1.20x, from 1.61x at "
                    "31 March 2026. The pack simultaneously seeks approval for INR 470 cr "
                    "of new commitments, of which INR 260 cr is debt-funded."
                ),
                "exposure": "Headroom of 0.08x on a covenant governing INR 1,336 cr of gross borrowings.",
                "management_position": "The deck reports the ratio but offers no commentary on the trend.",
                "gap": "No sensitivity showing DSCR after the proposed borrowings is provided.",
                "evidence": ["c0010", "c0015"],
            },
            {
                "title": "Regulatory action at the Nashik plant",
                "severity": "high",
                "why_now": (
                    "A show-cause notice was received on 2 July 2026 contemplating suspension "
                    "of operations at the affected line, and a reply falls due within 30 days."
                ),
                "exposure": "Maximum penalty INR 12 cr, plus a possible direction to suspend the line.",
                "management_position": "Listed in the risk update; no reply strategy is set out.",
                "gap": "The pack does not quantify the revenue at risk if the line is suspended.",
                "evidence": ["c0009", "c0023"],
            },
            {
                "title": "Repeat control failure in procurement",
                "severity": "high",
                "why_now": (
                    "The segregation-of-duties observation has now recurred across three audit "
                    "cycles, and its target date has moved to 31 March 2027."
                ),
                "exposure": "Vendor master creation and purchase order release remain with the same users.",
                "management_position": "Remediation is deferred pending the ERP authorisation redesign.",
                "gap": "No interim compensating control is described.",
                "evidence": ["c0026"],
            },
        ],
        "unresolved_actions": [
            {
                "action": "The CFO to place an ageing analysis of receivables above 180 days with a recovery plan for the ten largest overdue accounts.",
                "owner": "Chief Financial Officer",
                "raised_at": "118th meeting, 14 May 2026",
                "committed_date": "next meeting",
                "status": "open",
                "status_basis": "The MIS reports the 180-day balance at INR 78 cr but the pack contains no ageing analysis or recovery plan.",
                "ageing_cycles": 1,
                "evidence": ["c0014"],
            },
            {
                "action": "The IT security roadmap and indicative capital outlay to be placed before the Board.",
                "owner": "Managing Director",
                "raised_at": "118th meeting, 14 May 2026",
                "committed_date": "next meeting",
                "status": "unclear",
                "status_basis": "The current pack does not address the IT security roadmap.",
                "ageing_cycles": 1,
                "evidence": [],
            },
            {
                "action": "Standardise the ESG disclosure framework across all subsidiaries.",
                "owner": "Chief Sustainability Officer",
                "raised_at": "116th meeting, 12 February 2026",
                "committed_date": "30 June 2026",
                "status": "unclear",
                "status_basis": "Outstanding since February 2026; the current pack is silent on it.",
                "ageing_cycles": 2,
                "evidence": [],
            },
            {
                "action": "Obtain an independent valuation opinion for the Kalyani acquisition and revert with a revised proposal.",
                "owner": "Managing Director",
                "raised_at": "118th meeting, 14 May 2026",
                "committed_date": "not recorded",
                "status": "in_progress",
                "status_basis": "A revised proposal is tabled, but the speaker notes record the valuation opinion as still awaited.",
                "ageing_cycles": 1,
                "evidence": ["c0006"],
            },
            {
                "action": "Circulate a report on cyber insurance coverage and its adequacy to directors within thirty days.",
                "owner": "Chief Information Officer",
                "raised_at": "118th meeting, 14 May 2026",
                "committed_date": "within 30 days",
                "status": "open",
                "status_basis": "The risk register states cover of INR 25 cr but no adequacy assessment was circulated.",
                "ageing_cycles": 1,
                "evidence": ["c0022"],
            },
        ],
        "performance_changes": [
            {
                "metric": "EBITDA margin",
                "movement": "14.2% in Q1 FY27 against 17.8% in Q4 FY26",
                "direction": "deterioration",
                "materiality": "A 360bp contraction in one quarter, against a covenant structure with narrowing headroom.",
                "explanation_given": "The deck attributes it to the INR 32 cr Nashik inventory write-down; the MIS also shows realisation down 2.4% and finance costs up 24%.",
                "evidence": ["c0002", "c0013"],
            },
            {
                "metric": "Receivables over 180 days",
                "movement": "INR 78 cr at 30 June 2026 against INR 41 cr at 31 March 2026",
                "direction": "deterioration",
                "materiality": "A 90% increase in one quarter on a balance the board already flagged in May.",
                "explanation_given": "No explanation is given in the pack.",
                "evidence": ["c0014"],
            },
            {
                "metric": "Net debt",
                "movement": "INR 1,240 cr against INR 890 cr at 31 March 2026",
                "direction": "deterioration",
                "materiality": "Net debt to EBITDA moved from 1.11x to 1.72x against a cap of 2.50x.",
                "explanation_given": "The deck states the figure without attributing the increase.",
                "evidence": ["c0014", "c0015"],
            },
        ],
        "management_questions": [
            {
                "question": "What is the projected DSCR for each of the next four quarters after the Kalyani and Nashik line 3 commitments are drawn?",
                "rationale": "Headroom is 0.08x today and the pack seeks approval for INR 260 cr of new debt without a post-drawdown sensitivity.",
                "directed_to": "CFO",
                "priority": "critical",
                "evidence": ["c0010", "c0007"],
            },
            {
                "question": "Internal audit says the slow-moving condition was visible in the December 2025 ageing report. Why was the provision taken only in Q1 FY27?",
                "rationale": "The timing determines whether prior quarters' reported margins were overstated.",
                "directed_to": "CFO",
                "priority": "high",
                "evidence": ["c0027"],
            },
            {
                "question": "What revenue is at risk if the Pollution Control Board directs suspension of the affected Nashik line, and what is the reply strategy?",
                "rationale": "The notice contemplates suspension and a reply is due within 30 days; neither is quantified in the pack.",
                "directed_to": "Managing Director",
                "priority": "high",
                "evidence": ["c0023"],
            },
            {
                "question": "Sales headcount has fallen from 240 to 198 while realisation is down 2.4%. Is this a planned reduction or attrition?",
                "rationale": "The deck reports both movements without connecting or explaining them.",
                "directed_to": "Chief Commercial Officer",
                "priority": "medium",
                "evidence": ["c0004"],
            },
            {
                "question": "The Nashik line 3 payback assumes realisation recovers to FY26 levels from H2 FY27. What supports that assumption?",
                "rationale": "Realisation is currently falling and two large customers have just renegotiated pricing.",
                "directed_to": "CFO",
                "priority": "high",
                "evidence": ["c0007"],
            },
        ],
        "decisions_required": [
            {
                "decision": "Acquisition of a 74% equity stake in Kalyani Auto Components Private Limited at an enterprise value of INR 385 cr.",
                "proposed_by": "Managing Director",
                "financial_impact": "INR 385 cr enterprise value, funded INR 260 cr debt and INR 125 cr internal accruals.",
                "approval_basis": "Management recommendation, subject to receipt of an independent valuation opinion.",
                "readiness": "The board is not equipped to approve unconditionally: the independent valuation opinion the board directed in May has not been received, and the value has risen from INR 340 cr to INR 385 cr without explanation.",
                "considerations": "The board's own May direction made the valuation opinion a precondition; approving before receipt would set aside that direction.",
                "evidence": ["c0005", "c0006"],
            },
            {
                "decision": "Capital expenditure of INR 210 cr on Nashik line 3.",
                "proposed_by": "Management",
                "financial_impact": "INR 210 cr over 18 months; indicative payback 5.5 years.",
                "approval_basis": "The capital expenditure paper in the board deck.",
                "readiness": "The payback rests on a realisation recovery assumption the pack does not support.",
                "considerations": "The site is subject to a live regulatory notice contemplating suspension of operations.",
                "evidence": ["c0007", "c9999"],
            },
        ],
        "coverage_note": (
            "The full pack was parsed and assessed. Prior minutes for the 118th and 117th "
            "meetings were available; minutes for meetings before February 2026 were not "
            "supplied, so actions raised earlier than that are not covered."
        ),
    }
)
