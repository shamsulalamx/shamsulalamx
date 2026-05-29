#!/usr/bin/env python3
"""Transform NBME stems with run-on lab clusters into the renderer's
expected per-line format so they render as 2-column HTML tables.

The Electron app's `buildStemHTML` (index.html line 7346) has two
paths to produce lab tables:
  A. `_isLabPara` + `_extractLabRows` — fires when a paragraph has at
     least one Name+Value+Unit match (via `_LAB_SCAN_RE`) AND the para
     is < 400 chars AND contains no '?'.
  B. `_extractEmbeddedLabBlock` — fires when a paragraph has 3+
     contiguous `\\n`-separated lines matching `_EMBED_LAB_LINE_RE`.

For NBME stems with embedded labs, path B is more reliable because
`_LAB_SCAN_RE` greedily merges adjacent labs across newlines and
breaks on common OCR errors. Path B is line-by-line and uses a
broader unit list + qualifier words.

This transformer:
  1. Detects 'Laboratory studies show:', 'Serum studies show:', etc.
     markers in each stem paragraph.
  2. Identifies the lab block boundary (between marker and the next
     prose sentence — usually 'Which of the following…?' or
     'A CT scan…' / 'Ultrasonography…' etc.).
  3. Splits the lab block into per-lab lines, propagating section
     prefixes (Serum, Urine, Pleural fluid, etc.).
  4. Fixes common OCR errors in units and chemical symbols.
  5. Reassembles the stem so the lab paragraph contains the marker on
     line 0 and each lab on its own line, then '\\n\\n' before the
     question prompt. This forces path B (because the merged
     paragraph length is > 400 chars when the prose is included).

If the lab block has < 3 lab triplets, the transformer leaves the
paragraph alone (no value).
"""
from __future__ import annotations
import re
from typing import Optional

# OCR fixes for chemical symbols and merged subscripts
OCR_FIXES = [
    # cI / Cl / c 1 variations → Cl-
    (re.compile(r"\bc\s*[I1l]\s*[-—–]\s*(?=\d)", re.I), "Cl- "),
    (re.compile(r"\bc[I1l]\s+(?=\d)", re.I), "Cl- "),
    (re.compile(r"\bc1\b(?=\s*[\-]?\s+\d)"), "Cl-"),
    # Hco3NN → HCO3- NN (e.g., "Hco325" → "HCO3- 25")
    (re.compile(r"\b(?:Hco|HCO|HC0)\s*[-—–]\s*(\d+)\s*mEq/L\s*[-—–]?\s*3\b", re.I), r"HCO3- \1 mEq/L"),
    (re.compile(r"\b(?:Hco|HCO|HC0)\s*3?[-—–]?\s*(\d+)\b"), r"HCO3- \1"),
    (re.compile(r"\bHC0\s+(\d+)\s+mEq/L\s*[-—–]+\s*3\b"), r"HCO3- \1 mEq/L"),
    (re.compile(r"\bHCO3\s*[-—–]\s*(\d+)\s+mEq/L"), r"HCO3- \1 mEq/L"),
    (re.compile(r"\bHCO3-\s+3-\s+\|"), r"HCO3- |"),
    # PCO , → PCO2; PO , → PO2 (paren'd dropped subscripts)
    (re.compile(r"\bPCO\s*[,\.]?\s+(\d)"), r"PCO2 \1"),
    (re.compile(r"\bPO\s*[,\.]?\s+(\d)"), r"PO2 \1"),
    # ums / ums → /µm³
    (re.compile(r"\b(\d+)\s+ums?\b"), r"\1 /µm³"),
    (re.compile(r"\b(\d+)\s+µm\s*3\b"), r"\1 /µm³"),
    (re.compile(r"\b(\d+)\s+um\s*3\b"), r"\1 /µm³"),
    # /mm 3 / /mm? → /mm³
    (re.compile(r"\/mm\s*\?"), r"/mm³"),
    (re.compile(r"\/mm\s*3\b"), r"/mm³"),
    (re.compile(r"\/mm\b(?!\s*[3²³])"), r"/mm³"),  # bare /mm at end of token
    # Na *, Na+, Na^+, Nat (OCR'd) → Na+
    (re.compile(r"\bNa\s*[\*\^t]"), r"Na+"),
    (re.compile(r"\bK\s*[\*\^]"), r"K+"),
    (re.compile(r"\bNa\s*\+"), r"Na+"),
    (re.compile(r"\bK\s*\+"), r"K+"),
    # ECG OCR'd as EGG
    (re.compile(r"\bAn?\s+EGG\b"), r"An ECG"),
    # Cl · / Cl · OCR variations
    (re.compile(r"\bCl\s*[·\-—–]"), r"Cl-"),
    # Pipe separators → space (for pipe-table format)
    (re.compile(r"\s*\|\s*"), r" "),
]

# Lab block markers (allow OCR variants like "stud ies", "study" without 's')
LAB_MARKER_RE = re.compile(
    r"(?:Laboratory\s+(?:stud\s?(?:y|ies)?|findings)|"
    r"(?:Serum|Urine|Pleural\s+fluid|Cerebrospinal\s+fluid|"
    r"Arterial\s+blood\s+gas|Plasma|Blood)\s+(?:stud\s?(?:y|ies)?|analysis)"
    r"(?:\s+on\s+(?:room\s+air|\d+%\s+oxygen|[^,.]{0,30}?))?|"
    r"Hemoglobin\s+electrophoresis|Urinalysis|"
    r"Laboratory|Initial\s+laboratory|"
    r"Pleural\s+fluid\s+analysis)"
    r"\s+(?:shows?|results|reveal|indicates?|are|include|reveals?)\s*:?\s*",
    re.IGNORECASE,
)

# Section headers within a lab block (propagated as prefix into lab names)
SECTION_HEADER_WORDS = {
    "serum", "urine", "plasma", "blood smear", "pleural fluid",
    "cerebrospinal fluid", "arterial blood gas", "hemoglobin electrophoresis",
}

# Pattern for a single lab triplet: Name + Value + Unit
# Used to detect boundaries within a run-on lab block
LAB_UNITS = r"mEq\/L|mg\/dL|mg\/dl|mmol\/L|µg\/dL|µg\/dl|ng\/dL|ng\/dl|%|U\/L|IU\/L|mm\s?Hg|g\/dL|g\/dl|\/mm[²³3]|\/µm[²³3]|\/hpf|\/lpf|sec|ng\/mL|ng\/ml|mL\/min|mg\/24\s?h"
LAB_TRIPLET_RE = re.compile(
    rf"((?:[A-Z]|pH|pCO2?|pO2?)[A-Za-z0-9\s\+\-²³⁻\.,]{{0,40}}?)\s+"
    rf"([<>]?\d[\d.,]*(?:\-[\d.,]+)?\+?|trace|negative|positive|normal|abnormal|elevated|absent|present|reactive|nonreactive|increased|decreased|unchanged|none|occasional|frequent|few|many|moderate|severe|mild)\s*"
    rf"(?:({LAB_UNITS})|\b)"
    rf"(?:\s+\([^)]+\))?"
)


def fix_ocr(text: str) -> str:
    """Apply common OCR error fixes."""
    for pattern, repl in OCR_FIXES:
        text = pattern.sub(repl, text)
    return text


def normalize_qualifier(val: str) -> str:
    """Map non-standard qualifier words to renderer-compatible ones."""
    mapping = {
        "occasional": "present",
        "frequent": "present",
        "moderate": "elevated",
        "severe": "elevated",
        "few": "present",
        "many": "present",
        "mild": "trace",
    }
    return mapping.get(val.lower(), val)


def split_lab_block(stem: str) -> tuple[str, bool]:
    """Detect and reformat embedded lab clusters in a stem. Returns
    (new_stem, modified)."""
    # First apply OCR fixes everywhere
    fixed = fix_ocr(stem)

    # Find the marker
    marker_match = LAB_MARKER_RE.search(fixed)
    if not marker_match:
        return fixed, fixed != stem

    marker_start = marker_match.start()
    marker_end = marker_match.end()

    # The lab block starts right after the marker. Find its end.
    # Heuristics: the lab block ends when we hit:
    #   - a sentence with 'Which of the following', 'In addition to', etc.
    #   - an imaging follow-up like 'A CT scan…', 'Ultrasonography…'
    #   - a 24-hour follow-up like 'A 24-hour urine collection shows'
    after = fixed[marker_end:]
    END_PATTERN = re.compile(
        r"\s+(?:Which\s+of\s+the\s+following|"
        r"The\s+(?:most\s+likely|patient|next)|"
        r"A\s+24-hour|A\s+CT\s+scan|An?\s+x-ray|An?\s+ECG|An?\s+EGG|"
        r"An?\s+EKG|An?\s+MRI|Ultrasonography|Echocardiography|"
        r"Imaging|Endoscopy|Colonoscopy|Bronchoscopy|Angiography|"
        r"Treatment\s+with|In\s+addition|This\s+patient|"
        r"What\s+is\s+the|\[FIGURE:)",
        re.IGNORECASE,
    )
    end_match = END_PATTERN.search(after)
    block_end_offset = end_match.start() if end_match else len(after)
    block = after[:block_end_offset]
    post = after[block_end_offset:]

    # Now parse the block into lab tokens
    block_clean = re.sub(r"\s+", " ", block).strip()
    if not block_clean:
        return fixed, fixed != stem

    # Find all lab triplets
    matches = list(LAB_TRIPLET_RE.finditer(block_clean))
    if len(matches) < 3:
        return fixed, fixed != stem

    # Walk through the block, identifying section prefixes (Serum, Urine, etc.)
    # and accumulating labs with the current section prefix.
    section_prefix = ""
    lab_lines = []

    # Tokenize by detecting section words at the start of segments
    # (before a lab triplet's name).
    pos = 0
    for m in matches:
        # Look at text between pos and m.start() — could contain a section header
        gap = block_clean[pos:m.start()].strip()
        if gap:
            for sect in SECTION_HEADER_WORDS:
                # Match section as a whole word at end of gap
                if re.search(rf"\b{re.escape(sect)}\b\s*$", gap, re.I):
                    section_prefix = " ".join(w.capitalize() for w in sect.split())
                    break
            else:
                # Gap doesn't end in a section header — check if it contains one
                for sect in SECTION_HEADER_WORDS:
                    pat = re.search(rf"\b{re.escape(sect)}\b", gap, re.I)
                    if pat:
                        section_prefix = " ".join(w.capitalize() for w in sect.split())
                        break

        name = m.group(1).strip()
        val = m.group(2).strip()
        unit = m.group(3) if m.group(3) else ""

        # Apply qualifier normalization for non-numeric vals
        if not re.match(r"^[\d.,+\-<>]", val):
            val = normalize_qualifier(val)

        # Skip section header words that LAB_TRIPLET_RE accidentally captured as name
        name_lc = name.lower()
        if name_lc in SECTION_HEADER_WORDS or any(
            name_lc.endswith(sect) for sect in SECTION_HEADER_WORDS
        ):
            pos = m.end()
            continue

        # Build the line
        if section_prefix and not name.lower().startswith(section_prefix.lower()):
            full_name = f"{section_prefix} {name}"
        else:
            full_name = name
        if unit:
            line = f"{full_name} {val} {unit}"
        else:
            line = f"{full_name} {val}"
        lab_lines.append(line)
        pos = m.end()

    if len(lab_lines) < 3:
        return fixed, fixed != stem

    # Reassemble: pre + (marker without trailing colon) + ":\n" + lab lines joined by \n + remaining
    pre = fixed[:marker_start].rstrip()
    marker = marker_match.group(0).rstrip().rstrip(":")
    new_lab_section = marker + ":\n" + "\n".join(lab_lines)
    post = post.lstrip()

    if pre and post:
        new_stem = pre + " " + new_lab_section + "\n\n" + post
    elif pre:
        new_stem = pre + " " + new_lab_section
    elif post:
        new_stem = new_lab_section + "\n\n" + post
    else:
        new_stem = new_lab_section

    return new_stem, True


def transform_stem(stem: str) -> str:
    """Public API: transform an NBME stem with OCR fixes + lab-block split."""
    new_stem, _ = split_lab_block(stem)
    return new_stem
