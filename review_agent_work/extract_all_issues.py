#!/usr/bin/env python3
"""
Extract ALL findings (CRITICAL, HIGH, MEDIUM, LOW) from every per-file
review markdown under File_review/GROUP_*/  and write:
  - FULL_ISSUE_REGISTRY.md   (markdown table)
  - FULL_ISSUE_REGISTRY.csv  (CSV)

Run from the review_agent_work/ directory:
    python3 extract_all_issues.py
"""

import csv
import os
import re
from pathlib import Path

BASE = Path(__file__).parent
REVIEW_ROOT = BASE / "File_review"

# Map folder name → group number
GROUP_NUM = {
    "GROUP_01_IR_Core": 1,
    "GROUP_02_Node_Base": 2,
    "GROUP_03_Registry_Discovery": 3,
    "GROUP_04_Plugin_Ecosystem": 4,
    "GROUP_05_Planner": 5,
    "GROUP_06_Execution_Runtime": 6,
    "GROUP_07_Observability_Storage": 7,
    "GROUP_08_Platform_Infra": 8,
    "GROUP_09_SDK_CLI": 9,
    "GROUP_10_API": 10,
    "GROUP_11_MCP": 11,
    "GROUP_12_Domain_Models": 12,
    "GROUP_13_Audio_Plugins_Batch_1": 13,
    "GROUP_14_Audio_Plugins_Batch_2": 14,
    "GROUP_15_Audio_Plugins_Batch_3": 15,
    "GROUP_16_Common_Plugins": 16,
}

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# Regex to find a finding block.
# Each block starts with a line of dashes, then FILE:/FUNCTION:/CATEGORY:/SEVERITY:
# then more dashes, then the body sections.
BLOCK_RE = re.compile(
    r"-{20,}\s*\n"                          # opening dashes
    r"FILE:\s*(.+?)\n"                      # FILE:
    r"FUNCTION:\s*(.+?)\n"                  # FUNCTION:
    r"CATEGORY:\s*(.+?)\n"                  # CATEGORY:
    r"SEVERITY:\s*(CRITICAL|HIGH|MEDIUM|LOW)\s*\n"  # SEVERITY:
    r"-{20,}\s*\n"                          # closing dashes
    r".*?"                                  # skip WHAT IT CLAIMS TO DO label
    r"WHAT IT ACTUALLY DOES:\s*\n(.*?)\n"  # skip actual-does body
    r"THE BUG / RISK:\s*\n(.*?)\n"         # bug/risk — first line = summary
    r"EVIDENCE:",                           # stop before EVIDENCE
    re.DOTALL,
)

# Simpler fallback: just grab FILE/FUNCTION/CATEGORY/SEVERITY + first line of THE BUG / RISK
BLOCK_SIMPLE_RE = re.compile(
    r"-{20,}[^\n]*\n"
    r"FILE:\s*([^\n]+)\n"
    r"FUNCTION:\s*([^\n]+)\n"
    r"CATEGORY:\s*([^\n]+)\n"
    r"SEVERITY:\s*(CRITICAL|HIGH|MEDIUM|LOW)[^\n]*\n"
    r"-{20,}[^\n]*\n",
    re.MULTILINE,
)

# Section headers that terminate a content block
SECTION_STOP = re.compile(
    r"\n(?:THE BUG / RISK|EVIDENCE|REPRODUCTION SCENARIO|IMPACT|FIX DIRECTION):",
    re.IGNORECASE,
)

# Matches THE BUG / RISK section up to the next section header
BUG_RISK_RE = re.compile(
    r"THE BUG / RISK:\s*\n(.*?)(?=\nEVIDENCE:|\nREPRODUCTION SCENARIO:|\nIMPACT:|\nFIX DIRECTION:|\n-{20,})",
    re.DOTALL | re.IGNORECASE,
)

# Fallback: WHAT IT ACTUALLY DOES section (used when THE BUG / RISK is absent)
WHAT_ACTUALLY_RE = re.compile(
    r"WHAT IT ACTUALLY DOES:\s*\n(.*?)(?=\nTHE BUG / RISK:|\nEVIDENCE:|\nREPRODUCTION SCENARIO:|\nIMPACT:|\nFIX DIRECTION:|\n-{20,})",
    re.DOTALL | re.IGNORECASE,
)


def _first_sentence(text: str) -> str:
    """Extract a clean one-sentence summary from a multi-line block."""
    # Remove markdown code fences
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    # Collapse whitespace and newlines
    text = re.sub(r"\s+", " ", text).strip()
    # Take up to first sentence-ending punctuation (min 20 chars to avoid fragments)
    m = re.match(r"(.{20,}?[.!?])(?:\s|$)", text)
    if m:
        s = m.group(1).strip()
        return s[:220] + ("..." if len(s) > 220 else "")
    return text[:220] + ("..." if len(text) > 220 else "")


def extract_from_file(md_path: Path, group_num: int) -> list[dict]:
    text = md_path.read_text(encoding="utf-8", errors="replace")

    # Skip group index files and NOT_FOUND files
    name = md_path.name
    if name.startswith("GROUP_") or "NOT_FOUND" in name:
        return []

    findings = []

    for m in BLOCK_SIMPLE_RE.finditer(text):
        file_path = m.group(1).strip()
        function = m.group(2).strip()
        category = m.group(3).strip()
        severity = m.group(4).strip()

        # Search within the next 4000 chars (enough for any single finding block)
        after = text[m.end(): m.end() + 4000]

        # Strategy 1: explicit THE BUG / RISK section
        bug_match = BUG_RISK_RE.search(after)
        if bug_match:
            summary = _first_sentence(bug_match.group(1))
        else:
            # Strategy 2: fall back to WHAT IT ACTUALLY DOES
            act_match = WHAT_ACTUALLY_RE.search(after)
            if act_match:
                summary = _first_sentence(act_match.group(1))
            else:
                summary = "(see review file)"

        findings.append({
            "severity": severity,
            "group": group_num,
            "source_file": file_path,
            "function": function,
            "category": category,
            "summary": summary,
            "review_file": str(md_path.relative_to(BASE)),
        })

    return findings


def main():
    all_findings = []

    for group_dir in sorted(REVIEW_ROOT.iterdir()):
        if not group_dir.is_dir():
            continue
        group_name = group_dir.name
        group_num = GROUP_NUM.get(group_name)
        if group_num is None:
            continue

        for md_file in sorted(group_dir.glob("*.md")):
            findings = extract_from_file(md_file, group_num)
            all_findings.extend(findings)

    # Sort: severity order, then group, then source file
    all_findings.sort(key=lambda f: (
        SEVERITY_ORDER.get(f["severity"], 99),
        f["group"],
        f["source_file"],
        f["function"],
    ))

    # Assign sequential IDs
    for i, f in enumerate(all_findings, 1):
        f["id"] = f"FR-{i:03d}"

    # Count by severity
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in all_findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1

    # Count by group
    group_counts = {}
    for f in all_findings:
        g = f["group"]
        group_counts[g] = group_counts.get(g, 0) + 1

    total = len(all_findings)

    # ── Write Markdown ──────────────────────────────────────────────────────
    md_out = BASE / "FULL_ISSUE_REGISTRY.md"
    with md_out.open("w", encoding="utf-8") as fh:
        fh.write("# Full Issue Registry — All Severities\n\n")
        fh.write(f"**Generated:** 2026-05-26  \n")
        fh.write(f"**Total issues:** {total}  \n")
        fh.write(
            f"**CRITICAL:** {counts['CRITICAL']} | "
            f"**HIGH:** {counts['HIGH']} | "
            f"**MEDIUM:** {counts['MEDIUM']} | "
            f"**LOW:** {counts['LOW']}  \n\n"
        )
        fh.write("> All issues start as **OPEN**. Change Status to IN_PROGRESS → FIXED → VERIFIED as you work.\n\n")
        fh.write("---\n\n")

        # Per-group breakdown
        fh.write("## Findings by Group\n\n")
        fh.write("| Group | Name | Total |\n|---|---|---|\n")
        group_names = {v: k.split("_", 2)[2].replace("_", " ") for k, v in GROUP_NUM.items()}
        for g in range(1, 17):
            fh.write(f"| {g} | {group_names.get(g, '')} | {group_counts.get(g, 0)} |\n")
        fh.write("\n---\n\n")

        # Main table
        fh.write("## Issue Table\n\n")
        fh.write("| ID | Severity | Group | Source File | Function | Category | Summary | Status |\n")
        fh.write("|---|---|---|---|---|---|---|---|\n")
        for f in all_findings:
            # Escape pipes in summary
            summary = f["summary"].replace("|", "\\|")
            function = f["function"].replace("|", "\\|")
            fh.write(
                f"| {f['id']} | {f['severity']} | {f['group']} "
                f"| `{f['source_file']}` | `{function}` "
                f"| {f['category']} | {summary} | OPEN |\n"
            )

        fh.write("\n---\n\n")
        fh.write("## Review File Index\n\n")
        fh.write("Each ID links back to its source review file for full details (line numbers, fix direction).\n\n")
        fh.write("| ID | Review File |\n|---|---|\n")
        for f in all_findings:
            fh.write(f"| {f['id']} | `{f['review_file']}` |\n")

    # ── Write CSV ────────────────────────────────────────────────────────────
    csv_out = BASE / "FULL_ISSUE_REGISTRY.csv"
    with csv_out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["ID", "Severity", "Group", "SourceFile", "Function",
                        "Category", "Summary", "Status", "ReviewFile"],
            extrasaction="ignore",
        )
        writer.writeheader()
        for f in all_findings:
            writer.writerow({
                "ID": f["id"],
                "Severity": f["severity"],
                "Group": f["group"],
                "SourceFile": f["source_file"],
                "Function": f["function"],
                "Category": f["category"],
                "Summary": f["summary"],
                "Status": "OPEN",
                "ReviewFile": f["review_file"],
            })

    # ── Print summary ────────────────────────────────────────────────────────
    print(f"\n✓ Extracted {total} findings")
    print(f"  CRITICAL: {counts['CRITICAL']}")
    print(f"  HIGH:     {counts['HIGH']}")
    print(f"  MEDIUM:   {counts['MEDIUM']}")
    print(f"  LOW:      {counts['LOW']}")
    print(f"\nPer-group breakdown:")
    for g in range(1, 17):
        print(f"  Group {g:2d} ({group_names.get(g, ''):30s}): {group_counts.get(g, 0)}")
    print(f"\nOutput written to:")
    print(f"  {md_out}")
    print(f"  {csv_out}")


if __name__ == "__main__":
    main()
