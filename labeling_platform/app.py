from __future__ import annotations

import csv
import hashlib
import hmac
import html as html_module
import json
import re
import secrets
import threading
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

import bcrypt
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from extra_streamlit_components import CookieManager

from manual_pdf import build_manual_pdf_bytes


BASE_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = BASE_DIR / "labeling_assets"
GLUCOSE_DIR = BASE_DIR / "glucose_data"
USER_MANUAL_PATH = Path(__file__).resolve().parent / "USER_MANUAL.md"
MANUAL_IMAGES_DIR = Path(__file__).resolve().parent / "docs" / "manual_images"
G2_STUDY_TIMELINE_SVG = "g2-study-timeline.svg"
G2_STUDY_TIMELINE_CAPTION = (
    "Each participant wore a CGM for 20 study days (Phase 1: no alerts; Phase 2: alerts on). "
    "The interview happened afterward — you score their spoken Answers, not the glucose numbers."
)
CONTINGENCY_CHAIN_MINI_SVG = "contingency-chain-mini.svg"
PRELIMINARY_EXAMPLES_SVG = "preliminary-examples-scores.svg"
SCORING_WORKFLOW_SVG = "scoring-workflow-simple.svg"
SESSION_COOKIE_NAME = "g2_labeling_auth"
SESSION_MAX_AGE_DAYS = 30
SESSION_SECRET_PATH = ASSETS_DIR / ".session_secret"
SIMPLE_LABELING_MODE = True
SIMPLE_TRAINING_VERSION = "answer_labeling_training_v1"
# User-facing name aligned with CGM_Goal_v3: contingency-sensitive verbal behavior under CGM feedback
PLATFORM_DISPLAY_NAME = "CGM Contingency Speech Scoring Platform"
PLATFORM_PAGE_TITLE = "CGM Contingency Speech Scoring"
PLATFORM_LOGIN_CAPTION = (
    "G2 Study · Score how participants describe learning from continuous glucose monitoring"
)

USER_FILE_LOCK = threading.RLock()
ANNOTATION_FILE_LOCK = threading.RLock()

MANUAL_VISUAL_GUIDE: List[dict] = [
    {
        "file": "annotate-workflow-steps.svg",
        "title": "Recommended annotation order (Steps 1-8)",
        "caption": "Follow this order for every Q/A item. Language coding first; CGM is supporting evidence.",
    },
    {
        "file": "annotate-layout-guide.svg",
        "title": "Annotate page layout (regions 1-10, dual CGM)",
        "caption": "Scroll top to bottom: navigation, Q/A, CGM summary, coding form, save, then Participant Context.",
    },
    {
        "file": "01-annotate-full-page.png",
        "title": "Figure 0 - Full Annotate page (overview)",
        "caption": "Tall viewport showing sidebar, Q/A, CGM summary, coding form, and start of Participant Context.",
    },
    {
        "file": "02-annotate-top-qa.png",
        "title": "Figure A - Navigation and Q/A cards",
        "caption": "Header stats, Previous/Next, keyword legend, and bilingual Question/Answer cards. "
        "On CGM-relevant items, the early CGM Summary block may appear just below this view.",
    },
    {
        "file": "03-cgm-summary-table.png",
        "title": "Figure B - CGM Summary for Coding table",
        "caption": "Phase 1 baseline vs Phase 2 (all days and last 3d) with color-coded verdicts and metric picker.",
    },
    {
        "file": "04-code-selection.png",
        "title": "Figure C - Code selection (Group -> Subgroup -> Code)",
        "caption": "Up to 3 code slots with Group / Subgroup / Code dropdowns, Other checkbox, and codebook placeholders. "
        "On CGM-relevant items, the summary table may still appear above this block.",
    },
    {
        "file": "05-primary-confidence.png",
        "title": "Figure D - Primary Hierarchy, Components, and Rule Taxonomy",
        "caption": "Primary 0-4 radio, secondary component checkboxes, and rule taxonomy fields "
        "(shown when Rule is checked or Primary >= 3).",
    },
    {
        "file": "06-save-buttons.png",
        "title": "Figure E - Confidence, Notes, and Save",
        "caption": "Coding Confidence 1-5, optional coder note, late CGM coding notes when triggered, "
        "and Save / Save and Next. Participant Context may appear at the bottom of this view.",
    },
    {
        "file": "07-participant-context.png",
        "title": "Figure F - Participant Context and Demographics",
        "caption": "Demographics card (A1C, BMI, CDC Risk, etc.) and CGM tab bar "
        "(Computed Metrics / Alert Phase Comparison / Raw Trace) for the current subject.",
    },
    {
        "file": "08-alert-phase-comparison.png",
        "title": "Figure G - Alert Phase Comparison daily chart",
        "caption": "Phase 2 daily values vs Phase 1 baseline with daily delta bars.",
    },
]
CODES_PATH = ASSETS_DIR / "codebook_codes_flat_oneline.csv"
TREE_PATH = ASSETS_DIR / "codebook_tree.json"
LINE_ITEMS_PATH = ASSETS_DIR / "bilingual_line_items.jsonl"
ANNOTATIONS_PATH = ASSETS_DIR / "annotations_qa.csv"
CHECK_SAMPLES_PATH = ASSETS_DIR / "simple_check_samples.csv"
USERS_PATH = ASSETS_DIR / "users.json"
GLUCOSE_RAW_PATH = GLUCOSE_DIR / "G2_Raw_cgm.csv"
GLUCOSE_COMPUTED_PATH = GLUCOSE_DIR / "G2_computed_cgm.csv"
GLUCOSE_DEMOGRAPHICS_PATH = GLUCOSE_DIR / "G2_demographics.csv"
GLUCOSE_VALUE_COL = "Glucose.Value..mg.dL."

DEMOGRAPHICS_FIELDS: List[tuple] = [
    ("sex_atbirth", "Sex at Birth"),
    ("race", "Race"),
    ("ethnicity_screen", "Ethnicity"),
    ("education", "Education"),
    ("current_employment", "Employment"),
    ("bmi", "BMI"),
    ("bmi_cat", "BMI Category"),
    ("a1c", "A1C (%)"),
    ("a1c_cat", "A1C Category"),
    ("fasting_glucose", "Fasting Glucose (mg/dL)"),
    ("cdc_risk_score", "CDC Risk Score"),
    ("cdc_risk_score_cat", "CDC Risk Category"),
    ("cgm_date", "CGM Start Date"),
]

# Default card: fields most relevant to pre-diabetes status and CGM alert coding.
DEMOGRAPHICS_PRIMARY_FIELDS: List[tuple] = [
    ("a1c", "A1C"),
    ("bmi", "BMI"),
    ("cdc_risk_score", "CDC Risk Score"),
    ("sex_atbirth", "Sex at Birth"),
    ("race", "Race"),
]

# Shown only in the expanded record (low variance, redundant, sparse, or operational).
DEMOGRAPHICS_EXPANDED_ONLY_FIELDS: List[tuple] = [
    ("ethnicity_screen", "Ethnicity"),
    ("education", "Education"),
    ("current_employment", "Employment"),
    ("bmi_cat", "BMI Category"),
    ("a1c_cat", "A1C Category"),
    ("fasting_glucose", "Fasting Glucose (mg/dL)"),
    ("cdc_risk_score_cat", "CDC Risk Category"),
    ("cgm_date", "CGM Start Date"),
]

CGM_COMPUTED_METRICS: Dict[str, dict] = {
    "above_140": {
        "label": ">140 mg/dL",
        "unit": "%",
        "fmt": ".1f",
        "group": "Alert & time in range",
        "lower_is_better": True,
        "help": "Percent of time glucose was above 140 mg/dL (Dexcom alert threshold).",
    },
    "above_180": {
        "label": ">180 mg/dL",
        "unit": "%",
        "fmt": ".1f",
        "group": "Alert & time in range",
        "lower_is_better": True,
        "help": "Percent of time glucose was above 180 mg/dL.",
    },
    "in_range_63_140": {
        "label": "Time in Range (63–140)",
        "unit": "%",
        "fmt": ".1f",
        "group": "Alert & time in range",
        "lower_is_better": False,
        "help": "Percent of time glucose was between 63 and 140 mg/dL.",
    },
    "AUC": {
        "label": "Mean Glucose (AUC)",
        "unit": "mg/dL",
        "fmt": ".0f",
        "group": "Glycemic control",
        "lower_is_better": True,
        "help": "Average glucose value for the day (area under the curve).",
    },
    "eA1C": {
        "label": "eA1C",
        "unit": "%",
        "fmt": ".1f",
        "group": "Glycemic control",
        "lower_is_better": True,
        "help": "Estimated A1C.",
    },
    "GMI": {
        "label": "GMI",
        "unit": "%",
        "fmt": ".1f",
        "group": "Glycemic control",
        "lower_is_better": True,
        "help": "Glucose Management Indicator.",
    },
    "CV": {
        "label": "CV (Coefficient of Variation)",
        "unit": "%",
        "fmt": ".1f",
        "group": "Variability",
        "lower_is_better": True,
        "help": "Glucose variability; higher values indicate less stability.",
    },
    "MAGE": {
        "label": "MAGE",
        "unit": "mg/dL",
        "fmt": ".1f",
        "group": "Variability",
        "lower_is_better": True,
        "help": "Mean Amplitude of Glycemic Excursions.",
    },
    "J_index": {
        "label": "J-index",
        "unit": "",
        "fmt": ".1f",
        "group": "Variability",
        "lower_is_better": True,
        "help": "Combined index of mean glucose and variability.",
    },
    "GRI": {
        "label": "GRI",
        "unit": "",
        "fmt": ".1f",
        "group": "Risk indices",
        "lower_is_better": True,
        "help": "Glycemic Risk Index; combines high and low glucose risk.",
    },
    "HBGI": {
        "label": "HBGI",
        "unit": "",
        "fmt": ".2f",
        "group": "Risk indices",
        "lower_is_better": True,
        "help": "High Blood Glucose Index.",
    },
    "LBGI": {
        "label": "LBGI",
        "unit": "",
        "fmt": ".2f",
        "group": "Risk indices",
        "lower_is_better": True,
        "help": "Low Blood Glucose Index.",
    },
}

CGM_METRIC_GROUPS: Dict[str, List[str]] = {
    "Alert & time in range": ["above_140", "above_180", "in_range_63_140"],
    "Glycemic control": ["AUC", "eA1C", "GMI"],
    "Variability": ["CV", "MAGE", "J_index"],
    "Risk indices": ["GRI", "HBGI", "LBGI"],
}

# Display thresholds for phase comparisons. Smaller deltas are shown as
# "Similar" so coders do not over-interpret measurement noise or tiny shifts.
CGM_MEANINGFUL_DELTA: Dict[str, float] = {
    "above_140": 2.0,
    "above_180": 2.0,
    "in_range_63_140": 2.0,
    "AUC": 5.0,
    "eA1C": 0.2,
    "GMI": 0.2,
    "CV": 2.0,
    "MAGE": 5.0,
    "J_index": 2.0,
    "GRI": 2.0,
    "HBGI": 0.2,
    "LBGI": 0.2,
}

CGM_DEFAULT_METRICS = ["AUC", "in_range_63_140", "above_140", "eA1C"]

CGM_CODING_SUMMARY_DEFAULT_METRICS = CGM_DEFAULT_METRICS

CGM_CODING_STRONG_CODE_GROUPS = {
    "Learning Outcome",
    "Device Understanding & Usage",
    "App Interpretation & Preference",
}

CGM_CODING_KEYWORD_ONLY_CODE_GROUPS = {
    "Experience Valence",
    "Continuation Intent",
}

CGM_CODING_RELEVANT_CODE_GROUPS = CGM_CODING_STRONG_CODE_GROUPS | CGM_CODING_KEYWORD_ONLY_CODE_GROUPS

CGM_CODE_HINTS: Dict[str, str] = {
    "Dietary": ">140 mg/dL, Time in Range, and mean glucose (Phase 1→2) are most relevant for diet-related codes.",
    "Exercise": "Check Time in Range and mean glucose; also consider CV/MAGE in full CGM charts for variability.",
    "Alert-Based Reflection": "Focus on >140 mg/dL change after alerts turned on (Phase 2 vs Phase 1).",
    "Graph Leading to Behavior Action": "Compare whether stated behavior change aligns with Phase 2 glucose pattern.",
    "Graph Interpretation Language": "Interpretation accuracy is linguistic; use CGM only to check plausibility, not to auto-code.",
    "Check-ins After Meals": "Meal-timing behavior may relate to post-meal >140 mg/dL and mean glucose.",
    "Check-ins Before Meals": "Pre-meal checking may relate to Time in Range and mean glucose stability.",
}

CGM_TIMELINE_REMINDER = (
    "The interview is retrospective and may not align day-by-day with the CGM wear period. "
    "Use CGM as supporting or conflicting evidence for the participant's language — not as the sole basis for Primary level."
)

NARRATIVE_IMPROVEMENT_PATTERNS: List[str] = [
    r"\bimprov(?:e|ed|ing|ement)\b",
    r"\bbetter\b",
    r"\bcut(?:ting)?\s+back\b",
    r"\bchang(?:e|ed|ing)\b",
    r"\bstart(?:ed|ing)\s+(?:to|eat|walk|cut|avoid)",
    r"\breduc(?:e|ed|ing|tion)\b",
    r"\bhealthier\b",
    r"\bmejor(?:e|é|ando|ar)\b",
    r"\bcambi(?:e|é|ando|ar)\b",
    r"\bempec(?:é|e|ar)\b",
    r"\bdej(?:é|e|ar)\s+de\b",
]

CGM_METRIC_PRESETS: Dict[str, List[str]] = {
    "Default (4 core metrics)": CGM_DEFAULT_METRICS,
    "Alert & time in range": CGM_METRIC_GROUPS["Alert & time in range"],
    "Glycemic control": CGM_METRIC_GROUPS["Glycemic control"],
    "Variability": CGM_METRIC_GROUPS["Variability"],
    "Risk indices": CGM_METRIC_GROUPS["Risk indices"],
    "All metrics": list(CGM_COMPUTED_METRICS.keys()),
}

CGM_PHASE_ALL = "All periods"
CGM_PHASE_1 = "Phase 1 (No alerts, Day 1–10)"
CGM_PHASE_2 = "Phase 2 (Alerts >140 mg/dL, Day 11–20)"
CGM_PHASE_OPTIONS = [CGM_PHASE_ALL, CGM_PHASE_1, CGM_PHASE_2]
CGM_RAW_RANGE_ALL = "Full wear period"
PHASE_COMPARISON_DEFAULT = "above_140"
PHASE_SUMMARY_DEFAULT_METRICS = CGM_METRIC_GROUPS["Alert & time in range"] + ["AUC"]
PHASE2_RECENT_DAYS = 3

BEHAVIOR_HIGHLIGHT_PATTERNS: Dict[str, List[str]] = {
    "hl-diet": [
        r"\bdiet(?:ary)?\b",
        r"\b(?:eat|eats|eating|eaten|ate)\b",
        r"\bfood[s]?\b",
        r"\bmeal[s]?\b",
        r"\bsnack[s]?\b",
        r"\brice\b",
        r"\bbread\b",
        r"\bcarb(?:ohydrate)?s?\b",
        r"\bportion[s]?\b",
        r"\btortilla[s]?\b",
        r"\bsugar\b",
        r"\bnutrition\b",
        r"\bhungry\b",
        r"\bwater\b",
        r"\bcom(?:er|í|ía|iendo|en|emos|ieron)\b",
        r"\bque\s+como\b",
        r"\bcomida[s]?\b",
        r"\balimento[s]?\b",
        r"\barroz\b",
        r"\bpan\b",
        r"\bcarbohidrato[s]?\b",
        r"\bdieta\b",
        r"\bporci(?:ón|ones)\b",
        r"\btortilla[s]?\b",
        r"\baz[uú]car\b",
        r"\bnutrici(?:ón|on)\b",
        r"\bhambre\b",
        r"\bhabitos?\s+alimentari(?:o|os)\b",
        r"\beat(?:ing)?\s+habits?\b",
        r"\bfeed(?:ing|s)?\b",
        r"\bdrink(?:ing|s)?\b",
        r"\bdrank\b",
        r"\bflour\b",
        r"\bharina\b",
        r"\bdrink(?:ing|s)?\s+water\b",
        r"\b(?:alimentaci(?:ón|on)|alimentarme|alimentarse)\b",
        r"\b(?:desayuno|almuerzo|cena|breakfast|lunch|dinner)\b",
    ],
    "hl-exercise": [
        r"\bexercis(?:e|es|ing|ed)\b",
        r"\bworkout[s]?\b",
        r"\b(?:walk|walks|walking|walked)\b",
        r"\b(?:run|runs|running|ran)\b",
        r"\bphysical(?:ly)?\b",
        r"\byoga\b",
        r"\bgym\b",
        r"\bsedentary\b",
        r"\b(?:sit|sits|sitting|sat)\b",
        r"\bactiv(?:e|ity|ities)\b",
        r"\bmov(?:e|es|ing|ement|er|ed)\b",
        r"\bejercici(?:o|os|tar)\b",
        r"\bcamin(?:ar|ando|é|o|aba)\b",
        r"\bentren(?:ar|amiento|ando|é|o)\b",
        r"\bgimnasio\b",
        r"\bsedentari(?:o|a)\b",
        r"\bsentad[oa]\b",
        r"\bactiv(?:o|a|idad|idades)\b",
        r"\bmov(?:er|imiento|iendo|í|ió)\b",
        r"\bexercise\s+habits?\b",
        r"\bhabitos?\s+de\s+ejercici(?:o|os)\b",
        r"\bquehaceres\b",
        r"\b(?:jog|jogging|jogged)\b",
        r"\b(?:bike|biking|biked)\b",
        r"\b(?:dance|dancing|danced)\b",
        r"\b(?:swim|swimming|swam)\b",
        r"\b(?:correr|corr(?:í|ió|iendo|o|e))\b",
        r"\b(?:bailar|bail(?:ando|é|o|aba))\b",
        r"\b(?:nadar|nad(?:ando|é|o|aba))\b",
    ],
    "hl-change": [
        r"\bchang(?:e|ed|es|ing)\b",
        r"\badjust(?:ed|ing|ment|ments)?\b",
        r"\bmindful(?:ness)?\b",
        r"\b(?:conscious|conscience|conscientious)\b",
        r"\b(?:aware|awareness)\b",
        r"\bconscien(?:t|te|cia)\b",
        r"\batent[oa]\b",
        r"\bstart(?:ed|ing|s)?\b",
        r"\bstop(?:ped|ping|s)?\b",
        r"\bavoid(?:ed|ing|s)?\b",
        r"\bcut(?:ting)?\s+back\b",
        r"\btry(?:ing|ied|ies)?\b",
        r"\breduc(?:e|ed|ing|tion)\b",
        r"\bimprov(?:e|ed|ing|ement)\b",
        r"\bhabit[s]?\b",
        r"\brule[s]?\b",
        r"\bcut\s+back\b",
        r"\bsmaller\s+amount[s]?\b",
        r"\bportion\s+control\b",
        r"\b(?:less|fewer)\s+(?:food|carb|sugar|snack|meal|rice|bread|portion)\b",
        r"\bcambi(?:o|[óo])\b",
        r"\bcambi[eé]\b",
        r"\bajust(?:e|ar|ando|[óo])\b",
        r"\bempec(?:e|[éé])\b",
        r"\bevitar\b",
        r"\bintent(?:ar|ando|[óo])\b",
        r"\bmejor(?:ar|[óo])\b",
        r"\bregla[s]?\b",
        r"\bcom(?:er|o|í|ía)\s+menos\b",
        r"\b(?:improve|improving|improved|improvement)\b",
        r"\b(?:change|changing)\b",
        r"\b(?:begin|began|begun|beginning)\b",
        r"\b(?:continue|continued|continuing)\b",
        r"\b(?:learn|learned|learning)\b",
        r"\b(?:notice|noticed|noticing)\b",
        r"\b(?:realiz(?:e|ed|ing)|figur(?:e|ed|ing))\b",
        r"\b(?:comenz(?:ar|ó|aba|ando|ar)|empez(?:ar|ó|aba|ando)|empec(?:é|e))\b",
        r"\b(?:mejor(?:é|e|ando|ar|aba|ar(?:ía|ías|án|amos))|mejor(?:ar|[óo]))\b",
        r"\b(?:consciente|consciencia)\b",
        r"\b(?:aprend(?:í|ió|er|iendo|o))\b",
        r"\b(?:not(?:é|ar|ando|o|aba))\b",
    ],
    "hl-alert": [
        r"\balert[s]?\b",
        r"\balarm[s]?\b",
        r"\bnotification[s]?\b",
        r"\bbeep(?:ing|s)?\b",
        r"\bbuzz(?:ed|es|ing)?\b",
        r"\bpuff\b",
        r"\bpipi\b",
        r"\bp(?:ee)?pi\b",
        r"\bbip\b",
        r"\bpeep(?:s|ing)?\b",
        r"\bping(?:s|ing)?\b",
        r"\bding(?:s|ing)?\b",
        r"\bspik(?:e|ed|ing|es)\b",
        r"\bhigh\s+glucose\b",
        r"\bglucose\s+(?:alarm|alert|level|reading|readings)\b",
        r"\bwent\s+up\b",
        r"\bgo(?:es|ing)\s+up\b",
        r"\btrigger[s]?\b",
        r"\bwarning[s]?\b",
        r"\balerta[s]?\b",
        r"\balarmas?\b",
        r"\bnotificaci(?:ón|ones)\b",
        r"\bson(?:ar|aba|ó|ando)\b",
        r"\bpit(?:ada|aba|ar|ó|ando|a|an)\b",
        r"\bp\s*ipi\b",
        r"\bglucosa\s+alta\b",
        r"\bse\s+me\s+(?:subi[oó]|sube|subía)\b",
        r"\bsub(?:e|ió|ida|iendo)\b",
        r"\bdispar(?:a|an|ar|ó)\b",
        r"\blecturas?\s+de\s+glucosa\b",
        r"\blecturas?\s+actuales\s+de\s+glucosa\b",
        r"\bglucosa\s+(?:alta|elevada)\b",
        r"\b(?:blood\s+)?glucose\s+(?:readings?|levels?|values?)\b",
        r"\b(?:high|elevated|rising)\s+glucose\b",
        r"\bglucose\s+(?:went|goes|going)\s+up\b",
        r"\b(?:went|goes|going)\s+(?:up|high)\b",
        r"\b(?:rose|rising|risen)\b",
        r"\b(?:son(?:ó|aba|ando|ar)|sonaba|suena|sonar)\b",
        r"\b(?:pit(?:ó|aba|ando|ar|ada|a|an)|pitar|pitada)\b",
        r"\b(?:notific(?:ation|ations|ó|ando|ar))\b",
        r"\b(?:avis(?:o|os|ar|ó|aba|ando))\b",
        r"\b(?:record(?:ar|atorio|atorios|ó|aba))\b",
        r"\b(?:sub(?:ió|ía|e|iendo|en|o)|subi(?:ó|endo))\b",
        r"\bse\s+me\s+(?:subi[oó]|sube|subía|subieron)\b",
    ],
}

# Cross-language pairs: if either side matches, both patterns are applied to their language text.
BILINGUAL_KEYWORD_PAIRS: List[tuple] = [
    ("hl-alert", r"\bglucose\s+readings?\b", r"\blecturas?\s+de\s+glucosa\b"),
    ("hl-alert", r"\bglucose\s+readings?\b", r"\blecturas?\s+actuales\s+de\s+glucosa\b"),
    ("hl-alert", r"\bhigh\s+glucose\b", r"\bglucosa\s+alta\b"),
    ("hl-alert", r"\b(?:high|elevated)\s+glucose\b", r"\bglucosa\s+(?:alta|elevada)\b"),
    ("hl-alert", r"\balarm[s]?\b", r"\balarmas?\b"),
    ("hl-alert", r"\balert[s]?\b", r"\balerta[s]?\b"),
    ("hl-alert", r"\bbeep(?:ing|s)?\b", r"\b(?:son(?:ó|aba|ando|ar)|sonaba|pitar|pit(?:ó|aba|ando|ar))\b"),
    ("hl-alert", r"\b(?:puff|pipi|bip|buzz)\b", r"\b(?:pitada|p\s*ipi|pipi|bip)\b"),
    ("hl-alert", r"\b(?:went|goes|going)\s+up\b", r"\b(?:sub(?:e|ió|ía|iendo)|subiendo)\b"),
    ("hl-alert", r"\b(?:rose|rising)\b", r"\b(?:sub(?:e|ió|ía|iendo)|subiendo)\b"),
    ("hl-alert", r"\bnotification[s]?\b", r"\bnotificaci(?:ón|ones)\b"),
    ("hl-alert", r"\bwarning[s]?\b", r"\b(?:avis(?:o|os)|advertencia[s]?)\b"),
    ("hl-diet", r"\b(?:eat|eats|eating|eaten|ate)\b", r"\bcom(?:er|í|ía|iendo|en|emos|ieron)\b"),
    ("hl-diet", r"\bfood[s]?\b", r"\b(?:alimento[s]?|comida[s]?)\b"),
    ("hl-diet", r"\bsugar\b", r"\baz[uú]car\b"),
    ("hl-diet", r"\b(?:carb|carbohydrate[s]?)\b", r"\bcarbohidrato[s]?\b"),
    ("hl-diet", r"\brice\b", r"\barroz\b"),
    ("hl-diet", r"\bbread\b", r"\bpan\b"),
    ("hl-diet", r"\beating\s+habits?\b", r"\bhabitos?\s+alimentari(?:o|os)\b"),
    ("hl-diet", r"\bwhat\s+I\s+eat\b", r"\bque\s+como\b"),
    ("hl-exercise", r"\bexercise\b", r"\bejercici(?:o|os)\b"),
    ("hl-exercise", r"\b(?:walk|walking|walked)\b", r"\bcamin(?:ar|ando|é|o|aba)\b"),
    ("hl-exercise", r"\bactivit(?:y|ies)\b", r"\bactiv(?:idad|idades)\b"),
    ("hl-exercise", r"\bactivities\b", r"\b(?:actividades|quehaceres)\b"),
    ("hl-change", r"\b(?:improve|improved|improving)\b", r"\bmejor(?:ar|[óo]|é|e|ando|aba)\b"),
    ("hl-change", r"\b(?:change|changes|changed|changing)\b", r"\bcambi(?:o|[óo]|é|e|ar|ando)\b"),
    ("hl-change", r"\b(?:aware|awareness)\b", r"\b(?:consciente|consciencia|atent[oa])\b"),
    ("hl-change", r"\bmindful(?:ness)?\b", r"\b(?:atent[oa]|consciente)\b"),
    ("hl-change", r"\b(?:start(?:ed|ing|s)?|begin|began)\b", r"\b(?:empec(?:é|e|ar)|comenz(?:ó|ar|aba|ando))\b"),
    ("hl-change", r"\b(?:avoid|avoided|avoiding)\b", r"\bevitar\b"),
    ("hl-change", r"\b(?:learn|learned|learning)\b", r"\b(?:aprend(?:í|ió|er|iendo|o))\b"),
    ("hl-change", r"\b(?:improve|improved|improving)\b", r"\b(?:mejorar|mejor(?:é|e|ando|aba))\b"),
    ("hl-change", r"\bchanges\b", r"\bcambios\b"),
    ("hl-diet", r"\bdiet\b", r"\bdieta\b"),
    ("hl-alert", r"\bglucose levels?\b", r"\bniveles?\s+de\s+glucosa\b"),
    ("hl-exercise", r"\bexercise habits\b", r"\b(?:ejercicio|ejercicios)\b"),
    ("hl-change", r"\bhabit[s]?\b", r"\b(?:hábito[s]?|habito[s]?)\b"),
    ("hl-change", r"\brule[s]?\b", r"\bregla[s]?\b"),
]

# Extra patterns tried on the language with fewer category matches (best-effort count parity).
PARITY_BACKFILL_PATTERNS: Dict[str, Dict[str, List[str]]] = {
    "en": {
        "hl-diet": [
            r"\b(?:feed|fed|feeding)\b",
            r"\b(?:snack|snacking|snacked)\b",
            r"\b(?:fast(?:ing|ed)?)\b",
        ],
        "hl-alert": [
            r"\b(?:vibrat(?:e|ed|ing|es)|sound(?:ed|s|ing)?)\b",
            r"\b(?:nois(?:e|y|es))\b",
        ],
        "hl-change": [
            r"\b(?:cut(?:ting)?\s+down)\b",
            r"\b(?:pay(?:ing)?\s+attention)\b",
        ],
    },
    "es": {
        "hl-diet": [
            r"\b(?:tom(?:ar|é|aba|ando)|bebi(?:endo|ó|o))\b",
            r"\b(?:merienda|merendar)\b",
        ],
        "hl-alert": [
            r"\b(?:hizo\s+ruido|ruido|sonido)\b",
        ],
        "hl-change": [
            r"\b(?:dej(?:é|ar|aba|ando)|dejar)\b",
            r"\b(?:trat(?:é|ar|aba|ando))\b",
        ],
    },
}

OTHER_CODE = "__OTHER__"

ANNOTATION_COLUMNS = [
    "qa_id",
    "subject_id",
    "question_line_no",
    "answer_line_no",
    "selected_code_id",
    "selected_code_ids",
    "code_confidences",
    "code_comments",
    "is_other",
    "other_reason",
    "primary_hierarchy",
    "component_context",
    "component_behavior",
    "component_consequence",
    "component_rule",
    "secondary_component_score",
    "rule_source",
    "behavior_form",
    "confidence",
    "annotation_confidences",
    "annotation_comments",
    "evidence_span",
    "issue_flags",
    "meaning_unit_note",
    "coder",
    "coder_username",
    "updated_at_utc",
]

MAX_CODE_SELECTIONS = 3
CODE_DELIMITER = ";"
ISSUE_FLAG_DELIMITER = ";"

RULE_SOURCE_OPTIONS = [
    "N/A",
    "Self-generated",
    "Borrowed (doctor, family, generic advice)",
    "Mixed/Unclear",
]

GROUP_PLACEHOLDER = "— Select a Code Group —"
GROUP_NONE = "(None of these matches)"
SG_PLACEHOLDER = "— Select a Subgroup —"
SG_NONE = "(None of these matches in this group)"
CODE_PLACEHOLDER = "— Select a Code —"
CODE_NONE = "(None of these matches in this subgroup)"

BEHAVIOR_FORM_OPTIONS = [
    "N/A",
    "Enacted change (already doing it)",
    "Stated intention (planning to do it)",
]

ADMIN_USERNAMES = {"david"}
AGREEMENT_PRIMARY_LABELS = [0, 1, 2, 3, 4]
AGREEMENT_MIN_OVERLAP = 5

# Attention checks are the clear, unambiguous (Primary 0 / no-contingency) hidden
# check samples used to confirm an annotator is paying attention (Prolific-style).
# A coder is flagged for review when they have reached at least
# ATTENTION_CHECK_MIN_REACHED attention checks and their Primary accuracy on those
# items is below ATTENTION_CHECK_PASS_THRESHOLD.
ATTENTION_CHECK_MIN_REACHED = 3
ATTENTION_CHECK_PASS_THRESHOLD = 0.70
AGREEMENT_COMPONENT_FIELDS = [
    ("component_context", "Context"),
    ("component_behavior", "Behavior"),
    ("component_consequence", "Consequence"),
    ("component_rule", "Rule"),
]

RULE_SOURCE_DEFINITIONS = {
    "Self-generated": "the Answer presents the rule as coming from the participant's own experience",
    "Borrowed (doctor, family, generic advice)": "the Answer presents the rule as borrowed from outside advice or generic guidance",
    "Mixed/Unclear": "the Answer gives a mixed source or does not make the source clear",
}

BEHAVIOR_FORM_DEFINITIONS = {
    "Enacted change (already doing it)": "the Answer describes behavior already happening",
    "Stated intention (planning to do it)": "the Answer states a future plan or intention",
}

CODING_CONFIDENCE_LEVELS: List[dict] = [
    {
        "score": 1,
        "title": "Very uncertain",
        "description": "The marking may be wrong. The Answer has strong ambiguity, missing context, or several equally plausible levels.",
        "guidance": "Flag for adjudication.",
    },
    {
        "score": 2,
        "title": "Uncertain",
        "description": "Leaning toward one marking, but meaningful doubt remains after reading the Answer.",
        "guidance": "Flag for adjudication if still unsure after re-reading.",
    },
    {
        "score": 3,
        "title": "Moderate",
        "description": "Reasonably confident. The Answer has minor ambiguity, but one marking is clearly preferred.",
        "guidance": "Default when evidence is adequate but not perfect.",
    },
    {
        "score": 4,
        "title": "Confident",
        "description": "Clear Answer evidence supports the marking. Little meaningful ambiguity.",
        "guidance": "Use when the Answer maps cleanly to the selected marking.",
    },
    {
        "score": 5,
        "title": "Very confident",
        "description": "Strong, unambiguous evidence. Unlikely to change on review.",
        "guidance": "Use when the Answer support is straightforward and well-supported.",
    },
]

CONFIDENCE_HELP = (
    "How sure are you that this marking is correct for the Answer response? "
    "Scores 1–2 flag the item for adjudication; 3 = moderate; 4–5 = high confidence."
)

ISSUE_FLAG_OPTIONS = [
    "Answer segmentation ambiguity",
    "Bilingual drift",
    "Rule-vs-intent confusion",
    "Taxonomy fit ambiguity",
    "CGM timeline mismatch",
    "Narrative-CGM conflict",
    "Low transcript detail",
]
ISSUE_FLAG_ALIASES = {
    "Segmentation ambiguity": "Answer segmentation ambiguity",
    "Codebook fit ambiguity": "Taxonomy fit ambiguity",
}

PRIMARY_LEVELS = [
    {
        "level": 0,
        "title": "No contingency language",
        "definition": "No meaningful relation is expressed between CGM feedback and behavior, context, or future action.",
        "example": "I don't really remember anything specific.",
    },
    {
        "level": 1,
        "title": "Descriptive observation",
        "definition": "The participant reports a glucose value, trend, or reaction without clearly linking it to a behavior or context.",
        "example": "My glucose went up.",
    },
    {
        "level": 2,
        "title": "Contingency recognition",
        "definition": "The participant links a glucose outcome to a behavior, context, timing, or condition, but does not clearly state a future-oriented rule.",
        "example": "My glucose goes up when I eat tortillas late.",
    },
    {
        "level": 3,
        "title": "Emerging self-rule",
        "definition": "The participant indicates tentative, partial, or planned behavioral adjustment based on prior CGM-linked consequences.",
        "example": "I noticed tortillas at night make me spike, so I'm trying to cut back.",
    },
    {
        "level": 4,
        "title": "Explicit self-generated rule",
        "definition": "The participant states a clear, self-provided behavior-guiding rule derived from direct CGM-linked consequences.",
        "example": "If I eat tortillas at night, I spike, so now I only have one or I avoid them at dinner.",
    },
]

SIMPLE_PRIMARY_LEVELS = [
    {
        "level": 0,
        "title": "No contingency language",
        "definition": "No meaningful relation is expressed between feedback, behavior, context, or future action.",
        "example": "I don't really remember anything specific.",
    },
    {
        "level": 1,
        "title": "Descriptive observation",
        "definition": "The Answer reports a value, trend, event, or reaction without clearly linking it to a behavior or context.",
        "example": "My reading went up.",
    },
    {
        "level": 2,
        "title": "Contingency recognition",
        "definition": "The Answer links an outcome to a behavior, context, timing, or condition, but does not clearly state a future-oriented rule.",
        "example": "My reading changes when I eat tortillas late.",
    },
    {
        "level": 3,
        "title": "Emerging self-rule",
        "definition": "The Answer indicates tentative, partial, or planned behavioral adjustment based on prior observed consequences.",
        "example": "I noticed tortillas at night affect me, so I'm trying to cut back.",
    },
    {
        "level": 4,
        "title": "Explicit self-generated rule",
        "definition": "The Answer states a clear, self-provided behavior-guiding rule derived from direct observed consequences.",
        "example": "If I eat tortillas at night, my reading changes, so now I only have one or avoid them at dinner.",
    },
]

SECONDARY_COMPONENTS = [
    {
        "name": "Context",
        "definition": "A time, setting, meal, activity period, situation, or occasion under which the event occurred.",
        "example": "at dinner / when I'm at work / after a long walk",
    },
    {
        "name": "Behavior",
        "definition": "The participant action, such as eating, walking, delaying food, modifying portions, or changing routine.",
        "example": "I ate rice / I went for a walk / I cut my portion",
    },
    {
        "name": "Consequence",
        "definition": "A glucose related outcome, such as rising, remaining elevated, flattening, recovering quickly, or remaining stable.",
        "example": "my glucose went up / it stayed flat / it recovered quickly",
    },
    {
        "name": "Rule",
        "definition": "Future oriented self guidance derived from the relation among the other components.",
        "example": "so now I avoid tortillas at dinner / I'll walk after meals from now on",
    },
]

SIMPLE_SECONDARY_COMPONENTS = [
    {
        "name": "Context",
        "definition": "A time, setting, meal, activity period, situation, or occasion under which the event occurred.",
        "example": "at dinner / when I'm at work / after a long walk",
    },
    {
        "name": "Behavior",
        "definition": "An action described in the Answer, such as eating, walking, delaying food, modifying portions, or changing routine.",
        "example": "I ate rice / I went for a walk / I cut my portion",
    },
    {
        "name": "Consequence",
        "definition": "An observed outcome, such as rising, remaining elevated, flattening, recovering quickly, or remaining stable.",
        "example": "it went up / it stayed flat / it recovered quickly",
    },
    {
        "name": "Rule",
        "definition": "Future oriented self guidance derived from the relation among the other components.",
        "example": "so now I avoid tortillas at dinner / I'll walk after meals from now on",
    },
]


def primary_levels_for_display() -> List[dict]:
    return SIMPLE_PRIMARY_LEVELS if SIMPLE_LABELING_MODE else PRIMARY_LEVELS


def secondary_components_for_display() -> List[dict]:
    return SIMPLE_SECONDARY_COMPONENTS if SIMPLE_LABELING_MODE else SECONDARY_COMPONENTS


SIMPLE_TRAINING_QUIZ_ITEMS: List[dict] = [
    {
        "id": "no_contingency",
        "question": "Was there anything you did not like about the health educational videos?",
        "answer": "No. Everything was good.",
        "expected_primary": 0,
        "expected_components": {
            "Context": False,
            "Behavior": False,
            "Consequence": False,
            "Rule": False,
        },
        "expected_rule_source": "N/A",
        "expected_behavior_form": "N/A",
        "rationale": "The Answer gives a general evaluation and does not describe a contingency relation.",
        "explanation_steps": [
            "<strong>Context?</strong> No — nothing anchors a specific when/where glucose moment.",
            "<strong>Behavior?</strong> No — no action (eating, walking, etc.) is described.",
            "<strong>Outcome?</strong> No — no glucose change is mentioned.",
            "<strong>Rule?</strong> No — nothing about what they will do next time.",
            "<strong>Why Primary 0?</strong> This is a general comment about videos, not a "
            "context → behavior → outcome → rule story.",
        ],
    },
    {
        "id": "descriptive_observation",
        "question": "How would you interpret what you saw in the app?",
        "answer": "My glucose went up after lunch, but I do not know what caused it.",
        "expected_primary": 1,
        "expected_components": {
            "Context": True,
            "Behavior": False,
            "Consequence": True,
            "Rule": False,
        },
        "expected_rule_source": "N/A",
        "expected_behavior_form": "N/A",
        "rationale": "The Answer reports an outcome and timing, but it does not link the outcome to a behavior or state a rule.",
    },
    {
        "id": "contingency_recognition",
        "question": "What do you think caused the high glucose alert?",
        "answer": "When I ate rice at dinner, my glucose went up.",
        "expected_primary": 2,
        "expected_components": {
            "Context": True,
            "Behavior": True,
            "Consequence": True,
            "Rule": False,
        },
        "expected_rule_source": "N/A",
        "expected_behavior_form": "N/A",
        "rationale": "The Answer links a behavior and context to a glucose outcome, but it does not state future self-guidance.",
        "explanation_steps": [
            '<strong>Context?</strong> Yes — "at dinner" sets the situation.',
            '<strong>Behavior?</strong> Yes — "ate rice" is the action.',
            '<strong>Outcome?</strong> Yes — "my glucose went up" is the glucose feedback they noticed.',
            "<strong>Rule?</strong> No — there is no from-now-on plan (nothing like "
            '"so now I will…").',
            "<strong>Why Primary 2?</strong> Context, behavior, and outcome connect into cause-and-effect, "
            "but the person has not turned that into a rule yet.",
        ],
    },
    {
        "id": "emerging_self_rule",
        "question": "Were there any changes to your eating habits after wearing the glucose sensor?",
        "answer": "I noticed soda makes my glucose spike, so I am trying to drink water instead.",
        "expected_primary": 3,
        "expected_components": {
            "Context": False,
            "Behavior": True,
            "Consequence": True,
            "Rule": True,
        },
        "expected_rule_source": "Self-generated",
        "expected_behavior_form": "Stated intention (planning to do it)",
        "rationale": "The Answer shows a tentative behavior adjustment based on an observed consequence.",
        "explanation_steps": [
            '<strong>Context?</strong> Weak — no specific when/where, but the soda habit is clear enough to score.',
            '<strong>Behavior?</strong> Yes — drinking soda, and trying water instead.',
            '<strong>Outcome?</strong> Yes — "makes my glucose spike" is the pattern they noticed.',
            '<strong>Rule?</strong> Yes — trying water instead is future-oriented self-guidance, but tentative.',
            '<strong>Why Primary 3 (not 4)?</strong> "I am trying to…" shows a change starting or being tested — '
            'not yet a firm "from now on I always…" rule already in place.',
            "<strong>3 vs 4 tip:</strong> Primary 4 needs a clear, settled rule the person is already following "
            '(e.g. "now I avoid…"). "Trying to" or "planning to" usually fits Primary 3.',
        ],
    },
    {
        "id": "explicit_self_generated_rule",
        "question": "Could you create a general rule about how diet relates to glucose levels?",
        "answer": "After watching the sensor, I figured out tortillas at night spike me, so now I avoid tortillas at dinner.",
        "expected_primary": 4,
        "expected_components": {
            "Context": True,
            "Behavior": True,
            "Consequence": True,
            "Rule": True,
        },
        "expected_rule_source": "Self-generated",
        "expected_behavior_form": "Enacted change (already doing it)",
        "rationale": "The Answer states a clear self-generated rule and says the behavior is already happening.",
        "explanation_steps": [
            '<strong>Context?</strong> Yes — nighttime/dinner timing ("at night" / "at dinner").',
            '<strong>Behavior?</strong> Yes — eating tortillas, and now avoiding them at dinner.',
            '<strong>Outcome?</strong> Yes — "spike me" is the glucose pattern they learned from the sensor.',
            '<strong>Rule?</strong> Yes — "so now I avoid tortillas at dinner" is clear self-guidance.',
            "<strong>Why Primary 4?</strong> The rule is self-made from their own observation, and "
            '"now I avoid" shows the change is already happening — not just a plan.',
        ],
    },
    {
        "id": "borrowed_rule",
        "question": "Were there any changes to your eating habits?",
        "answer": "My doctor told me sugary drinks can raise my glucose, so I am planning to stop buying soda.",
        "expected_primary": 3,
        "expected_components": {
            "Context": False,
            "Behavior": True,
            "Consequence": True,
            "Rule": True,
        },
        "expected_rule_source": "Borrowed (doctor, family, generic advice)",
        "expected_behavior_form": "Stated intention (planning to do it)",
        "rationale": "The Answer has a behavior-guiding rule, but the source is outside advice rather than self-generated sensor learning.",
    },
]

# Test Drive checks Primary Hierarchy on one clear item per level (0, 2, 3, 4).
# Primary 1 is covered in Step 1 preliminary examples; 3 vs 4 is the key training gap here.
SIMPLE_TEST_DRIVE_ITEM_IDS = [
    "no_contingency",                # clearly Primary 0
    "contingency_recognition",       # clearly Primary 2
    "emerging_self_rule",            # clearly Primary 3
    "explicit_self_generated_rule",  # clearly Primary 4
]


def simple_test_drive_items() -> List[dict]:
    by_id = {item["id"]: item for item in SIMPLE_TRAINING_QUIZ_ITEMS}
    return [by_id[item_id] for item_id in SIMPLE_TEST_DRIVE_ITEM_IDS if item_id in by_id]


def render_theme_css(theme: str) -> None:
    if theme == "Dark":
        st.markdown(
            """
            <style>
            .stApp, .stApp [data-testid="stAppViewContainer"], .stApp [data-testid="stHeader"] {
                background-color: #0f1420 !important;
                color: #e8ecf3 !important;
            }
            .stApp [data-testid="stSidebar"] {
                background-color: #121a29 !important;
                color: #e8ecf3 !important;
                border-right: 1px solid #263247;
            }
            .stMarkdown, .stText, p, label, h1, h2, h3, h4, h5, h6, span, div {
                color: #e8ecf3;
            }
            .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"],
            .stNumberInput input {
                background-color: #1a2334 !important;
                color: #e8ecf3 !important;
                border: 1px solid #3a465d !important;
            }
            .stRadio > div { background: transparent !important; }
            .stButton > button {
                background-color: #1d2b42; color: #e8ecf3; border: 1px solid #3a465d;
            }
            .stButton > button:hover { border-color: #6aa9ff; color: #ffffff; }
            .section-card {
                padding: 14px 16px; border-radius: 12px; border: 1px solid #2f3847;
                margin-bottom: 10px; color: #e8ecf3;
            }
            .card-question { background: #1d3a5e; border-left: 6px solid #6aa9ff; }
            .card-answer { background: #5a3520; border-left: 6px solid #ffb366; }
            .card-step { background: #2b2246; border-left: 6px solid #b39bff; }
            .card-other { background: #3d1f35; border-left: 6px solid #ff8db7; }
            .card-save { background: #173728; border-left: 6px solid #58d68d; }
            .card-info { background: #18212f; border-left: 6px solid #4f8ff7; }
            .card-cgm { background: #152a24; border-left: 6px solid #34d399; }
            .card-demographics { background: #1a2440; border-left: 6px solid #818cf8; margin-bottom: 10px; }
            .instruction-step-title { font-size: 15px; font-weight: 700; margin-bottom: 6px; color: #e8ecf3; }
            .instruction-step-body { font-size: 14px; line-height: 1.45; color: #cbd5e1; }
            .instruction-step-body em { color: #e8ecf3; }
            .score-ruler-card { padding: 12px 16px; }
            .score-ruler-row {
                display: flex; align-items: flex-start; gap: 10px; margin-bottom: 8px;
            }
            .score-ruler-row:last-child { margin-bottom: 0; }
            .score-badge {
                display: inline-flex; align-items: center; justify-content: center;
                width: 26px; height: 26px; min-width: 26px; border-radius: 999px;
                color: #ffffff; font-size: 13px; font-weight: 700; margin-top: 1px;
            }
            .score-ruler-title { font-size: 15px; font-weight: 700; color: #e8ecf3; }
            .score-ruler-hint { font-size: 14px; line-height: 1.45; color: #94a3b8; }
            .qa-card { padding: 10px 14px !important; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.25); }
            .qa-card *:not(mark) { color: #f8fafc !important; }
            .qa-title { font-size: 15px; font-weight: 700; margin-bottom: 5px; letter-spacing: 0; text-transform: uppercase; }
            .qa-role-note { font-size: 11px; font-weight: 600; text-transform: none; opacity: 0.82; }
            .qa-text { font-size: 14px; line-height: 1.38; margin: 3px 0; }
            .qa-label { font-weight: 700; margin-right: 6px; }
            .card-question .qa-label { color: #c9deff !important; }
            .card-answer .qa-label { color: #ffd8b3 !important; }
            .qa-card mark.hl-diet { background: rgba(251, 191, 36, 0.58) !important; color: #fef3c7 !important; padding: 0 3px; border-radius: 3px; font-weight: 600; }
            .qa-card mark.hl-exercise { background: rgba(96, 165, 250, 0.55) !important; color: #dbeafe !important; padding: 0 3px; border-radius: 3px; font-weight: 600; }
            .qa-card mark.hl-change { background: rgba(52, 211, 153, 0.45) !important; color: #d1fae5 !important; padding: 0 3px; border-radius: 3px; font-weight: 600; }
            .qa-card mark.hl-alert { background: rgba(248, 113, 113, 0.52) !important; color: #fee2e2 !important; padding: 0 3px; border-radius: 3px; font-weight: 600; }
            .meta-pill {
                display: inline-block; background: #1f2735; border: 1px solid #3a465d;
                color: #e8ecf3; border-radius: 999px; padding: 4px 10px;
                margin: 2px 8px 8px 0; font-size: 13px;
            }
            .stat-pill {
                display: inline-block; background: #1d2b42; border: 1px solid #3a465d;
                color: #e8ecf3; border-radius: 8px; padding: 6px 12px;
                margin-left: 6px; font-size: 14px; font-weight: 500;
            }
            .stat-pill b { color: #6aa9ff; }
            .level-card {
                padding: 10px 12px; border-radius: 8px; border-left: 4px solid #6aa9ff;
                background: #18212f; margin-bottom: 8px;
            }
            mark.hl-diet { background: rgba(251, 191, 36, 0.42); color: #fef3c7 !important; padding: 0 3px; border-radius: 3px; }
            mark.hl-exercise { background: rgba(96, 165, 250, 0.42); color: #dbeafe !important; padding: 0 3px; border-radius: 3px; }
            mark.hl-change { background: rgba(52, 211, 153, 0.35); color: #d1fae5 !important; padding: 0 3px; border-radius: 3px; }
            mark.hl-alert { background: rgba(248, 113, 113, 0.38); color: #fee2e2 !important; padding: 0 3px; border-radius: 3px; }
            .highlight-legend { font-size: 13px; margin: 4px 0 12px 0; color: #cbd5e1; }
            .highlight-legend mark { font-size: 12px; }
            .cgm-summary-legend {
                display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
                margin: 0 0 8px 0; font-size: 13px;
            }
            .cgm-legend-item {
                display: inline-block; border-radius: 999px; padding: 4px 10px; font-weight: 600;
            }
            .cgm-legend-improved { background: rgba(52, 211, 153, 0.22); color: #6ee7b7; }
            .cgm-legend-worsened { background: rgba(248, 113, 113, 0.22); color: #fca5a5; }
            .cgm-legend-unchanged { background: rgba(148, 163, 184, 0.16); color: #cbd5e1; }
            .cgm-legend-note { color: #94a3b8; font-size: 12px; }
            [data-testid="stExpander"] details {
                border: 1px solid #2f3847 !important; border-radius: 8px; background: #121a29 !important;
            }
            [data-testid="stExpander"] summary {
                background-color: #18212f !important; border-radius: 8px;
            }
            [data-testid="stExpander"] summary:hover,
            [data-testid="stExpander"] details[open] > summary {
                background-color: #1f2b3e !important;
            }
            [data-testid="stExpander"] summary p,
            [data-testid="stExpander"] summary span,
            [data-testid="stExpander"] summary div {
                color: #e8ecf3 !important; font-weight: 600;
            }
            [data-testid="stExpander"] summary svg { fill: #e8ecf3 !important; color: #e8ecf3 !important; }
            </style>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <style>
            .stApp, .stApp [data-testid="stAppViewContainer"], .stApp [data-testid="stHeader"] {
                background-color: #ffffff !important; color: #1f2937 !important;
            }
            .stApp [data-testid="stSidebar"] {
                background-color: #f8f9fc !important; color: #1f2937 !important;
                border-right: 1px solid #dde3ee;
            }
            .stMarkdown, .stText, p, label, h1, h2, h3, h4, h5, h6, span, div {
                color: #1f2937;
            }
            .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"],
            .stNumberInput input {
                background-color: #ffffff !important; color: #1f2937 !important;
                border: 1px solid #d7dbe6 !important;
            }
            .stButton > button {
                background-color: #ffffff; color: #1f2937; border: 1px solid #ccd4e0;
            }
            .stButton > button:hover { border-color: #4f8ff7; color: #111827; }
            .section-card {
                padding: 14px 16px; border-radius: 12px; border: 1px solid #d9dde7;
                margin-bottom: 10px;
            }
            .card-question { background: #eef6ff; border-left: 6px solid #4f8ff7; }
            .card-answer { background: #fff3e8; border-left: 6px solid #ff9f43; }
            .card-step { background: #f6f3ff; border-left: 6px solid #8e6cff; }
            .card-other { background: #fff0f6; border-left: 6px solid #e2558c; }
            .card-save { background: #eefaf1; border-left: 6px solid #35b46b; }
            .card-info { background: #f4f8ff; border-left: 6px solid #4f8ff7; }
            .card-cgm { background: #ecfdf5; border-left: 6px solid #10b981; }
            .card-demographics { background: #eef2ff; border-left: 6px solid #6366f1; margin-bottom: 10px; }
            .instruction-step-title { font-size: 15px; font-weight: 700; margin-bottom: 6px; color: #111827; }
            .instruction-step-body { font-size: 14px; line-height: 1.45; color: #374151; }
            .score-ruler-card { padding: 12px 16px; }
            .score-ruler-row {
                display: flex; align-items: flex-start; gap: 10px; margin-bottom: 8px;
            }
            .score-ruler-row:last-child { margin-bottom: 0; }
            .score-badge {
                display: inline-flex; align-items: center; justify-content: center;
                width: 26px; height: 26px; min-width: 26px; border-radius: 999px;
                color: #ffffff; font-size: 13px; font-weight: 700; margin-top: 1px;
            }
            .score-ruler-title { font-size: 15px; font-weight: 700; color: #111827; }
            .score-ruler-hint { font-size: 14px; line-height: 1.45; color: #64748b; }
            .qa-card { padding: 10px 14px !important; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.05); }
            .qa-card *:not(mark) { color: #1f2937 !important; }
            .qa-title { font-size: 15px; font-weight: 700; margin-bottom: 5px; letter-spacing: 0; text-transform: uppercase; }
            .qa-role-note { font-size: 11px; font-weight: 600; text-transform: none; opacity: 0.78; }
            .qa-text { font-size: 14px; line-height: 1.38; margin: 3px 0; }
            .qa-label { font-weight: 700; margin-right: 6px; }
            .card-question .qa-label { color: #1d4ed8 !important; }
            .card-answer .qa-label { color: #b45309 !important; }
            .qa-card mark.hl-diet { background: rgba(251, 191, 36, 0.65) !important; color: #78350f !important; padding: 0 3px; border-radius: 3px; font-weight: 600; }
            .qa-card mark.hl-exercise { background: rgba(96, 165, 250, 0.55) !important; color: #1e3a8a !important; padding: 0 3px; border-radius: 3px; font-weight: 600; }
            .qa-card mark.hl-change { background: rgba(16, 185, 129, 0.42) !important; color: #065f46 !important; padding: 0 3px; border-radius: 3px; font-weight: 600; }
            .qa-card mark.hl-alert { background: rgba(248, 113, 113, 0.48) !important; color: #991b1b !important; padding: 0 3px; border-radius: 3px; font-weight: 600; }
            .meta-pill {
                display: inline-block; background: #f0f2f6; border: 1px solid #d7dbe6;
                border-radius: 999px; padding: 4px 10px; margin: 2px 8px 8px 0;
                font-size: 13px;
            }
            .stat-pill {
                display: inline-block; background: #eef6ff; border: 1px solid #cfe1ff;
                color: #1f2937; border-radius: 8px; padding: 6px 12px;
                margin-left: 6px; font-size: 14px; font-weight: 500;
            }
            .stat-pill b { color: #2b6cb0; }
            .level-card {
                padding: 10px 12px; border-radius: 8px; border-left: 4px solid #4f8ff7;
                background: #f4f8ff; margin-bottom: 8px;
            }
            mark.hl-diet { background: rgba(251, 191, 36, 0.38); color: #78350f !important; padding: 0 3px; border-radius: 3px; }
            mark.hl-exercise { background: rgba(96, 165, 250, 0.35); color: #1e3a8a !important; padding: 0 3px; border-radius: 3px; }
            mark.hl-change { background: rgba(16, 185, 129, 0.28); color: #065f46 !important; padding: 0 3px; border-radius: 3px; }
            mark.hl-alert { background: rgba(248, 113, 113, 0.32); color: #991b1b !important; padding: 0 3px; border-radius: 3px; }
            .highlight-legend { font-size: 13px; margin: 4px 0 12px 0; color: #4b5563; }
            .highlight-legend mark { font-size: 12px; }
            .cgm-summary-legend {
                display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
                margin: 0 0 8px 0; font-size: 13px;
            }
            .cgm-legend-item {
                display: inline-block; border-radius: 999px; padding: 4px 10px; font-weight: 600;
            }
            .cgm-legend-improved { background: rgba(16, 185, 129, 0.20); color: #065f46; }
            .cgm-legend-worsened { background: rgba(239, 68, 68, 0.18); color: #991b1b; }
            .cgm-legend-unchanged { background: rgba(100, 116, 139, 0.14); color: #475569; }
            .cgm-legend-note { color: #64748b; font-size: 12px; }
            [data-testid="stExpander"] details {
                border: 1px solid #d9dde7 !important; border-radius: 8px; background: #ffffff !important;
            }
            [data-testid="stExpander"] summary {
                background-color: #f4f8ff !important; border-radius: 8px;
            }
            [data-testid="stExpander"] summary:hover,
            [data-testid="stExpander"] details[open] > summary {
                background-color: #e8f0ff !important;
            }
            [data-testid="stExpander"] summary p,
            [data-testid="stExpander"] summary span,
            [data-testid="stExpander"] summary div {
                color: #1f2937 !important; font-weight: 600;
            }
            [data-testid="stExpander"] summary svg { fill: #1f2937 !important; color: #1f2937 !important; }
            </style>
            """,
            unsafe_allow_html=True,
        )
    st.markdown(
        """
        <style>
        .code-hover-wrap {
            display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 10px 0;
        }
        .code-hover-chip {
            display: inline-block; border-radius: 999px; border: 1px solid #cbd5e1;
            background: rgba(255,255,255,0.62); padding: 3px 9px; font-size: 12px;
            line-height: 1.45; cursor: help; max-width: 100%;
        }
        .code-hover-chip:hover {
            border-color: #4f8ff7; box-shadow: 0 1px 5px rgba(79,143,247,0.22);
        }
        .sticky-qa-panel {
            position: fixed; top: 3.5rem; left: 21rem; right: 1.5rem; z-index: 999;
            padding: 6px 8px; border-radius: 8px; margin: 8px 0 12px 0;
            background: rgba(255, 255, 255, 0.97);
            box-shadow: 0 5px 14px rgba(15, 23, 42, 0.13);
        }
        .block-container:has(.sticky-qa-panel) {
            padding-top: 11rem !important;
        }
        .frozen-qa-spacer {
            display: none;
        }
        .sticky-qa-grid {
            display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
            gap: 8px; align-items: stretch;
        }
        .sticky-qa-panel .qa-card {
            max-height: 23vh; overflow-y: auto; margin-bottom: 0;
        }
        .code-option-row {
            border: 1px solid #d9dde7; border-radius: 8px; padding: 8px 10px;
            margin-bottom: 8px; background: rgba(255, 255, 255, 0.45);
        }
        .code-option-label { font-weight: 700; margin-bottom: 2px; }
        .code-option-meta { font-size: 12px; color: #64748b; margin-bottom: 3px; }
        .code-option-definition { font-size: 13px; line-height: 1.45; }
        .marking-feedback-header {
            font-size: 12px; font-weight: 700; color: #475569; margin: 8px 0 2px 0;
            text-transform: uppercase;
        }
        .marking-label {
            font-size: 14px; line-height: 1.42; padding-top: 2px;
        }
        .marking-selected-note {
            font-size: 14px; line-height: 1.42; padding: 7px 0 0 0;
        }
        .stApp [data-testid="stSidebar"] .highlight-legend { display: none; }
        @media (max-width: 900px) {
            .sticky-qa-panel { position: sticky; top: 0.5rem; padding: 0; box-shadow: none; background: transparent; }
            .block-container:has(.sticky-qa-panel) { padding-top: 1rem !important; }
            .frozen-qa-spacer { display: none; }
            .sticky-qa-grid { grid-template-columns: 1fr; }
            .sticky-qa-panel .qa-card { max-height: 22vh; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ----------------------------- User auth -----------------------------

def load_users() -> Dict[str, dict]:
    if not USERS_PATH.exists():
        with USER_FILE_LOCK:
            if not USERS_PATH.exists():
                USERS_PATH.write_text("{}", encoding="utf-8")
    try:
        return json.loads(USERS_PATH.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}


def save_users(users: Dict[str, dict]) -> None:
    with USER_FILE_LOCK:
        tmp_path = USERS_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(USERS_PATH)


def utc_now_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def register_user(username: str, password: str, display_name: str) -> Optional[str]:
    username = username.strip().lower()
    if not username or len(username) < 3:
        return "Username must be at least 3 characters."
    if not password or len(password) < 6:
        return "Password must be at least 6 characters."
    with USER_FILE_LOCK:
        users = load_users()
        if username in users:
            return "Username already exists."
        users[username] = {
            "password_hash": hash_password(password),
            "display_name": (display_name or username).strip(),
            "created_at_utc": utc_now_iso_z(),
            "role": "coder",
            "training_completed": False,
            "training_completed_at_utc": None,
            "simple_training_completed": False,
            "simple_training_completed_at_utc": None,
            "simple_training_version": None,
        }
        save_users(users)
    return None


def authenticate(username: str, password: str) -> Optional[dict]:
    username = username.strip().lower()
    users = load_users()
    user = users.get(username)
    if not user:
        return None
    if not verify_password(password, user.get("password_hash", "")):
        return None
    user.setdefault("training_completed", False)
    user.setdefault("training_completed_at_utc", None)
    user.setdefault("simple_training_completed", False)
    user.setdefault("simple_training_completed_at_utc", None)
    user.setdefault("simple_training_version", None)
    return {"username": username, **user}


def get_session_secret() -> bytes:
    if not SESSION_SECRET_PATH.exists():
        SESSION_SECRET_PATH.write_text(secrets.token_hex(32), encoding="utf-8")
    return SESSION_SECRET_PATH.read_text(encoding="utf-8").strip().encode("utf-8")


def create_session_token(username: str) -> str:
    username = username.strip().lower()
    issued_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = json.dumps({"u": username, "iat": issued_at}, separators=(",", ":"))
    signature = hmac.new(get_session_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}|{signature}"
    return urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def verify_session_token(token: str) -> Optional[str]:
    if not token:
        return None
    try:
        raw = urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        payload, signature = raw.rsplit("|", 1)
        expected = hmac.new(get_session_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(payload)
        issued_at = datetime.fromisoformat(str(data["iat"]).replace("Z", "+00:00"))
        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - issued_at > timedelta(days=SESSION_MAX_AGE_DAYS):
            return None
        username = str(data.get("u", "")).strip().lower()
        return username or None
    except Exception:
        return None


def get_cookie_manager() -> CookieManager:
    if "cookie_manager" not in st.session_state:
        st.session_state.cookie_manager = CookieManager(key="g2_auth_cookie_manager")
    return st.session_state.cookie_manager


def _cookie_secure_flag() -> Optional[bool]:
    try:
        forwarded = str(st.context.headers.get("X-Forwarded-Proto", "") or "").lower()
        if forwarded == "https":
            return True
        if forwarded == "http":
            return False
    except Exception:
        pass
    return None


def read_auth_token() -> str:
    """Read the signed session token from the browser (works reliably on F5 refresh)."""
    try:
        token = st.context.cookies.get(SESSION_COOKIE_NAME)
        if token:
            return str(token)
    except Exception:
        pass
    try:
        cookies = get_cookie_manager().get_all(key="auth_read_get_all") or {}
        token = cookies.get(SESSION_COOKIE_NAME)
        if token:
            return str(token)
    except Exception:
        pass
    return ""


def set_auth_cookie(username: str, *, remember: bool = True) -> None:
    token = create_session_token(username)
    secure = _cookie_secure_flag()
    if remember:
        expires = datetime.now(timezone.utc) + timedelta(days=SESSION_MAX_AGE_DAYS)
        get_cookie_manager().set(
            SESSION_COOKIE_NAME,
            token,
            expires_at=expires,
            path="/",
            same_site="lax",
            secure=secure,
            key=f"set_auth_cookie_{username}",
        )
    else:
        get_cookie_manager().set(
            SESSION_COOKIE_NAME,
            token,
            max_age=60 * 60 * 12,
            path="/",
            same_site="lax",
            secure=secure,
            key=f"set_auth_cookie_{username}",
        )


def clear_auth_cookie() -> None:
    secure = _cookie_secure_flag()
    try:
        expired = datetime.now(timezone.utc) - timedelta(days=1)
        get_cookie_manager().set(
            SESSION_COOKIE_NAME,
            "",
            expires_at=expired,
            path="/",
            same_site="lax",
            secure=secure,
            key="clear_auth_cookie_expire",
        )
        get_cookie_manager().delete(
            SESSION_COOKIE_NAME,
            path="/",
            key="clear_auth_cookie_delete",
        )
    except Exception:
        pass


def sign_out_user() -> None:
    st.session_state.user = None
    st.session_state["_signed_out"] = True
    st.session_state.pop("_auth_cookie_retries", None)
    clear_auth_cookie()
    st.cache_data.clear()


def persist_user_session(username: Optional[str] = None) -> None:
    """Reload user record into session; never clear login on a busy/missing users file."""
    name = (username or (st.session_state.get("user") or {}).get("username") or "").strip().lower()
    if not name:
        return
    users = load_users()
    record = users.get(name)
    if record:
        st.session_state.user = {"username": name, **record}
    elif st.session_state.get("user"):
        st.session_state.user["username"] = name


def restore_user_from_cookie(cookies: Optional[dict] = None) -> bool:
    if st.session_state.get("_signed_out"):
        return False
    if st.session_state.get("user"):
        return True
    token = ""
    if cookies:
        token = str(cookies.get(SESSION_COOKIE_NAME, "") or "")
    if not token:
        token = read_auth_token()
    if not token:
        return False
    username = verify_session_token(token)
    if not username:
        clear_auth_cookie()
        return False
    users = load_users()
    user = users.get(username)
    if not user:
        # Do not clear the auth cookie here — users.json may be mid-write (e.g. Test Drive save).
        return False
    user.setdefault("training_completed", False)
    user.setdefault("training_completed_at_utc", None)
    user.setdefault("simple_training_completed", False)
    user.setdefault("simple_training_completed_at_utc", None)
    user.setdefault("simple_training_version", None)
    st.session_state.user = {"username": username, **user}
    return True


def try_restore_auth_session() -> bool:
    if st.session_state.get("_signed_out"):
        return False
    if st.session_state.get("user"):
        return True
    if restore_user_from_cookie():
        return True
    cookies = get_cookie_manager().get_all(key="auth_restore_get_all")
    if cookies is None:
        return False
    if cookies:
        return restore_user_from_cookie(cookies)
    return restore_user_from_cookie()


def init_auth_state() -> None:
    if "user" not in st.session_state:
        st.session_state.user = None


def mark_training_completed(username: str) -> None:
    with USER_FILE_LOCK:
        users = load_users()
        if username in users:
            users[username]["training_completed"] = True
            users[username]["training_completed_at_utc"] = utc_now_iso_z()
            save_users(users)


def simple_training_is_complete(user: dict) -> bool:
    return (
        bool(user.get("simple_training_completed", False))
        and str(user.get("simple_training_version", "")) == SIMPLE_TRAINING_VERSION
    )


def mark_simple_training_completed(username: str) -> None:
    with USER_FILE_LOCK:
        users = load_users()
        if username in users:
            ts = utc_now_iso_z()
            users[username]["simple_training_completed"] = True
            users[username]["simple_training_completed_at_utc"] = ts
            users[username]["simple_training_version"] = SIMPLE_TRAINING_VERSION
            save_users(users)


def reload_user_into_session() -> None:
    persist_user_session()


# ----------------------------- Data loading -----------------------------

@st.cache_data(show_spinner=False)
def load_codes() -> pd.DataFrame:
    if not CODES_PATH.exists():
        raise FileNotFoundError(f"Code file not found: {CODES_PATH}")
    df = pd.read_csv(CODES_PATH, encoding="utf-8-sig")
    for col in ["code_id", "code_group", "subgroup", "code_name", "definition"]:
        if col not in df.columns:
            raise ValueError(f"Missing required column in code CSV: {col}")
    return df.fillna("")


@st.cache_data(show_spinner=False)
def load_codebook_tree() -> dict:
    if not TREE_PATH.exists():
        return {"groups": []}
    return json.loads(TREE_PATH.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_line_items() -> List[dict]:
    if not LINE_ITEMS_PATH.exists():
        raise FileNotFoundError(f"Line items file not found: {LINE_ITEMS_PATH}")
    items: List[dict] = []
    with LINE_ITEMS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


@st.cache_data(show_spinner=False)
def build_qa_items() -> List[dict]:
    items = load_line_items()
    grouped: Dict[str, List[dict]] = {}
    for item in items:
        grouped.setdefault(item["subject_id"], []).append(item)

    qa_items: List[dict] = []
    # Sort subjects alphabetically/numerically for deterministic ordering
    for subject_id in sorted(grouped.keys()):
        rows = sorted(grouped[subject_id], key=lambda x: int(x["line_no"]))
        i = 0
        while i < len(rows) - 1:
            q = rows[i]
            a = rows[i + 1]
            if q.get("speaker_role") == "interviewer" and a.get("speaker_role") == "subject":
                qa_items.append(
                    {
                        "qa_id": f"{subject_id}_Q{int(q['line_no']):03d}_A{int(a['line_no']):03d}",
                        "subject_id": subject_id,
                        "question_line_no": int(q["line_no"]),
                        "answer_line_no": int(a["line_no"]),
                        "question_en": q.get("text_en", ""),
                        "question_es": q.get("text_es", ""),
                        "answer_en": a.get("text_en", ""),
                        "answer_es": a.get("text_es", ""),
                    }
                )
                i += 2
            else:
                i += 1
    return qa_items


@st.cache_data(show_spinner=False)
def load_check_samples() -> pd.DataFrame:
    if not CHECK_SAMPLES_PATH.exists():
        return pd.DataFrame()
    df = pd.read_csv(CHECK_SAMPLES_PATH, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    required = {"subject_id", "qa_id", "expected_primary", "rationale"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required column(s) in check sample CSV: {', '.join(sorted(missing))}")
    if "attention_check" not in df.columns:
        df["attention_check"] = "0"
    return df.fillna("")


def check_sample_map() -> Dict[str, dict]:
    df = load_check_samples()
    if df.empty:
        return {}
    return {str(row["qa_id"]): row.to_dict() for _, row in df.iterrows()}


def compare_annotation_to_check_sample(annotation: dict, check_sample: dict) -> dict:
    expected_primary = parse_annotation_int(check_sample.get("expected_primary"), -1)
    saved_primary = parse_annotation_int(annotation.get("primary_hierarchy"), -1)
    component_results = []
    for field, label in AGREEMENT_COMPONENT_FIELDS:
        expected_col = f"expected_{field.replace('component_', '')}"
        expected_value = parse_annotation_bool(check_sample.get(expected_col))
        saved_value = parse_annotation_bool(annotation.get(field))
        component_results.append((label, saved_value == expected_value))
    component_match_count = sum(1 for _, matched in component_results if matched)
    expected_rule_source = normalize_taxonomy_selection(
        check_sample.get("expected_rule_source"),
        RULE_SOURCE_OPTIONS,
    )
    saved_rule_source = normalize_taxonomy_selection(
        annotation.get("rule_source"),
        RULE_SOURCE_OPTIONS,
    )
    expected_behavior_form = normalize_taxonomy_selection(
        check_sample.get("expected_behavior_form"),
        BEHAVIOR_FORM_OPTIONS,
    )
    saved_behavior_form = normalize_taxonomy_selection(
        annotation.get("behavior_form"),
        BEHAVIOR_FORM_OPTIONS,
    )
    expected_rule_taxonomy = (
        expected_primary >= 3
        or parse_annotation_bool(check_sample.get("expected_rule"))
        or bool(expected_rule_source)
        or bool(expected_behavior_form)
    )
    is_attention_check = parse_annotation_bool(check_sample.get("attention_check"))
    primary_match = saved_primary == expected_primary
    return {
        "qa_id": str(check_sample.get("qa_id", "")),
        "subject_id": str(check_sample.get("subject_id", "")),
        "saved_primary": saved_primary,
        "expected_primary": expected_primary,
        "primary_match": primary_match,
        "component_matches": f"{component_match_count}/{len(component_results)}",
        "components_all_match": component_match_count == len(component_results),
        "rule_source_match": saved_rule_source == expected_rule_source,
        "behavior_form_match": saved_behavior_form == expected_behavior_form,
        "rule_taxonomy_expected": expected_rule_taxonomy,
        "is_attention_check": is_attention_check,
        "attention_check_pass": (primary_match if is_attention_check else None),
        "rationale": str(check_sample.get("rationale", "")),
    }


def ensure_annotations_file() -> None:
    if ANNOTATIONS_PATH.exists():
        return
    with ANNOTATIONS_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ANNOTATION_COLUMNS)
        writer.writeheader()


def parse_annotation_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def parse_annotation_bool(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    if not text or text in {"nan", "none", "0", "0.0", "false", "no"}:
        return False
    if text in {"1", "1.0", "true", "yes"}:
        return True
    try:
        return int(float(text)) == 1
    except ValueError:
        return False


def normalize_annotation_row(row: dict) -> dict:
    out = {col: "" for col in ANNOTATION_COLUMNS}
    for key, value in row.items():
        if key not in ANNOTATION_COLUMNS:
            continue
        if pd.isna(value):
            out[key] = ""
        else:
            out[key] = str(value).strip()

    out["question_line_no"] = str(parse_annotation_int(out.get("question_line_no"), 0))
    out["answer_line_no"] = str(parse_annotation_int(out.get("answer_line_no"), 0))
    out["primary_hierarchy"] = str(parse_annotation_int(out.get("primary_hierarchy"), 0))
    out["confidence"] = str(parse_annotation_int(out.get("confidence"), 3))
    out["secondary_component_score"] = str(parse_annotation_int(out.get("secondary_component_score"), 0))
    for flag_key in (
        "component_context",
        "component_behavior",
        "component_consequence",
        "component_rule",
        "is_other",
    ):
        out[flag_key] = "1" if parse_annotation_bool(out.get(flag_key)) else "0"
    return out


def load_annotations() -> pd.DataFrame:
    ensure_annotations_file()
    df = pd.read_csv(ANNOTATIONS_PATH, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    for col in ANNOTATION_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[ANNOTATION_COLUMNS].fillna("")
    legacy_str = df["selected_code_id"].astype(str).str.strip()
    needs_migration = (
        (df["selected_code_ids"].astype(str).str.strip() == "")
        & (legacy_str != "")
        & (legacy_str != OTHER_CODE)
    )
    if needs_migration.any():
        df.loc[needs_migration, "selected_code_ids"] = df.loc[needs_migration, "selected_code_id"]
    if not df.empty:
        normalized_rows = [normalize_annotation_row(row.to_dict()) for _, row in df.iterrows()]
        df = pd.DataFrame(normalized_rows, columns=ANNOTATION_COLUMNS)
    return df


def parse_code_ids(raw: str) -> List[str]:
    if not raw:
        return []
    return [c.strip() for c in str(raw).split(CODE_DELIMITER) if c.strip()]


def join_code_ids(code_ids: List[str]) -> str:
    return CODE_DELIMITER.join([c for c in code_ids if c])


def parse_code_confidences(raw: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if not raw:
        return out
    for part in str(raw).split(CODE_DELIMITER):
        part = part.strip()
        if not part or "=" not in part:
            continue
        code_id, score = part.rsplit("=", 1)
        code_id = code_id.strip()
        if not code_id:
            continue
        out[code_id] = max(1, min(5, parse_annotation_int(score, 3)))
    return out


def join_code_confidences(code_confidences: Dict[str, int], selected_code_ids: List[str]) -> str:
    parts = []
    for code_id in selected_code_ids:
        if not code_id:
            continue
        score = max(1, min(5, parse_annotation_int(code_confidences.get(code_id), 3)))
        parts.append(f"{code_id}={score}")
    return CODE_DELIMITER.join(parts)


def parse_code_comments(raw: str) -> Dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v).strip() for k, v in data.items() if str(v).strip()}


def join_code_comments(code_comments: Dict[str, str], selected_code_ids: List[str]) -> str:
    out = {
        code_id: str(code_comments.get(code_id, "")).strip()
        for code_id in selected_code_ids
        if code_id and str(code_comments.get(code_id, "")).strip()
    }
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")) if out else ""


def parse_annotation_confidences(raw: str) -> Dict[str, int]:
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    parsed: Dict[str, int] = {}
    for key, value in data.items():
        score = parse_annotation_int(value, 0)
        if 1 <= score <= 5:
            parsed[str(key)] = score
    return parsed


def join_annotation_confidences(annotation_confidences: Dict[str, int]) -> str:
    out = {
        str(mark_id): max(1, min(5, parse_annotation_int(score, 3)))
        for mark_id, score in annotation_confidences.items()
        if str(mark_id).strip()
    }
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")) if out else ""


def parse_annotation_comments(raw: str) -> Dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v).strip() for k, v in data.items() if str(v).strip()}


def join_annotation_comments(annotation_comments: Dict[str, str]) -> str:
    out = {
        str(mark_id): str(comment).strip()
        for mark_id, comment in annotation_comments.items()
        if str(mark_id).strip() and str(comment).strip()
    }
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")) if out else ""


def parse_issue_flags(raw: str) -> List[str]:
    if not raw:
        return []
    flags = [flag.strip() for flag in str(raw).split(ISSUE_FLAG_DELIMITER) if flag.strip()]
    normalized = [ISSUE_FLAG_ALIASES.get(flag, flag) for flag in flags]
    return [flag for flag in normalized if flag in ISSUE_FLAG_OPTIONS]


def join_issue_flags(issue_flags: List[str]) -> str:
    return ISSUE_FLAG_DELIMITER.join([flag for flag in issue_flags if flag in ISSUE_FLAG_OPTIONS])


def parse_delimited_options(raw: str, valid_options: List[str]) -> List[str]:
    if not raw:
        return []
    option_set = set(valid_options)
    values = [value.strip() for value in str(raw).split(ISSUE_FLAG_DELIMITER) if value.strip()]
    return [value for value in values if value in option_set and value != "N/A"]


def join_delimited_options(selected_options: List[str], valid_options: List[str]) -> str:
    option_set = set(valid_options)
    cleaned: List[str] = []
    for option in selected_options:
        if option in option_set and option != "N/A" and option not in cleaned:
            cleaned.append(option)
    return ISSUE_FLAG_DELIMITER.join(cleaned) if cleaned else "N/A"


def user_is_admin(user: dict) -> bool:
    username = str(user.get("username", "")).strip().lower()
    role = str(user.get("role", "")).strip().lower()
    return username in ADMIN_USERNAMES or role in {"admin", "lead", "pi"}


def coder_display_label(username: str, users: Dict[str, dict]) -> str:
    username_clean = str(username).strip().lower()
    profile = users.get(username_clean, {})
    display_name = str(profile.get("display_name", "")).strip()
    if display_name and display_name.lower() != username_clean:
        return f"{display_name} ({username_clean})"
    return username_clean or "unknown"


def normalize_taxonomy_selection(raw: object, valid_options: List[str]) -> tuple:
    if raw is None:
        return tuple()
    valid_set = set(valid_options)
    cleaned: List[str] = []
    for part in str(raw).split(ISSUE_FLAG_DELIMITER):
        option = part.strip()
        if not option or option.lower() in {"nan", "none"} or option == "N/A":
            continue
        if option in valid_set and option not in cleaned:
            cleaned.append(option)
    return tuple(sorted(cleaned))


def agreement_ready_annotations(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=ANNOTATION_COLUMNS)
    out = df.copy()
    out["coder_username"] = out["coder_username"].astype(str).str.strip().str.lower()
    out["qa_id"] = out["qa_id"].astype(str).str.strip()
    out = out[(out["coder_username"] != "") & (out["qa_id"] != "")]
    if out.empty:
        return out
    out = out.sort_values(["coder_username", "qa_id", "updated_at_utc"])
    return out.drop_duplicates(["coder_username", "qa_id"], keep="last")


def annotation_map_for_coder(df: pd.DataFrame, username: str) -> Dict[str, dict]:
    username_clean = str(username).strip().lower()
    if df.empty:
        return {}
    mine = df[df["coder_username"].astype(str).str.lower() == username_clean]
    return {str(row["qa_id"]): row.to_dict() for _, row in mine.iterrows()}


def row_primary_value(row: dict) -> int:
    return max(0, min(4, parse_annotation_int(row.get("primary_hierarchy"), 0)))


def row_binary_value(row: dict, field: str) -> int:
    return 1 if parse_annotation_bool(row.get(field)) else 0


def row_component_tuple(row: dict) -> tuple:
    return tuple(row_binary_value(row, field) for field, _ in AGREEMENT_COMPONENT_FIELDS)


def safe_mean(values: List[float]) -> Optional[float]:
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def exact_agreement_fraction(values_a: List[object], values_b: List[object]) -> Optional[float]:
    n = min(len(values_a), len(values_b))
    if n <= 0:
        return None
    return sum(1 for idx in range(n) if values_a[idx] == values_b[idx]) / n


def cohen_kappa(values_a: List[object], values_b: List[object], labels: List[object]) -> Optional[float]:
    n = min(len(values_a), len(values_b))
    if n <= 0:
        return None
    a = values_a[:n]
    b = values_b[:n]
    observed_labels = list(dict.fromkeys(labels + a + b))
    observed_agreement = exact_agreement_fraction(a, b)
    if observed_agreement is None:
        return None
    counts_a = Counter(a)
    counts_b = Counter(b)
    expected_agreement = sum((counts_a[label] / n) * (counts_b[label] / n) for label in observed_labels)
    denominator = 1.0 - expected_agreement
    if abs(denominator) < 1e-12:
        return None
    return (observed_agreement - expected_agreement) / denominator


def quadratic_weighted_kappa(values_a: List[int], values_b: List[int], labels: List[int]) -> Optional[float]:
    n = min(len(values_a), len(values_b))
    if n <= 0 or len(labels) < 2:
        return None
    ordered_labels = list(labels)
    position = {label: idx for idx, label in enumerate(ordered_labels)}
    a = [value for value in values_a[:n] if value in position]
    b = [value for value in values_b[:n] if value in position]
    if len(a) != n or len(b) != n:
        return None
    scale = len(ordered_labels) - 1
    counts_a = Counter(a)
    counts_b = Counter(b)
    observed_disagreement = 0.0
    for left, right in zip(a, b):
        observed_disagreement += ((position[left] - position[right]) / scale) ** 2
    observed_disagreement /= n

    expected_disagreement = 0.0
    for left in ordered_labels:
        for right in ordered_labels:
            weight = ((position[left] - position[right]) / scale) ** 2
            expected_disagreement += weight * (counts_a[left] / n) * (counts_b[right] / n)
    if abs(expected_disagreement) < 1e-12:
        return None
    return 1.0 - (observed_disagreement / expected_disagreement)


def mean_absolute_difference(values_a: List[int], values_b: List[int]) -> Optional[float]:
    n = min(len(values_a), len(values_b))
    if n <= 0:
        return None
    return sum(abs(values_a[idx] - values_b[idx]) for idx in range(n)) / n


def rule_taxonomy_relevant(row: dict) -> bool:
    return (
        row_primary_value(row) >= 3
        or parse_annotation_bool(row.get("component_rule"))
        or bool(normalize_taxonomy_selection(row.get("rule_source"), RULE_SOURCE_OPTIONS))
        or bool(normalize_taxonomy_selection(row.get("behavior_form"), BEHAVIOR_FORM_OPTIONS))
    )


def pairwise_agreement_row(
    coder_a: str,
    coder_b: str,
    annotations_a: Dict[str, dict],
    annotations_b: Dict[str, dict],
) -> dict:
    shared_ids = sorted(set(annotations_a) & set(annotations_b))
    primary_a = [row_primary_value(annotations_a[qa_id]) for qa_id in shared_ids]
    primary_b = [row_primary_value(annotations_b[qa_id]) for qa_id in shared_ids]
    component_exact_values_a = [row_component_tuple(annotations_a[qa_id]) for qa_id in shared_ids]
    component_exact_values_b = [row_component_tuple(annotations_b[qa_id]) for qa_id in shared_ids]
    component_kappas: List[float] = []
    for field, _ in AGREEMENT_COMPONENT_FIELDS:
        comp_a = [row_binary_value(annotations_a[qa_id], field) for qa_id in shared_ids]
        comp_b = [row_binary_value(annotations_b[qa_id], field) for qa_id in shared_ids]
        kappa = cohen_kappa(comp_a, comp_b, [0, 1])
        if kappa is not None:
            component_kappas.append(kappa)

    rule_ids = [
        qa_id
        for qa_id in shared_ids
        if rule_taxonomy_relevant(annotations_a[qa_id]) or rule_taxonomy_relevant(annotations_b[qa_id])
    ]
    rule_a = [
        normalize_taxonomy_selection(annotations_a[qa_id].get("rule_source"), RULE_SOURCE_OPTIONS)
        for qa_id in rule_ids
    ]
    rule_b = [
        normalize_taxonomy_selection(annotations_b[qa_id].get("rule_source"), RULE_SOURCE_OPTIONS)
        for qa_id in rule_ids
    ]
    behavior_a = [
        normalize_taxonomy_selection(annotations_a[qa_id].get("behavior_form"), BEHAVIOR_FORM_OPTIONS)
        for qa_id in rule_ids
    ]
    behavior_b = [
        normalize_taxonomy_selection(annotations_b[qa_id].get("behavior_form"), BEHAVIOR_FORM_OPTIONS)
        for qa_id in rule_ids
    ]

    return {
        "coder_a": coder_a,
        "coder_b": coder_b,
        "shared_items": len(shared_ids),
        "low_overlap": len(shared_ids) < AGREEMENT_MIN_OVERLAP,
        "primary_exact": exact_agreement_fraction(primary_a, primary_b),
        "primary_qwk": quadratic_weighted_kappa(primary_a, primary_b, AGREEMENT_PRIMARY_LABELS),
        "primary_kappa": cohen_kappa(primary_a, primary_b, AGREEMENT_PRIMARY_LABELS),
        "primary_mean_abs_diff": mean_absolute_difference(primary_a, primary_b),
        "components_exact": exact_agreement_fraction(component_exact_values_a, component_exact_values_b),
        "components_mean_kappa": safe_mean(component_kappas),
        "rule_source_exact": exact_agreement_fraction(rule_a, rule_b),
        "rule_source_items": len(rule_ids),
        "behavior_form_exact": exact_agreement_fraction(behavior_a, behavior_b),
        "behavior_form_items": len(rule_ids),
    }


def build_pairwise_agreement_table(annotations_df: pd.DataFrame) -> pd.DataFrame:
    ready = agreement_ready_annotations(annotations_df)
    if ready.empty:
        return pd.DataFrame()
    coders = sorted(ready["coder_username"].astype(str).unique())
    coder_maps = {coder: annotation_map_for_coder(ready, coder) for coder in coders}
    rows = []
    for idx, coder_a in enumerate(coders):
        for coder_b in coders[idx + 1 :]:
            row = pairwise_agreement_row(coder_a, coder_b, coder_maps[coder_a], coder_maps[coder_b])
            if row["shared_items"] > 0:
                rows.append(row)
    return pd.DataFrame(rows)


def build_check_sample_agreement_table(
    annotations_df: pd.DataFrame,
    check_samples: Dict[str, dict],
) -> pd.DataFrame:
    ready = agreement_ready_annotations(annotations_df)
    if ready.empty or not check_samples:
        return pd.DataFrame()
    rows = []
    for coder in sorted(ready["coder_username"].astype(str).unique()):
        ann_map = annotation_map_for_coder(ready, coder)
        comparisons = [
            compare_annotation_to_check_sample(ann_map[qa_id], expected)
            for qa_id, expected in check_samples.items()
            if qa_id in ann_map
        ]
        total = len(comparisons)
        taxonomy_rows = [row for row in comparisons if row["rule_taxonomy_expected"]]
        attention_rows = [row for row in comparisons if row.get("is_attention_check")]
        attention_reached = len(attention_rows)
        attention_accuracy = (
            sum(1 for row in attention_rows if row["primary_match"]) / attention_reached
            if attention_reached
            else None
        )
        attention_flag = bool(
            attention_reached >= ATTENTION_CHECK_MIN_REACHED
            and attention_accuracy is not None
            and attention_accuracy < ATTENTION_CHECK_PASS_THRESHOLD
        )
        rows.append(
            {
                "coder": coder,
                "check_samples_reached": total,
                "hidden_check_coverage": total / len(check_samples) if check_samples else None,
                "primary_gold_accuracy": (
                    sum(1 for row in comparisons if row["primary_match"]) / total if total else None
                ),
                "components_gold_accuracy": (
                    sum(1 for row in comparisons if row["components_all_match"]) / total if total else None
                ),
                "rule_source_gold_accuracy": (
                    sum(1 for row in taxonomy_rows if row["rule_source_match"]) / len(taxonomy_rows)
                    if taxonomy_rows
                    else None
                ),
                "behavior_form_gold_accuracy": (
                    sum(1 for row in taxonomy_rows if row["behavior_form_match"]) / len(taxonomy_rows)
                    if taxonomy_rows
                    else None
                ),
                "rule_taxonomy_items": len(taxonomy_rows),
                "attention_checks_reached": attention_reached,
                "attention_check_accuracy": attention_accuracy,
                "attention_flag": attention_flag,
            }
        )
    return pd.DataFrame(rows)


def user_check_sample_details(
    annotations_df: pd.DataFrame,
    check_samples: Dict[str, dict],
    username: str,
) -> pd.DataFrame:
    ready = agreement_ready_annotations(annotations_df)
    ann_map = annotation_map_for_coder(ready, username)
    rows = [
        compare_annotation_to_check_sample(ann_map[qa_id], expected)
        for qa_id, expected in check_samples.items()
        if qa_id in ann_map
    ]
    return pd.DataFrame(rows)


def user_attention_check_status(
    annotations_df: pd.DataFrame,
    check_samples: Dict[str, dict],
    username: str,
) -> dict:
    """Primary accuracy on the clear attention-check items for one coder."""
    ready = agreement_ready_annotations(annotations_df)
    ann_map = annotation_map_for_coder(ready, username)
    attention_rows = [
        compare_annotation_to_check_sample(ann_map[qa_id], expected)
        for qa_id, expected in check_samples.items()
        if qa_id in ann_map and parse_annotation_bool(expected.get("attention_check"))
    ]
    reached = len(attention_rows)
    passed = sum(1 for row in attention_rows if row["primary_match"])
    accuracy = passed / reached if reached else None
    flagged = bool(
        reached >= ATTENTION_CHECK_MIN_REACHED
        and accuracy is not None
        and accuracy < ATTENTION_CHECK_PASS_THRESHOLD
    )
    return {"reached": reached, "passed": passed, "accuracy": accuracy, "flagged": flagged}


def metric_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def format_percent_metric(value: object) -> str:
    if metric_missing(value):
        return "N/A"
    return f"{float(value) * 100:.1f}%"


def format_kappa_metric(value: object) -> str:
    if metric_missing(value):
        return "N/A"
    return f"{float(value):.2f}"


def format_number_metric(value: object, digits: int = 2) -> str:
    if metric_missing(value):
        return "N/A"
    return f"{float(value):.{digits}f}"


def format_pairwise_agreement_table(df: pd.DataFrame, users: Dict[str, dict]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    display = pd.DataFrame()
    display["Coder A"] = df["coder_a"].map(lambda username: coder_display_label(username, users))
    display["Coder B"] = df["coder_b"].map(lambda username: coder_display_label(username, users))
    display["Shared Items"] = df["shared_items"].astype(int)
    display["Overlap Note"] = df["low_overlap"].map(
        lambda low: f"< {AGREEMENT_MIN_OVERLAP}; interpret cautiously" if low else ""
    )
    display["Primary Exact"] = df["primary_exact"].map(format_percent_metric)
    display["Primary QWK"] = df["primary_qwk"].map(format_kappa_metric)
    display["Primary Kappa"] = df["primary_kappa"].map(format_kappa_metric)
    display["Primary Mean Abs Diff"] = df["primary_mean_abs_diff"].map(lambda value: format_number_metric(value, 2))
    display["Components Exact"] = df["components_exact"].map(format_percent_metric)
    display["Components Mean Kappa"] = df["components_mean_kappa"].map(format_kappa_metric)
    display["Rule Source Exact"] = df["rule_source_exact"].map(format_percent_metric)
    display["Rule Source Items"] = df["rule_source_items"].astype(int)
    display["Behavior Form Exact"] = df["behavior_form_exact"].map(format_percent_metric)
    display["Behavior Form Items"] = df["behavior_form_items"].astype(int)
    return display


def format_check_sample_agreement_table(df: pd.DataFrame, users: Dict[str, dict]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    display = pd.DataFrame()
    display["Coder"] = df["coder"].map(lambda username: coder_display_label(username, users))
    display["Check Samples Reached"] = df["check_samples_reached"].astype(int)
    display["Hidden Check Coverage"] = df["hidden_check_coverage"].map(format_percent_metric)
    display["Attention Checks Reached"] = df["attention_checks_reached"].astype(int)
    display["Attention Check Accuracy"] = df["attention_check_accuracy"].map(format_percent_metric)
    display["Attention Flag"] = df["attention_flag"].map(
        lambda flagged: "Review (low attention)" if flagged else ""
    )
    display["Primary Gold Accuracy"] = df["primary_gold_accuracy"].map(format_percent_metric)
    display["Components Gold Accuracy"] = df["components_gold_accuracy"].map(format_percent_metric)
    display["Rule Source Gold Accuracy"] = df["rule_source_gold_accuracy"].map(format_percent_metric)
    display["Behavior Form Gold Accuracy"] = df["behavior_form_gold_accuracy"].map(format_percent_metric)
    display["Rule Taxonomy Items"] = df["rule_taxonomy_items"].astype(int)
    return display


def build_qwk_matrix(pairwise_df: pd.DataFrame, coders: List[str], users: Dict[str, dict]) -> pd.DataFrame:
    labels = [coder_display_label(coder, users) for coder in coders]
    matrix = pd.DataFrame("N/A", index=labels, columns=labels)
    for label in labels:
        matrix.loc[label, label] = "-"
    if pairwise_df.empty:
        return matrix
    label_lookup = {coder: coder_display_label(coder, users) for coder in coders}
    for _, row in pairwise_df.iterrows():
        a = label_lookup.get(str(row["coder_a"]), str(row["coder_a"]))
        b = label_lookup.get(str(row["coder_b"]), str(row["coder_b"]))
        value = format_kappa_metric(row["primary_qwk"])
        matrix.loc[a, b] = value
        matrix.loc[b, a] = value
    return matrix


def save_annotation(
    qa_item: dict,
    selected_code_ids: List[str],
    code_confidences: Dict[str, int],
    code_comments: Dict[str, str],
    is_other: bool,
    other_reason: str,
    primary_hierarchy: int,
    component_context: bool,
    component_behavior: bool,
    component_consequence: bool,
    component_rule: bool,
    rule_source: str,
    behavior_form: str,
    confidence: int,
    annotation_confidences: Dict[str, int],
    annotation_comments: Dict[str, str],
    evidence_span: str,
    issue_flags: List[str],
    meaning_unit_note: str,
    coder_display: str,
    coder_username: str,
) -> None:
    with ANNOTATION_FILE_LOCK:
        df = load_annotations()
        qa_id = qa_item["qa_id"]
        coder_username_clean = coder_username.strip().lower()
        secondary_component_score = (
            int(component_context)
            + int(component_behavior)
            + int(component_consequence)
            + int(component_rule)
        )
        code_ids_clean = [c for c in selected_code_ids if c and c != OTHER_CODE]
        primary_legacy = code_ids_clean[0] if code_ids_clean else (OTHER_CODE if is_other else "")
        row = {
            "qa_id": qa_id,
            "subject_id": qa_item["subject_id"],
            "question_line_no": qa_item["question_line_no"],
            "answer_line_no": qa_item["answer_line_no"],
            "selected_code_id": primary_legacy,
            "selected_code_ids": join_code_ids(code_ids_clean),
            "code_confidences": join_code_confidences(code_confidences, code_ids_clean),
            "code_comments": join_code_comments(code_comments, code_ids_clean),
            "is_other": "1" if is_other else "0",
            "other_reason": other_reason.strip(),
            "primary_hierarchy": str(primary_hierarchy),
            "component_context": "1" if component_context else "0",
            "component_behavior": "1" if component_behavior else "0",
            "component_consequence": "1" if component_consequence else "0",
            "component_rule": "1" if component_rule else "0",
            "secondary_component_score": str(secondary_component_score),
            "rule_source": (rule_source or "N/A").strip(),
            "behavior_form": (behavior_form or "N/A").strip(),
            "confidence": str(int(confidence)),
            "annotation_confidences": join_annotation_confidences(annotation_confidences),
            "annotation_comments": join_annotation_comments(annotation_comments),
            "evidence_span": (evidence_span or "").strip(),
            "issue_flags": join_issue_flags(issue_flags),
            "meaning_unit_note": (meaning_unit_note or "").strip(),
            "coder": coder_display.strip(),
            "coder_username": coder_username_clean,
            "updated_at_utc": utc_now_iso_z(),
        }

        if not df.empty:
            same_coder_item = (
                (df["qa_id"].astype(str) == qa_id)
                & (df["coder_username"].astype(str).str.lower() == coder_username_clean)
            )
            df = df[~same_coder_item]
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        df = df.reindex(columns=ANNOTATION_COLUMNS, fill_value="")
        tmp_path = ANNOTATIONS_PATH.with_suffix(".csv.tmp")
        df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
        tmp_path.replace(ANNOTATIONS_PATH)


def audit_annotation_records(qa_items: List[dict]) -> dict:
    df = load_annotations()
    valid_qa_ids = {item["qa_id"] for item in qa_items}
    issues: List[str] = []

    if df.empty:
        return {
            "total": 0,
            "subjects": 0,
            "coders": 0,
            "issues": issues,
        }

    duped_by_coder = df.duplicated(subset=["qa_id", "coder_username"], keep=False)
    if duped_by_coder.any():
        dupes = (
            df.loc[duped_by_coder, ["qa_id", "coder_username"]]
            .astype(str)
            .drop_duplicates()
            .to_dict("records")
        )
        issues.append(f"Duplicate qa_id + coder rows: {dupes}")

    for _, row in df.iterrows():
        qa_id = str(row["qa_id"])
        if qa_id not in valid_qa_ids:
            issues.append(f"Unknown qa_id (not in current Q/A set): {qa_id}")
        score = parse_annotation_int(row.get("secondary_component_score"), 0)
        recomputed = (
            parse_annotation_bool(row.get("component_context"))
            + parse_annotation_bool(row.get("component_behavior"))
            + parse_annotation_bool(row.get("component_consequence"))
            + parse_annotation_bool(row.get("component_rule"))
        )
        if score != recomputed:
            issues.append(f"secondary_component_score mismatch for {qa_id}: saved {score}, expected {recomputed}")
        if not SIMPLE_LABELING_MODE:
            if parse_annotation_bool(row.get("is_other")) and not str(row.get("other_reason", "")).strip():
                issues.append(f"Other checked without reason: {qa_id}")
            if parse_annotation_bool(row.get("is_other")) and str(row.get("selected_code_ids", "")).strip():
                issues.append(f"Other checked while code(s) also selected: {qa_id}")
            if not parse_annotation_bool(row.get("is_other")) and not str(row.get("selected_code_ids", "")).strip():
                issues.append(f"No codes saved and not marked Other: {qa_id}")
            if parse_annotation_int(row.get("primary_hierarchy"), 0) >= 2 and not str(row.get("evidence_span", "")).strip():
                issues.append(f"Primary >=2 without evidence span: {qa_id}")

    return {
        "total": len(df),
        "subjects": df["subject_id"].nunique(),
        "coders": df["coder_username"].nunique() if "coder_username" in df.columns else 0,
        "issues": issues,
    }


@st.cache_data(show_spinner=False)
def load_demographics_all() -> pd.DataFrame:
    if not GLUCOSE_DEMOGRAPHICS_PATH.exists():
        return pd.DataFrame()
    df = pd.read_csv(GLUCOSE_DEMOGRAPHICS_PATH, encoding="utf-8-sig")
    if "subject_id" not in df.columns:
        return pd.DataFrame()
    return df.fillna("")


def get_demographics_for_subject(subject_id: str) -> dict:
    df = load_demographics_all()
    if df.empty:
        return {}
    rows = df[df["subject_id"].astype(str) == subject_id]
    if rows.empty:
        return {}
    return rows.iloc[0].to_dict()


def summarize_subject_cgm_coverage(subject_id: str) -> dict:
    computed = enrich_computed_with_phase(get_cgm_computed_for_subject(subject_id))
    demo = get_demographics_for_subject(subject_id)
    raw = get_cgm_raw_for_subject(subject_id)
    if computed.empty:
        return {
            "subject_id": subject_id,
            "coverage": "No CGM data",
            "phase1_days": 0,
            "phase2_days": 0,
            "recent_days": 0,
            "computed_days": 0,
            "has_demographics": bool(demo),
            "has_raw": not raw.empty,
        }

    phase1 = computed[computed["study_day"] <= 10]
    phase2 = computed[computed["study_day"] > 10]
    recent = get_phase2_last_n_days_df(computed)
    phase1_days = len(phase1)
    phase2_days = len(phase2)
    if phase1_days >= 8 and phase2_days >= 8:
        coverage = "Full Phase 1 + Phase 2"
    elif phase2_days >= 3:
        coverage = "Partial Phase 2"
    elif phase2_days > 0:
        coverage = "Limited Phase 2"
    else:
        coverage = "Phase 1 only"

    return {
        "subject_id": subject_id,
        "coverage": coverage,
        "phase1_days": phase1_days,
        "phase2_days": phase2_days,
        "recent_days": len(recent),
        "computed_days": len(computed),
        "has_demographics": bool(demo),
        "has_raw": not raw.empty,
    }


def build_participant_data_coverage_df(qa_subject_counts: Optional[Dict[str, int]] = None) -> pd.DataFrame:
    computed_all = load_cgm_computed_all()
    if computed_all.empty:
        return pd.DataFrame()

    qa_subject_counts = qa_subject_counts or {}
    rows: List[dict] = []
    for subject_id in sorted(computed_all["subject_id"].astype(str).unique()):
        cov = summarize_subject_cgm_coverage(subject_id)
        qa_items = qa_subject_counts.get(subject_id, 0)
        rows.append(
            {
                "Subject": subject_id,
                "Q/A items": str(qa_items) if qa_items else "CGM-only",
                "Coverage": cov["coverage"],
                "Phase 1 days": cov["phase1_days"],
                "Phase 2 days": cov["phase2_days"],
                "Last-3d window": cov["recent_days"],
                "Computed days": cov["computed_days"],
                "Demographics": "Yes" if cov["has_demographics"] else "No",
                "Raw CGM": "Yes" if cov["has_raw"] else "No",
            }
        )
    return pd.DataFrame(rows)


def render_subject_cgm_coverage_note(subject_id: str) -> None:
    cov = summarize_subject_cgm_coverage(subject_id)
    if cov["coverage"] == "No CGM data":
        st.warning(f"No CGM computed metrics found for **{subject_id}**.")
        return
    if cov["coverage"] in {"Limited Phase 2", "Phase 1 only"}:
        st.warning(
            f"**{subject_id}** has **{cov['coverage'].lower()}** "
            f"(Phase 1: {cov['phase1_days']} days, Phase 2: {cov['phase2_days']} days). "
            "Phase comparisons and last-3d averages use available days only."
        )
    elif cov["coverage"] == "Partial Phase 2":
        st.info(
            f"**{subject_id}** CGM coverage: Phase 1 {cov['phase1_days']} days · "
            f"Phase 2 {cov['phase2_days']} days · last-3d window {cov['recent_days']} day(s)."
        )


def format_demographic_value(field_key: str, value: object) -> str:
    text = str(value).strip() if value is not None else ""
    if not text or text.upper() in {"NA", "NAN", "N/A", "NONE"}:
        return "N/A"
    if field_key in {"bmi", "a1c"}:
        try:
            return f"{float(text):.1f}"
        except ValueError:
            return text
    if field_key in {"fasting_glucose", "cdc_risk_score"}:
        try:
            return f"{float(text):.0f}"
        except ValueError:
            return text
    return text


def is_demographic_missing(value: object) -> bool:
    text = str(value).strip() if value is not None else ""
    return not text or text.upper() in {"NA", "NAN", "N/A", "NONE"}


def format_primary_demographic_metric(field_key: str, demo: dict) -> str:
    if field_key == "a1c":
        a1c = format_demographic_value("a1c", demo.get("a1c", ""))
        cat = format_demographic_value("a1c_cat", demo.get("a1c_cat", ""))
        if a1c == "N/A":
            return "N/A"
        return f"{a1c}%" if cat == "N/A" else f"{a1c}% ({cat})"
    if field_key == "bmi":
        bmi = format_demographic_value("bmi", demo.get("bmi", ""))
        cat = format_demographic_value("bmi_cat", demo.get("bmi_cat", ""))
        if bmi == "N/A":
            return "N/A"
        return bmi if cat == "N/A" else f"{bmi} ({cat})"
    if field_key == "cdc_risk_score":
        score = format_demographic_value("cdc_risk_score", demo.get("cdc_risk_score", ""))
        cat = format_demographic_value("cdc_risk_score_cat", demo.get("cdc_risk_score_cat", ""))
        if score == "N/A":
            return "N/A"
        return score if cat == "N/A" else f"{score} ({cat})"
    return format_demographic_value(field_key, demo.get(field_key, ""))


def primary_demographic_help(field_key: str) -> str:
    help_map = {
        "a1c": "Baseline A1C and clinical category. Core pre-diabetes indicator for this study.",
        "bmi": "Baseline BMI with obesity class.",
        "cdc_risk_score": "CDC pre-diabetes risk score with category.",
        "sex_atbirth": "Participant sex at birth.",
        "race": "Self-reported race.",
    }
    return help_map.get(field_key, "")


def render_demographics_panel(subject_id: str, demo: dict, *, compact: bool = False) -> None:
    st.markdown('<div class="section-card card-demographics">', unsafe_allow_html=True)
    st.markdown(f"**Demographics — {subject_id}**")
    if not compact:
        st.caption(
            "Baseline clinical and demographic fields most relevant to pre-diabetes and alert-related coding. "
            "Expand below for additional details."
        )

    if compact:
        for row_start in range(0, len(DEMOGRAPHICS_PRIMARY_FIELDS), 2):
            cols = st.columns(2)
            for col_idx, col in enumerate(cols):
                field_idx = row_start + col_idx
                if field_idx >= len(DEMOGRAPHICS_PRIMARY_FIELDS):
                    break
                field_key, label = DEMOGRAPHICS_PRIMARY_FIELDS[field_idx]
                with col:
                    st.metric(
                        label=label,
                        value=format_primary_demographic_metric(field_key, demo),
                        help=primary_demographic_help(field_key),
                    )
    else:
        cols = st.columns(len(DEMOGRAPHICS_PRIMARY_FIELDS))
        for col, (field_key, label) in zip(cols, DEMOGRAPHICS_PRIMARY_FIELDS):
            with col:
                st.metric(
                    label=label,
                    value=format_primary_demographic_metric(field_key, demo),
                    help=primary_demographic_help(field_key),
                )

    with st.expander("Additional demographics"):
        expanded_rows = []
        for field_key, label in DEMOGRAPHICS_EXPANDED_ONLY_FIELDS:
            value = format_demographic_value(field_key, demo.get(field_key, ""))
            note = ""
            if field_key == "ethnicity_screen":
                note = "Same value for all G2 participants"
            elif field_key == "fasting_glucose" and is_demographic_missing(demo.get(field_key, "")):
                note = "Not recorded for this participant"
            elif field_key == "cgm_date" and is_demographic_missing(demo.get(field_key, "")):
                note = "Not recorded for this participant"
            expanded_rows.append({"Field": label, "Value": value, "Note": note})

        st.dataframe(
            pd.DataFrame(expanded_rows),
            width="stretch",
            hide_index=True,
        )

    with st.expander("View full raw record"):
        display = {
            label: format_demographic_value(field_key, demo.get(field_key, ""))
            for field_key, label in DEMOGRAPHICS_FIELDS
        }
        st.dataframe(
            pd.DataFrame([display]),
            width="stretch",
            hide_index=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def load_cgm_raw_all() -> pd.DataFrame:
    if not GLUCOSE_RAW_PATH.exists():
        return pd.DataFrame()
    df = pd.read_csv(GLUCOSE_RAW_PATH, encoding="utf-8-sig")
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", format="mixed")
    if GLUCOSE_VALUE_COL in df.columns:
        df[GLUCOSE_VALUE_COL] = pd.to_numeric(df[GLUCOSE_VALUE_COL], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_cgm_computed_all() -> pd.DataFrame:
    if not GLUCOSE_COMPUTED_PATH.exists():
        return pd.DataFrame()
    df = pd.read_csv(GLUCOSE_COMPUTED_PATH, encoding="utf-8-sig")
    for col in ("start_date", "end_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", format="mixed")
    return df


def get_cgm_raw_for_subject(subject_id: str) -> pd.DataFrame:
    df = load_cgm_raw_all()
    if df.empty or "subject_id" not in df.columns:
        return pd.DataFrame()
    out = df[df["subject_id"] == subject_id].copy()
    if out.empty:
        return out
    return out.sort_values("timestamp").reset_index(drop=True)


def get_cgm_computed_for_subject(subject_id: str) -> pd.DataFrame:
    df = load_cgm_computed_all()
    if df.empty or "subject_id" not in df.columns:
        return pd.DataFrame()
    out = df[df["subject_id"] == subject_id].copy()
    if out.empty:
        return out
    return out.sort_values("start_date").reset_index(drop=True)


def enrich_computed_with_phase(computed: pd.DataFrame) -> pd.DataFrame:
    if computed.empty:
        return computed
    out = computed.copy()
    anchor = out["start_date"].min().normalize()
    out["study_day"] = ((out["start_date"].dt.normalize() - anchor).dt.days + 1).clip(lower=1)
    out["phase"] = out["study_day"].apply(
        lambda day: CGM_PHASE_1 if day <= 10 else CGM_PHASE_2
    )
    return out


def filter_computed_by_phase(computed: pd.DataFrame, phase_filter: str) -> pd.DataFrame:
    if computed.empty or phase_filter == CGM_PHASE_ALL:
        return computed
    return computed[computed["phase"] == phase_filter].copy()


def available_cgm_metric_keys(computed: Optional[pd.DataFrame] = None) -> List[str]:
    if computed is None or computed.empty:
        return list(CGM_COMPUTED_METRICS.keys())
    return [key for key in CGM_COMPUTED_METRICS if key in computed.columns]


def cgm_metric_option_label(metric_key: str) -> str:
    meta = CGM_COMPUTED_METRICS[metric_key]
    return f"{meta['group']} · {meta['label']}"


def cgm_metric_labels_from_keys(metric_keys: List[str]) -> List[str]:
    return [cgm_metric_option_label(key) for key in metric_keys if key in CGM_COMPUTED_METRICS]


def cgm_metric_keys_from_labels(option_labels: List[str]) -> List[str]:
    mapping = {cgm_metric_option_label(key): key for key in CGM_COMPUTED_METRICS}
    return [mapping[label] for label in option_labels if label in mapping]


def render_cgm_metric_picker(
    key_prefix: str,
    *,
    default_keys: List[str],
    available_keys: Optional[List[str]] = None,
    label: str = "Metrics to display",
    help_text: str = "",
    show_presets: bool = True,
) -> List[str]:
    keys_pool = available_keys or list(CGM_COMPUTED_METRICS.keys())
    all_option_labels = cgm_metric_labels_from_keys(keys_pool)
    default_labels = cgm_metric_labels_from_keys([key for key in default_keys if key in keys_pool])
    multiselect_key = f"{key_prefix}_metrics"

    if multiselect_key not in st.session_state:
        st.session_state[multiselect_key] = default_labels

    if show_presets:
        preset_col, apply_col = st.columns([3, 1])
        with preset_col:
            preset = st.selectbox(
                "Quick preset",
                options=list(CGM_METRIC_PRESETS.keys()),
                key=f"{key_prefix}_preset",
                help="Choose a preset, then click Apply preset to fill the metric list below.",
            )
        with apply_col:
            st.write("")
            st.write("")
            if st.button("Apply preset", key=f"{key_prefix}_apply", width="stretch"):
                preset_keys = [key for key in CGM_METRIC_PRESETS[preset] if key in keys_pool]
                st.session_state[multiselect_key] = cgm_metric_labels_from_keys(preset_keys)

    selected_labels = st.multiselect(
        label,
        options=all_option_labels,
        key=multiselect_key,
        help=help_text or "Pick any combination. Labels include the metric category.",
    )
    return cgm_metric_keys_from_labels(selected_labels)


def render_cgm_metric_single_picker(
    key_prefix: str,
    *,
    default_key: str,
    available_keys: Optional[List[str]] = None,
    label: str = "Metric",
    help_text: str = "",
) -> str:
    keys_pool = available_keys or list(CGM_COMPUTED_METRICS.keys())
    option_labels = cgm_metric_labels_from_keys(keys_pool)
    default_label = cgm_metric_option_label(default_key)
    default_index = option_labels.index(default_label) if default_label in option_labels else 0
    selected_label = st.selectbox(
        label,
        options=option_labels,
        index=default_index,
        key=f"{key_prefix}_single",
        help=help_text,
    )
    return cgm_metric_keys_from_labels([selected_label])[0]


def answer_suggests_cgm_context(text: str) -> bool:
    if not text:
        return False
    for patterns in BEHAVIOR_HIGHLIGHT_PATTERNS.values():
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return True
    return False


def narrative_suggests_improvement(text: str) -> bool:
    if not text:
        return False
    for pattern in NARRATIVE_IMPROVEMENT_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True
    return False


def get_code_specific_cgm_hints(
    selected_code_ids: List[str],
    code_index: Dict[str, Dict[str, str]],
) -> List[str]:
    hints: List[str] = []
    seen: set = set()
    for code_id in selected_code_ids:
        meta = code_index.get(code_id, {})
        code_name = meta.get("name", code_id)
        for hint_key, hint_text in CGM_CODE_HINTS.items():
            if hint_key.lower() in code_name.lower() or hint_key.lower() in code_id.lower():
                line = f"**{code_name}:** {hint_text}"
                if line not in seen:
                    seen.add(line)
                    hints.append(line)
    return hints


def compute_cgm_mismatch_message(qa_text: str, computed: pd.DataFrame) -> Optional[str]:
    if computed.empty or not narrative_suggests_improvement(qa_text):
        return None
    phase1 = computed[computed["study_day"] <= 10]
    phase2 = computed[computed["study_day"] > 10]
    if phase1.empty or phase2.empty:
        return None

    worsened: List[str] = []
    for metric_key in ("above_140", "in_range_63_140", "AUC"):
        if metric_key not in computed.columns:
            continue
        p1 = phase_weighted_mean(phase1, metric_key)
        p2 = phase_weighted_mean(phase2, metric_key)
        if p1 is None or p2 is None:
            continue
        delta = p2 - p1
        _, verdict_kind = format_phase_period_verdict(metric_key, delta)
        if verdict_kind == "worsened":
            worsened.append(CGM_COMPUTED_METRICS[metric_key]["label"])

    if len(worsened) < 2:
        return None
    return (
        "Participant language suggests improvement, but Phase 2 vs Phase 1 worsened for: "
        f"{', '.join(worsened)}. CGM is **conflicting evidence** — note the mismatch and consider lower confidence. "
        "Do not automatically downgrade Primary level."
    )


def is_adjudication_candidate(
    confidence: int,
    *,
    mismatch_message: Optional[str] = None,
) -> tuple[bool, str]:
    reasons: List[str] = []
    if confidence <= 2:
        reasons.append(f"confidence {confidence}")
    if mismatch_message and confidence <= 3:
        reasons.append("narrative–CGM mismatch with moderate-or-lower confidence")
    if not reasons:
        return False, ""
    return True, "; ".join(reasons)


def build_adjudication_candidates(
    subject_id: str,
    qa_items: List[dict],
    annotated_map: Dict[str, dict],
) -> pd.DataFrame:
    computed = (
        pd.DataFrame()
        if SIMPLE_LABELING_MODE
        else enrich_computed_with_phase(get_cgm_computed_for_subject(subject_id))
    )
    rows: List[dict] = []
    for item in qa_items:
        if item["subject_id"] != subject_id:
            continue
        qa_id = item["qa_id"]
        ann = annotated_map.get(qa_id)
        if not ann:
            continue
        qa_text = " ".join(
            [
                str(item.get("question_en") or ""),
                str(item.get("question_es") or ""),
                str(item.get("answer_en") or ""),
                str(item.get("answer_es") or ""),
            ]
        )
        mismatch = compute_cgm_mismatch_message(qa_text, computed) if not computed.empty else None
        confidence = parse_annotation_int(ann.get("confidence"), 3)
        flagged, reason = is_adjudication_candidate(confidence, mismatch_message=mismatch)
        if not flagged:
            continue
        row = {
            "Item ID": qa_id,
            "Question line": item.get("question_line_no"),
            "Confidence": confidence,
            "Primary": ann.get("primary_hierarchy", ""),
            "Reason": reason,
        }
        if not SIMPLE_LABELING_MODE:
            row["Mismatch"] = "Yes" if mismatch else "No"
        rows.append(row)
    return pd.DataFrame(rows)


def is_cgm_relevant_for_coding(
    *,
    selected_code_ids: List[str],
    code_index: Dict[str, Dict[str, str]],
    primary_hierarchy: int,
    component_context: bool,
    component_behavior: bool,
    component_consequence: bool,
    component_rule: bool,
    qa_text: str,
    always_show: bool = False,
) -> tuple[bool, str]:
    if always_show:
        return True, "sidebar: always show CGM summary"

    reasons: List[str] = []
    keyword_hit = answer_suggests_cgm_context(qa_text)
    strong_code_hit = False

    for code_id in selected_code_ids:
        group = code_index.get(code_id, {}).get("group", "")
        if group in CGM_CODING_STRONG_CODE_GROUPS:
            strong_code_hit = True
            reasons.append(f"code group: {group}")
        elif group in CGM_CODING_KEYWORD_ONLY_CODE_GROUPS and keyword_hit:
            reasons.append(f"code group (with CGM keywords): {group}")

    if keyword_hit:
        reasons.append("Q/A mentions diet, exercise, change, or alerts")

    if primary_hierarchy >= 3:
        reasons.append(f"Primary level {primary_hierarchy}")
    elif primary_hierarchy == 2 and (
        keyword_hit
        or strong_code_hit
        or component_behavior
        or component_consequence
        or component_rule
    ):
        reasons.append(f"Primary level {primary_hierarchy}")

    component_parts = []
    if component_context:
        component_parts.append("Context")
    if component_behavior:
        component_parts.append("Behavior")
    if component_consequence:
        component_parts.append("Consequence")
    if component_rule:
        component_parts.append("Rule")
    if component_parts and (keyword_hit or strong_code_hit or primary_hierarchy >= 2):
        reasons.append(f"components: {', '.join(component_parts)}")

    if not reasons:
        return False, ""

    has_strong_signal = (
        keyword_hit
        or strong_code_hit
        or component_behavior
        or component_consequence
        or component_rule
        or primary_hierarchy >= 2
    )
    if primary_hierarchy <= 1 and not has_strong_signal:
        return False, ""

    return True, "; ".join(dict.fromkeys(reasons))


def should_show_early_cgm_summary(qa_text: str, *, always_show: bool) -> tuple[bool, str]:
    if always_show:
        return True, "sidebar: always show CGM summary"
    if answer_suggests_cgm_context(qa_text):
        return True, "Q/A mentions diet, exercise, change, or alerts"
    return False, ""


def format_demographics_coding_oneliner(subject_id: str) -> str:
    demo = get_demographics_for_subject(subject_id)
    if not demo:
        return ""
    parts = [
        f"A1C {format_primary_demographic_metric('a1c', demo)}",
        f"BMI {format_primary_demographic_metric('bmi', demo)}",
        f"CDC Risk {format_primary_demographic_metric('cdc_risk_score', demo)}",
    ]
    return " · ".join(parts)


def cgm_verdict_cell_style(verdict_kind: str, theme: str = "Light") -> str:
    palettes = {
        "Dark": {
            "improved": ("rgba(52, 211, 153, 0.22)", "#6ee7b7"),
            "worsened": ("rgba(248, 113, 113, 0.22)", "#fca5a5"),
            "unchanged": ("rgba(148, 163, 184, 0.16)", "#cbd5e1"),
            "na": ("transparent", "#94a3b8"),
        },
        "Light": {
            "improved": ("rgba(16, 185, 129, 0.20)", "#065f46"),
            "worsened": ("rgba(239, 68, 68, 0.18)", "#991b1b"),
            "unchanged": ("rgba(100, 116, 139, 0.14)", "#475569"),
            "na": ("transparent", "#64748b"),
        },
    }
    palette = palettes.get(theme, palettes["Light"])
    bg, color = palette.get(verdict_kind, palette["na"])
    return f"background-color: {bg}; color: {color}; font-weight: 600;"


def get_phase2_last_n_days_df(computed: pd.DataFrame, n: int = PHASE2_RECENT_DAYS) -> pd.DataFrame:
    phase2 = computed[computed["study_day"] > 10].copy()
    if phase2.empty:
        return phase2
    return phase2.sort_values("study_day").tail(n)


def describe_phase2_recent_window(computed: pd.DataFrame, n: int = PHASE2_RECENT_DAYS) -> str:
    recent = get_phase2_last_n_days_df(computed, n=n)
    if recent.empty:
        return "no Phase 2 days available"
    days = recent["study_day"].astype(int).tolist()
    if len(days) == 1:
        return f"Study Day {days[0]} (1 day)"
    return f"Study Days {days[0]}–{days[-1]} ({len(days)} days)"


def fmt_cgm_metric_value(metric_key: str, value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    meta = CGM_COMPUTED_METRICS[metric_key]
    unit = meta["unit"]
    text = f"{value:{meta['fmt']}}"
    return f"{text}{(' ' + unit) if unit else ''}"


def fmt_phase1_comparison(
    metric_key: str,
    baseline: Optional[float],
    comparison: Optional[float],
) -> tuple[str, str]:
    if baseline is None or comparison is None:
        return "N/A", "na"
    delta = comparison - baseline
    verdict_text, verdict_kind = format_phase_period_verdict(metric_key, delta)
    return f"{format_phase_delta(metric_key, delta)} ({verdict_text})", verdict_kind


def build_cgm_coding_summary_table(
    computed: pd.DataFrame,
    metric_keys: Optional[List[str]] = None,
) -> pd.DataFrame:
    phase1 = computed[computed["study_day"] <= 10]
    phase2 = computed[computed["study_day"] > 10]
    phase2_recent = get_phase2_last_n_days_df(computed, n=PHASE2_RECENT_DAYS)
    keys = metric_keys or [
        key for key in CGM_CODING_SUMMARY_DEFAULT_METRICS if key in computed.columns
    ]
    rows = []
    for metric_key in keys:
        if metric_key not in computed.columns:
            continue
        meta = CGM_COMPUTED_METRICS[metric_key]
        full_val = phase_weighted_mean(computed, metric_key)
        p1_val = phase_weighted_mean(phase1, metric_key) if not phase1.empty else None
        p2_val = phase_weighted_mean(phase2, metric_key) if not phase2.empty else None
        p2_recent_val = (
            phase_weighted_mean(phase2_recent, metric_key) if not phase2_recent.empty else None
        )
        if full_val is None:
            continue

        phase_change_all, verdict_all = fmt_phase1_comparison(metric_key, p1_val, p2_val)
        phase_change_recent, verdict_recent = fmt_phase1_comparison(
            metric_key, p1_val, p2_recent_val
        )

        rows.append(
            {
                "Metric": meta["label"],
                "Category": meta["group"],
                "Healthier direction": metric_health_direction_hint(metric_key),
                "Full wear avg": fmt_cgm_metric_value(metric_key, full_val),
                "Phase 1 avg (baseline)": fmt_cgm_metric_value(metric_key, p1_val),
                "Phase 2 avg (all days)": fmt_cgm_metric_value(metric_key, p2_val),
                "Phase 1 → Phase 2 (all)": phase_change_all,
                "Phase 2 avg (last 3d)": fmt_cgm_metric_value(metric_key, p2_recent_val),
                "Phase 1 → Phase 2 (last 3d)": phase_change_recent,
                "_verdict_kind": verdict_all,
                "_verdict_kind_last3": verdict_recent,
            }
        )
    return pd.DataFrame(rows)


def style_cgm_coding_summary_table(summary_table: pd.DataFrame, theme: str = "Light"):
    display_df = summary_table.drop(
        columns=["_verdict_kind", "_verdict_kind_last3"],
        errors="ignore",
    )
    verdicts_all = summary_table["_verdict_kind"].tolist()
    verdicts_last3 = summary_table["_verdict_kind_last3"].tolist()

    def style_row(row: pd.Series):
        idx = row.name
        styles = [""] * len(row)
        if "Phase 1 → Phase 2 (all)" in row.index:
            kind = verdicts_all[idx] if idx < len(verdicts_all) else "na"
            styles[row.index.get_loc("Phase 1 → Phase 2 (all)")] = cgm_verdict_cell_style(
                kind, theme
            )
        if "Phase 1 → Phase 2 (last 3d)" in row.index:
            kind = verdicts_last3[idx] if idx < len(verdicts_last3) else "na"
            styles[row.index.get_loc("Phase 1 → Phase 2 (last 3d)")] = cgm_verdict_cell_style(
                kind, theme
            )
        return styles

    return display_df.style.apply(style_row, axis=1)


def get_cgm_coding_summary_metric_keys(
    subject_id: str,
    computed: pd.DataFrame,
    *,
    interactive: bool,
) -> List[str]:
    available_keys = available_cgm_metric_keys(computed)
    default_keys = [key for key in CGM_CODING_SUMMARY_DEFAULT_METRICS if key in available_keys]
    multiselect_key = f"cgm_coding_summary_{subject_id}_metrics"

    if interactive:
        return render_cgm_metric_picker(
            f"cgm_coding_summary_{subject_id}",
            default_keys=default_keys,
            available_keys=available_keys,
            label="Summary metrics for coding",
            help_text=(
                "Default = 4 core metrics for quick coding. All 12 computed metrics are available — "
                "use presets or pick individually (e.g., Variability for exercise-related codes)."
            ),
        )

    selected_labels = st.session_state.get(multiselect_key, cgm_metric_labels_from_keys(default_keys))
    if not selected_labels:
        return default_keys
    return cgm_metric_keys_from_labels(selected_labels)


def render_cgm_coding_summary_legend() -> None:
    st.markdown(
        """
        <div class="cgm-summary-legend">
          <span class="cgm-legend-item cgm-legend-improved">Improved</span>
          <span class="cgm-legend-item cgm-legend-worsened">Worsened</span>
          <span class="cgm-legend-item cgm-legend-unchanged">Similar</span>
          <span class="cgm-legend-note">Both comparisons use Phase 1 all-days avg as baseline ·
          <b>last 3d</b> = final Phase 2 days · tiny deltas are treated as similar</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_cgm_coding_context_summary(
    subject_id: str,
    *,
    reason: str,
    qa_text: str = "",
    selected_code_ids: Optional[List[str]] = None,
    code_index: Optional[Dict[str, Dict[str, str]]] = None,
    confidence: Optional[int] = None,
    show_table: bool = True,
    show_extras: bool = True,
    extras_only: bool = False,
    theme: str = "Light",
) -> None:
    computed = enrich_computed_with_phase(get_cgm_computed_for_subject(subject_id))
    if computed.empty:
        st.info("CGM context is relevant for this item, but no computed metrics are available for this participant.")
        return

    wear_start = computed["start_date"].min().strftime("%Y-%m-%d")
    wear_end = computed["end_date"].max().strftime("%Y-%m-%d")
    phase1_days = int((computed["study_day"] <= 10).sum())
    phase2_days = int((computed["study_day"] > 10).sum())
    demo_line = format_demographics_coding_oneliner(subject_id)
    mismatch_message = compute_cgm_mismatch_message(qa_text, computed) if qa_text else None

    st.markdown('<div class="section-card card-cgm">', unsafe_allow_html=True)
    if extras_only:
        st.markdown("**CGM Coding Notes**")
        st.caption(f"Additional context for this item ({reason}).")
    else:
        st.markdown("**CGM Summary for Coding**")
        st.caption(
            f"Shown because this item is CGM-relevant ({reason}). "
            "Default table shows **4 core metrics**; you can add any of the **12 computed metrics** below."
        )
        st.info(CGM_TIMELINE_REMINDER)
        if demo_line:
            st.caption(f"**Baseline context:** {demo_line}")
        st.caption(
            f"Wear period: {wear_start} → {wear_end} · "
            f"Phase 1 days: {phase1_days} · Phase 2 days: {phase2_days} · "
            f"**Last 3d window:** {describe_phase2_recent_window(computed)}"
        )
        st.caption(
            "Compare **Phase 2 (all days)** and **Phase 2 (last 3 days)** each against the same "
            "**Phase 1 baseline**. Recent days may show improvement even when the full Phase 2 average has not changed yet."
        )

    selected_summary_metrics: List[str] = []
    if show_table:
        selected_summary_metrics = get_cgm_coding_summary_metric_keys(
            subject_id,
            computed,
            interactive=not extras_only,
        )
    summary_table = (
        build_cgm_coding_summary_table(computed, selected_summary_metrics)
        if show_table and selected_summary_metrics
        else pd.DataFrame()
    )

    if show_table and not selected_summary_metrics:
        st.info("Select at least one metric for the coding summary table.")
    elif show_table and summary_table.empty:
        st.info("CGM context is relevant for this item, but summary metrics are unavailable.")
    elif show_table and not summary_table.empty:
        render_subject_cgm_coverage_note(subject_id)
        render_cgm_coding_summary_legend()
        styled_table = style_cgm_coding_summary_table(summary_table, theme=theme)
        st.dataframe(styled_table, width="stretch", hide_index=True)

    if show_extras:
        if selected_code_ids and code_index:
            code_hints = get_code_specific_cgm_hints(selected_code_ids, code_index)
            if code_hints:
                st.markdown("**Code-specific CGM hints**")
                for hint in code_hints:
                    st.markdown(f"- {hint}")

        if mismatch_message:
            st.warning(mismatch_message)

        if confidence is not None:
            flagged, adj_reason = is_adjudication_candidate(
                confidence,
                mismatch_message=mismatch_message,
            )
            if flagged:
                st.warning(
                    f"**Adjudication candidate:** {adj_reason}. "
                    "Add a coder note explaining your judgment."
                )

    if not extras_only:
        st.caption(
            "Tip: If full Phase 2 is flat but **last 3d** is green, the participant may be starting to change behavior after alerts. "
            "Daily charts and all 12 metrics are in **Participant Context** below."
        )
    st.markdown("</div>", unsafe_allow_html=True)


def phase_weighted_mean(df: pd.DataFrame, column: str) -> Optional[float]:
    if df.empty or column not in df.columns:
        return None
    values = df[column].astype(float)
    ndays = df["ndays"].fillna(1).astype(float) if "ndays" in df.columns else pd.Series([1.0] * len(df))
    total = float(ndays.sum())
    if total <= 0:
        return float(values.mean())
    return float((values * ndays).sum() / total)


def build_phase_comparison_table(computed: pd.DataFrame) -> pd.DataFrame:
    phase1 = computed[computed["study_day"] <= 10].copy()
    phase2 = computed[computed["study_day"] > 10].copy()
    if phase1.empty or phase2.empty:
        return pd.DataFrame()

    rows = []
    for metric_key, meta in CGM_COMPUTED_METRICS.items():
        if metric_key not in computed.columns:
            continue
        baseline = phase_weighted_mean(phase1, metric_key)
        if baseline is None:
            continue
        phase2_rows = phase2.sort_values("start_date").copy()
        phase2_rows["baseline_phase1"] = baseline
        phase2_rows["delta_vs_phase1"] = phase2_rows[metric_key].astype(float) - baseline
        phase2_rows["metric_key"] = metric_key
        phase2_rows["metric_label"] = meta["label"]
        rows.append(
            phase2_rows[
                [
                    "start_date",
                    "study_day",
                    "metric_key",
                    "metric_label",
                    metric_key,
                    "baseline_phase1",
                    "delta_vs_phase1",
                ]
            ].rename(
                columns={
                    metric_key: "phase2_value",
                    "baseline_phase1": "phase1_baseline",
                }
            )
        )
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def cgm_meaningful_delta(metric_key: str) -> float:
    return CGM_MEANINGFUL_DELTA.get(metric_key, 0.0)


def phase_delta_is_meaningful(metric_key: str, delta: float) -> bool:
    return abs(delta) >= cgm_meaningful_delta(metric_key)


def delta_is_improvement(metric_key: str, delta: float) -> bool:
    meta = CGM_COMPUTED_METRICS[metric_key]
    if meta["lower_is_better"]:
        return delta < 0
    return delta > 0


def format_phase_delta(metric_key: str, delta: float) -> str:
    meta = CGM_COMPUTED_METRICS[metric_key]
    unit = meta["unit"]
    formatted = format(delta, meta["fmt"])
    suffix = f" {unit}" if unit else ""
    sign = "+" if delta > 0 else ""
    return f"{sign}{formatted}{suffix}"


def metric_health_direction_hint(metric_key: str) -> str:
    meta = CGM_COMPUTED_METRICS[metric_key]
    threshold = cgm_meaningful_delta(metric_key)
    if meta["lower_is_better"]:
        return f"↓ Lower is healthier (±{threshold:g}{meta['unit']} treated as similar)"
    return f"↑ Higher is healthier (±{threshold:g}{meta['unit']} treated as similar)"


def format_phase_period_verdict(metric_key: str, delta: float) -> tuple[str, str]:
    if not phase_delta_is_meaningful(metric_key, delta):
        return "Similar", "unchanged"
    improved = delta_is_improvement(metric_key, delta)
    change_arrow = "↓" if delta < 0 else "↑"
    if improved:
        return f"Improved {change_arrow}", "improved"
    return f"Worsened {change_arrow}", "worsened"


def _phase_verdict_color(verdict_kind: str) -> str:
    return {
        "improved": "#34d399",
        "worsened": "#f87171",
        "unchanged": "#94a3b8",
    }[verdict_kind]


def build_phase_delta_figure(
    phase2_daily: pd.DataFrame,
    metric_key: str,
    theme: str,
    *,
    compact: bool = False,
) -> go.Figure:
    fig = go.Figure()
    meta = CGM_COMPUTED_METRICS[metric_key]
    plot_df = phase2_daily.sort_values("start_date").copy()
    if plot_df.empty:
        return fig

    baseline = float(plot_df["phase1_baseline"].iloc[0])
    deltas = plot_df["delta_vs_phase1"].astype(float)
    colors = [
        "rgba(52, 211, 153, 0.85)" if delta_is_improvement(metric_key, d) else "rgba(248, 113, 113, 0.85)"
        for d in deltas
    ]
    unit_suffix = f" {meta['unit']}" if meta["unit"] else ""

    fig.add_trace(
        go.Bar(
            x=plot_df["start_date"],
            y=deltas,
            name="Daily delta",
            marker={"color": colors},
            hovertemplate=(
                "Study day %{customdata[0]}<br>"
                f"Phase 2: %{{customdata[1]:{meta['fmt']}}}{unit_suffix}<br>"
                f"Phase 1 baseline: {baseline:{meta['fmt']}}{unit_suffix}<br>"
                f"Delta: %{{y:{meta['fmt']}}}{unit_suffix}<extra></extra>"
            ),
            customdata=list(
                zip(
                    plot_df["study_day"].astype(int),
                    plot_df["phase2_value"].astype(float),
                )
            ),
        )
    )
    fig.add_hline(y=0, line={"color": "rgba(148, 163, 184, 0.9)", "width": 1})

    _finalize_plotly_layout(
        fig,
        theme,
        title=f"Phase 2 Each Day vs Phase 1 Baseline — {meta['label']}",
        x_title="Phase 2 date (alerts on)",
        y_title=f"Daily value − Phase 1 baseline ({unit_suffix.strip() or 'value'})",
        height=340 if compact else 400,
        legend_count=0,
        show_legend=False,
        compact=compact,
    )
    return fig


def build_phase2_daily_values_figure(
    phase2_daily: pd.DataFrame,
    metric_key: str,
    theme: str,
    *,
    compact: bool = False,
) -> go.Figure:
    fig = go.Figure()
    meta = CGM_COMPUTED_METRICS[metric_key]
    plot_df = phase2_daily.sort_values("start_date").copy()
    if plot_df.empty:
        return fig

    baseline = float(plot_df["phase1_baseline"].iloc[0])
    unit_suffix = f" {meta['unit']}" if meta["unit"] else ""

    fig.add_trace(
        go.Scatter(
            x=plot_df["start_date"],
            y=plot_df["phase2_value"].astype(float),
            mode="lines+markers",
            name=f"Phase 2 daily {meta['label']}",
            line={"color": "#34d399", "width": 2},
            marker={"size": 7},
            hovertemplate=(
                "Study day %{customdata}<br>"
                f"Phase 2: %{{y:{meta['fmt']}}}{unit_suffix}<extra></extra>"
            ),
            customdata=plot_df["study_day"].astype(int),
        )
    )
    fig.add_hline(
        y=baseline,
        line={"color": "rgba(251, 191, 36, 0.9)", "width": 2, "dash": "dash"},
        annotation_text=f"Phase 1 baseline ({baseline:{meta['fmt']}}{unit_suffix})",
        annotation_position="right",
    )

    _finalize_plotly_layout(
        fig,
        theme,
        title=f"Phase 2 Daily Values vs Phase 1 Baseline — {meta['label']}",
        x_title="Phase 2 date (alerts on)",
        y_title=f"{meta['label']} ({unit_suffix.strip()})",
        height=320 if compact else 380,
        legend_count=1,
        compact=compact,
    )
    return fig


def build_phase_average_comparison_figure(
    computed: pd.DataFrame,
    theme: str,
    *,
    metric_keys: Optional[List[str]] = None,
    compact: bool = False,
) -> go.Figure:
    phase1 = computed[computed["study_day"] <= 10]
    phase2 = computed[computed["study_day"] > 10]
    fig = go.Figure()
    if phase1.empty or phase2.empty:
        return fig

    labels = []
    phase1_vals = []
    phase2_vals = []
    keys = metric_keys or available_cgm_metric_keys(computed)
    for metric_key in keys:
        if metric_key not in computed.columns:
            continue
        meta = CGM_COMPUTED_METRICS[metric_key]
        p1 = phase_weighted_mean(phase1, metric_key)
        p2 = phase_weighted_mean(phase2, metric_key)
        if p1 is None or p2 is None:
            continue
        labels.append(meta["label"])
        phase1_vals.append(p1)
        phase2_vals.append(p2)

    if not labels:
        return fig

    fig.add_trace(
        go.Bar(name="Phase 1 (no alerts)", x=labels, y=phase1_vals, marker={"color": "#94a3b8"})
    )
    fig.add_trace(
        go.Bar(name="Phase 2 (alerts on)", x=labels, y=phase2_vals, marker={"color": "#34d399"})
    )
    fig.update_layout(barmode="group")

    chart_height = 320 if compact else 380
    if len(labels) > 6:
        chart_height += min(120, 12 * (len(labels) - 6))

    _finalize_plotly_layout(
        fig,
        theme,
        title="Phase 1 vs Phase 2 Period Averages (summary)",
        x_title="Metric",
        y_title="Value",
        height=chart_height,
        legend_count=2,
        compact=compact,
    )
    return fig


def render_phase_summary_cards(
    phase1: pd.DataFrame,
    phase2: pd.DataFrame,
    computed: pd.DataFrame,
    summary_keys: List[str],
) -> None:
    keys = [key for key in summary_keys if key in computed.columns]
    if not keys:
        st.info("Select at least one metric for the summary.")
        return

    for row_start in range(0, len(keys), 4):
        row_keys = keys[row_start : row_start + 4]
        summary_cols = st.columns(len(row_keys))
        for col, metric_key in zip(summary_cols, row_keys):
            metric_meta = CGM_COMPUTED_METRICS[metric_key]
            p1 = phase_weighted_mean(phase1, metric_key)
            p2 = phase_weighted_mean(phase2, metric_key)
            if p1 is None or p2 is None:
                continue
            delta = p2 - p1
            metric_unit = metric_meta["unit"]
            p1_text = f"{p1:{metric_meta['fmt']}}{(' ' + metric_unit) if metric_unit else ''}"
            p2_text = f"{p2:{metric_meta['fmt']}}{(' ' + metric_unit) if metric_unit else ''}"
            verdict_text, verdict_kind = format_phase_period_verdict(metric_key, delta)
            verdict_color = _phase_verdict_color(verdict_kind)
            with col:
                st.markdown(f"**{metric_meta['label']}**")
                st.caption(f"{metric_meta['group']} · {metric_health_direction_hint(metric_key)}")
                st.markdown(
                    f'<p style="font-size:1.15rem;font-weight:600;color:{verdict_color};margin:0.25rem 0;">'
                    f"{verdict_text}</p>",
                    unsafe_allow_html=True,
                )
                st.caption(f"Phase 1 avg: {p1_text}")
                st.caption(f"Phase 2 avg: {p2_text}")
                st.caption(f"Change: {format_phase_delta(metric_key, delta)}")


def render_phase_comparison_panel(
    computed: pd.DataFrame,
    subject_id: str,
    theme: str,
    *,
    compact: bool = False,
) -> None:
    phase1 = computed[computed["study_day"] <= 10]
    phase2 = computed[computed["study_day"] > 10]
    if phase1.empty or phase2.empty:
        st.warning(
            "Need both Phase 1 (Days 1–10) and Phase 2 (Days 11–20) data to compare alert vs no-alert periods."
        )
        return

    available_keys = available_cgm_metric_keys(computed)

    st.markdown(
        "**How to read this panel:** Phase 1 baseline = the weighted average across **all** Phase 1 days "
        "(no alerts). Each Phase 2 day is compared **individually** to that single baseline, because behavior "
        "change after alerts may take time to appear in glucose control."
    )
    st.caption(
        "All 12 computed CGM metrics are available. Use the picker below to choose which metric to inspect "
        "day-by-day; open the summary expander to compare additional metrics at the period-average level."
    )

    selected_metric = render_cgm_metric_single_picker(
        f"phase_daily_{subject_id}",
        default_key=PHASE_COMPARISON_DEFAULT,
        available_keys=available_keys,
        label="Metric for daily Phase 2 vs Phase 1 baseline",
        help_text="Each Phase 2 day minus the Phase 1 all-days baseline for this metric.",
    )
    meta = CGM_COMPUTED_METRICS[selected_metric]
    baseline = phase_weighted_mean(phase1, selected_metric)
    unit = meta["unit"]
    baseline_text = (
        f"{baseline:{meta['fmt']}}{(' ' + unit) if unit else ''}"
        if baseline is not None
        else "N/A"
    )
    st.info(
        f"**Phase 1 baseline ({meta['label']}):** {baseline_text} "
        f"(average of Days 1–10, no alerts). "
        f"Charts below show each Phase 2 day relative to this value."
    )

    comparison_table = build_phase_comparison_table(computed)
    phase2_metric = comparison_table[comparison_table["metric_key"] == selected_metric].copy()
    if phase2_metric.empty:
        st.info("No daily comparison data for the selected metric.")
        return

    fig_values = build_phase2_daily_values_figure(phase2_metric, selected_metric, theme, compact=compact)
    st.plotly_chart(fig_values, width="stretch")

    fig_delta = build_phase_delta_figure(phase2_metric, selected_metric, theme, compact=compact)
    st.plotly_chart(fig_delta, width="stretch")

    improved_days = int(
        phase2_metric["delta_vs_phase1"].apply(lambda d: delta_is_improvement(selected_metric, d)).sum()
    )
    total_days = len(phase2_metric)
    direction = "Lower" if meta["lower_is_better"] else "Higher"
    st.caption(
        f"Green bars = improvement vs Phase 1 baseline ({improved_days}/{total_days} Phase 2 days). "
        f"{direction} values are better for {meta['label']}. "
        f"Compare this day-by-day pattern with whether the participant describes gradual diet/exercise changes in the Q/A above."
    )

    with st.expander("Overall Phase 1 vs Phase 2 period averages (summary only)"):
        st.caption(
            "Each card shows whether the **Phase 2 period average** improved or worsened vs the "
            "**Phase 1 period average**. The direction hint (↑/↓) indicates which way is healthier "
            "for that metric; the verdict arrow shows how Phase 2 moved relative to Phase 1."
        )
        summary_keys = render_cgm_metric_picker(
            f"phase_summary_{subject_id}",
            default_keys=[key for key in PHASE_SUMMARY_DEFAULT_METRICS if key in available_keys],
            available_keys=available_keys,
            label="Summary metrics to display",
            help_text="Choose which metrics appear in the summary cards and bar chart below.",
            show_presets=True,
        )
        render_phase_summary_cards(phase1, phase2, computed, summary_keys)
        if summary_keys:
            fig_avg = build_phase_average_comparison_figure(
                computed,
                theme,
                metric_keys=summary_keys,
                compact=compact,
            )
            st.plotly_chart(fig_avg, width="stretch")

    with st.expander("View daily comparison table"):
        display = phase2_metric.copy()
        display["start_date"] = display["start_date"].dt.strftime("%Y-%m-%d")
        display["phase2_value"] = display["phase2_value"].map(
            lambda v: format(v, CGM_COMPUTED_METRICS[selected_metric]["fmt"])
        )
        display["phase1_baseline"] = display["phase1_baseline"].map(
            lambda v: format(v, CGM_COMPUTED_METRICS[selected_metric]["fmt"])
        )
        display["delta_vs_phase1"] = display["delta_vs_phase1"].map(
            lambda v: format_phase_delta(selected_metric, float(v))
        )
        display = display.rename(
            columns={
                "start_date": "Date",
                "study_day": "Study Day",
                "phase2_value": "Phase 2 value",
                "phase1_baseline": "Phase 1 baseline",
                "delta_vs_phase1": "Delta (P2 day − P1 baseline)",
            }
        )
        st.dataframe(
            display[["Date", "Study Day", "Phase 2 value", "Phase 1 baseline", "Delta (P2 day − P1 baseline)"]],
            width="stretch",
            hide_index=True,
        )


def summarize_cgm_computed(computed: pd.DataFrame, metric_keys: Optional[List[str]] = None) -> dict:
    if computed.empty:
        return {}
    ndays = computed["ndays"].fillna(0).astype(float)
    total_days = float(ndays.sum())
    weights = ndays / total_days if total_days > 0 else pd.Series([1.0 / len(computed)] * len(computed))

    def weighted_mean(column: str) -> float:
        return float((computed[column].astype(float) * weights).sum())

    keys = metric_keys or list(CGM_COMPUTED_METRICS.keys())
    summary = {
        "wear_start": computed["start_date"].min(),
        "wear_end": computed["end_date"].max(),
        "total_days": round(total_days, 1),
        "n_days": len(computed),
    }
    for key in keys:
        if key in computed.columns:
            summary[key] = weighted_mean(key)
    return summary


def format_metric_value(metric_key: str, value: float) -> str:
    meta = CGM_COMPUTED_METRICS[metric_key]
    unit = meta["unit"]
    formatted = format(value, meta["fmt"])
    return f"{formatted}{(' ' + unit) if unit else ''}"


def _plotly_x_value(value: pd.Timestamp) -> datetime:
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def _plotly_theme_colors(theme: str) -> tuple:
    bg = "#0f1420" if theme == "Dark" else "#ffffff"
    text = "#e8ecf3" if theme == "Dark" else "#1f2937"
    grid = "#263247" if theme == "Dark" else "#e5e7eb"
    return bg, text, grid


def _legend_row_count(item_count: int, items_per_row: int = 2) -> int:
    if item_count <= 0:
        return 0
    return max(1, (item_count + items_per_row - 1) // items_per_row)


def _finalize_plotly_layout(
    fig: go.Figure,
    theme: str,
    *,
    title: str,
    x_title: str = "",
    y_title: str = "Value",
    height: int = 380,
    legend_count: int = 0,
    show_legend: bool = True,
    compact: bool = False,
) -> None:
    bg, text, grid = _plotly_theme_colors(theme)
    items_per_row = 2 if compact else 4
    legend_rows = _legend_row_count(legend_count, items_per_row=items_per_row)
    legend_height = 34 * legend_rows if show_legend and legend_count else 0
    bottom_margin = 64 + legend_height
    total_height = height + legend_height

    layout_kwargs = {
        "height": total_height,
        "margin": {"l": 56, "r": 20, "t": 72, "b": bottom_margin},
        "title": {
            "text": title,
            "font": {"size": 16, "color": text},
            "x": 0,
            "xanchor": "left",
            "y": 0.98,
            "yanchor": "top",
        },
        "paper_bgcolor": bg,
        "plot_bgcolor": bg,
        "xaxis": {
            "title": {"text": x_title, "standoff": 14},
            "gridcolor": grid,
            "color": text,
        },
        "yaxis": {
            "title": {"text": y_title, "standoff": 10},
            "gridcolor": grid,
            "color": text,
        },
    }
    if show_legend and legend_count:
        layout_kwargs["legend"] = {
            "orientation": "h",
            "yanchor": "top",
            "y": -0.24 - 0.10 * max(0, legend_rows - 1),
            "x": 0,
            "xanchor": "left",
            "bgcolor": "rgba(0,0,0,0)",
            "font": {"color": text, "size": 11},
        }
    else:
        layout_kwargs["showlegend"] = False
    fig.update_layout(**layout_kwargs)


def add_phase_boundary_line(fig: go.Figure, boundary: pd.Timestamp) -> None:
    x_val = _plotly_x_value(boundary)
    fig.add_vline(
        x=x_val,
        line={"color": "rgba(251, 191, 36, 0.8)", "width": 2, "dash": "dot"},
    )
    fig.add_annotation(
        x=x_val,
        y=1.02,
        xref="x",
        yref="y domain",
        text="Phase 1 -> Phase 2",
        showarrow=False,
        yanchor="bottom",
        xanchor="left",
        xshift=6,
        font={"color": "rgba(251, 191, 36, 0.95)", "size": 11},
    )


def build_computed_metrics_figure(
    computed: pd.DataFrame,
    metric_keys: List[str],
    theme: str,
    *,
    compact: bool = False,
) -> go.Figure:
    plot_df = computed.dropna(subset=["start_date"]).copy()
    fig = go.Figure()
    if plot_df.empty or not metric_keys:
        return fig

    colors = ["#34d399", "#60a5fa", "#fbbf24", "#f87171", "#a78bfa", "#fb7185"]
    for idx, metric_key in enumerate(metric_keys):
        if metric_key not in plot_df.columns:
            continue
        meta = CGM_COMPUTED_METRICS[metric_key]
        label = meta["label"]
        unit_suffix = f" {meta['unit']}" if meta["unit"] else ""
        fig.add_trace(
            go.Scatter(
                x=plot_df["start_date"],
                y=plot_df[metric_key],
                mode="lines+markers",
                name=f"{label}{unit_suffix}",
                line={"color": colors[idx % len(colors)], "width": 2},
                marker={"size": 6},
                hovertemplate=(
                    f"{label}: %{{y:{meta['fmt']}}}{unit_suffix}"
                    "<br>%{x|%Y-%m-%d}<extra></extra>"
                ),
            )
        )

    phase1 = plot_df[plot_df["study_day"] <= 10]
    phase2 = plot_df[plot_df["study_day"] > 10]
    if not phase1.empty and not phase2.empty:
        add_phase_boundary_line(fig, phase2["start_date"].min())

    _finalize_plotly_layout(
        fig,
        theme,
        title="Daily CGM Computed Metrics",
        x_title="Date",
        y_title="Value",
        height=340 if compact else 420,
        legend_count=len(metric_keys),
        compact=compact,
    )
    fig.update_layout(hovermode="x unified")
    return fig


def build_cgm_figure(
    raw: pd.DataFrame,
    theme: str,
    phase_boundary: Optional[pd.Timestamp] = None,
    *,
    compact: bool = False,
) -> go.Figure:
    plot_df = raw.dropna(subset=["timestamp", GLUCOSE_VALUE_COL]).copy()
    fig = go.Figure()
    if plot_df.empty:
        return fig

    line_color = "#34d399" if theme == "Dark" else "#059669"
    fig.add_trace(
        go.Scatter(
            x=plot_df["timestamp"],
            y=plot_df[GLUCOSE_VALUE_COL],
            mode="lines",
            name="Glucose (mg/dL)",
            line={"color": line_color, "width": 1.5},
            hovertemplate="%{x|%Y-%m-%d %H:%M}<br>Glucose: %{y:.0f} mg/dL<extra></extra>",
        )
    )

    fig.add_hrect(y0=63, y1=140, fillcolor="rgba(52, 211, 153, 0.12)", line_width=0)
    for y_val, color, label in (
        (63, "rgba(96, 165, 250, 0.7)", "63 mg/dL"),
        (140, "rgba(251, 191, 36, 0.7)", "140 mg/dL"),
        (180, "rgba(248, 113, 113, 0.7)", "180 mg/dL"),
    ):
        fig.add_hline(
            y=y_val,
            line={"color": color, "width": 1, "dash": "dash"},
            annotation_text=label,
            annotation_position="right",
        )
    if phase_boundary is not None:
        add_phase_boundary_line(fig, phase_boundary)

    _finalize_plotly_layout(
        fig,
        theme,
        title="CGM Glucose Trace",
        x_title="Time",
        y_title="Glucose (mg/dL)",
        height=300 if compact else 360,
        legend_count=0,
        show_legend=False,
        compact=compact,
    )
    fig.update_layout(hovermode="x unified", yaxis={"rangemode": "tozero"})
    return fig


def render_participant_context_panel(subject_id: str, theme: str, *, compact: bool = False) -> None:
    demo = get_demographics_for_subject(subject_id)
    raw = get_cgm_raw_for_subject(subject_id)
    computed = enrich_computed_with_phase(get_cgm_computed_for_subject(subject_id))
    has_cgm = not raw.empty or not computed.empty

    if not demo and not has_cgm:
        st.info(f"No participant data found for {subject_id}.")
        return

    if demo:
        render_demographics_panel(subject_id, demo, compact=compact)

    if not has_cgm:
        return

    render_subject_cgm_coverage_note(subject_id)

    st.markdown('<div class="section-card card-cgm">', unsafe_allow_html=True)
    st.markdown(f"**CGM — {subject_id}**")
    if not compact:
        st.caption(
            "Sources: `G2_computed_cgm.csv` (daily iglu metrics) and `G2_Raw_cgm.csv` (5-minute raw readings). "
            "G2 study design: Phase 1 (Days 1–10) had masked values and no alerts; "
            "Phase 2 (Days 11–20) sent alerts when glucose exceeded 140 mg/dL. "
            "The post-visit interview is retrospective, so its timeline may not align with the charts below."
        )

    phase_boundary = None
    if not computed.empty:
        phase2 = computed[computed["study_day"] > 10]
        if not phase2.empty:
            phase_boundary = phase2["start_date"].min()

    tab_metrics, tab_phase, tab_raw = st.tabs(
        ["Computed Metrics", "Alert Phase Comparison", "Raw CGM Trace"]
    )

    with tab_metrics:
        if computed.empty:
            st.warning("No computed metrics found for this participant.")
        else:
            available_keys = available_cgm_metric_keys(computed)
            if compact:
                phase_filter = st.selectbox(
                    "Study phase filter",
                    options=CGM_PHASE_OPTIONS,
                    index=0,
                    key=f"cgm_phase_{subject_id}",
                    help="Phase 1 = control period with no alerts. Phase 2 = intervention with >140 mg/dL alerts.",
                )
                selected_metrics = render_cgm_metric_picker(
                    f"cgm_metrics_{subject_id}",
                    default_keys=[key for key in CGM_DEFAULT_METRICS if key in available_keys],
                    available_keys=available_keys,
                    label="Metrics",
                    help_text="All 12 computed CGM metrics are available. Use a preset or pick individually.",
                )
            else:
                ctrl1, ctrl2 = st.columns([1, 1])
                with ctrl1:
                    phase_filter = st.selectbox(
                        "Study phase filter",
                        options=CGM_PHASE_OPTIONS,
                        index=0,
                        key=f"cgm_phase_{subject_id}",
                        help="Phase 1 = control period with no alerts. Phase 2 = intervention with >140 mg/dL alerts.",
                    )
                with ctrl2:
                    st.caption("Metric groups: Alert & time in range · Glycemic control · Variability · Risk indices")
                selected_metrics = render_cgm_metric_picker(
                    f"cgm_metrics_{subject_id}",
                    default_keys=[key for key in CGM_DEFAULT_METRICS if key in available_keys],
                    available_keys=available_keys,
                    label="Metrics to display (select one or more)",
                    help_text="All 12 computed CGM metrics are available. Use a preset or pick individually.",
                )

            filtered_computed = filter_computed_by_phase(computed, phase_filter)
            if filtered_computed.empty:
                st.warning("No computed metrics available for the selected phase.")
            elif not selected_metrics:
                st.info("Select at least one metric to display.")
            else:
                summary = summarize_cgm_computed(filtered_computed, selected_metrics)
                wear_start = summary["wear_start"].strftime("%Y-%m-%d %H:%M")
                wear_end = summary["wear_end"].strftime("%Y-%m-%d %H:%M")
                if not compact:
                    st.markdown(
                        f"**Period:** {wear_start} → {wear_end} "
                        f"({summary['n_days']} daily windows, ~{summary['total_days']} wear-days total)"
                    )
                else:
                    st.caption(f"{wear_start} → {wear_end}")

                metric_cols = st.columns(min(len(selected_metrics), 2 if compact else 4))
                for idx, metric_key in enumerate(selected_metrics):
                    meta = CGM_COMPUTED_METRICS[metric_key]
                    with metric_cols[idx % len(metric_cols)]:
                        st.metric(
                            label=meta["label"],
                            value=format_metric_value(metric_key, summary[metric_key]),
                            help=meta["help"],
                        )

                fig = build_computed_metrics_figure(
                    filtered_computed, selected_metrics, theme, compact=compact
                )
                st.plotly_chart(fig, width="stretch")

                with st.expander("View daily metrics table"):
                    table_cols = ["start_date", "end_date", "study_day", "phase", "ndays"] + selected_metrics
                    table_cols = [c for c in table_cols if c in filtered_computed.columns]
                    display_df = filtered_computed[table_cols].copy()
                    display_df["start_date"] = display_df["start_date"].dt.strftime("%Y-%m-%d")
                    display_df["end_date"] = display_df["end_date"].dt.strftime("%Y-%m-%d")
                    rename_map = {
                        "start_date": "Start",
                        "end_date": "End",
                        "study_day": "Study Day",
                        "phase": "Phase",
                        "ndays": "Days",
                    }
                    for metric_key in selected_metrics:
                        rename_map[metric_key] = CGM_COMPUTED_METRICS[metric_key]["label"]
                    st.dataframe(
                        display_df.rename(columns=rename_map),
                        width="stretch",
                        hide_index=True,
                    )

    with tab_phase:
        if computed.empty:
            st.warning("No computed metrics found for this participant.")
        else:
            render_phase_comparison_panel(computed, subject_id, theme, compact=compact)

    with tab_raw:
        if raw.empty:
            st.warning("No raw CGM readings found for this participant.")
        else:
            raw = raw.copy()
            raw["date"] = raw["timestamp"].dt.date
            available_dates = sorted(raw["date"].dropna().unique())
            date_options = [CGM_RAW_RANGE_ALL] + [d.isoformat() for d in available_dates]
            selected_range = st.selectbox(
                "Raw glucose chart date range",
                options=date_options,
                index=0,
                key=f"cgm_range_{subject_id}",
            )
            plot_raw = raw if selected_range == CGM_RAW_RANGE_ALL else raw[raw["date"].astype(str) == selected_range]
            if plot_raw.empty:
                st.warning("No glucose readings on the selected date.")
            else:
                fig = build_cgm_figure(plot_raw, theme, phase_boundary, compact=compact)
                st.plotly_chart(fig, width="stretch")
                st.caption(
                    f"{len(plot_raw)} readings (every 5 min) | "
                    f"Min {plot_raw[GLUCOSE_VALUE_COL].min():.0f} mg/dL | "
                    f"Max {plot_raw[GLUCOSE_VALUE_COL].max():.0f} mg/dL | "
                    f"Mean {plot_raw[GLUCOSE_VALUE_COL].mean():.0f} mg/dL"
                )

    st.markdown("</div>", unsafe_allow_html=True)


def confidence_option_label(score: int) -> str:
    level = next(item for item in CODING_CONFIDENCE_LEVELS if item["score"] == score)
    return f"{level['score']} — {level['title']}: {level['description']} ({level['guidance']})"


def confidence_short_label(score: int) -> str:
    level = next(item for item in CODING_CONFIDENCE_LEVELS if item["score"] == score)
    return f"{level['score']} — {level['title']}"


def _copy_pattern_map(patterns: Dict[str, List[str]]) -> Dict[str, List[str]]:
    return {cat: list(pats) for cat, pats in patterns.items()}


def _effective_highlight_patterns(en_text: str, es_text: str, lang: str) -> Dict[str, List[str]]:
    patterns = _copy_pattern_map(BEHAVIOR_HIGHLIGHT_PATTERNS)
    en_raw = en_text or ""
    es_raw = es_text or ""
    for cat, en_pat, es_pat in BILINGUAL_KEYWORD_PAIRS:
        if re.search(en_pat, en_raw, flags=re.IGNORECASE) or re.search(es_pat, es_raw, flags=re.IGNORECASE):
            target_pat = en_pat if lang == "en" else es_pat
            if target_pat not in patterns[cat]:
                patterns[cat].append(target_pat)
    return patterns


def _highlight_with_patterns(text: str, patterns: Dict[str, List[str]]) -> str:
    if not text:
        return ""
    matches: List[tuple] = []
    for css_class, pattern_list in patterns.items():
        for pattern in pattern_list:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                matches.append((match.start(), match.end(), css_class))
    if not matches:
        return text
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    merged: List[tuple] = []
    for start, end, css_class in matches:
        if merged and start < merged[-1][1]:
            continue
        merged.append((start, end, css_class))
    parts: List[str] = []
    cursor = 0
    for start, end, css_class in merged:
        parts.append(text[cursor:start])
        parts.append(f'<mark class="{css_class}">{text[start:end]}</mark>')
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _category_counter_from_html(html: str) -> Counter:
    return Counter(re.findall(r'class="(hl-\w+)"', html))


def _remove_last_mark(html: str, category: str) -> str:
    marks = list(re.finditer(rf'<mark class="{re.escape(category)}">([^<]+)</mark>', html))
    if not marks:
        return html
    last = marks[-1]
    return html[: last.start()] + last.group(1) + html[last.end() :]


def _ensure_category_parity(
    en_esc: str,
    es_esc: str,
    en_html: str,
    es_html: str,
    en_patterns: Dict[str, List[str]],
    es_patterns: Dict[str, List[str]],
) -> tuple[str, str]:
    """If a category appears in one language only, activate all paired patterns on the other side."""
    en_c = _category_counter_from_html(en_html)
    es_c = _category_counter_from_html(es_html)
    changed = False
    for cat in ("hl-diet", "hl-exercise", "hl-change", "hl-alert"):
        if cat in en_c and cat not in es_c:
            for pair_cat, _en_pat, es_pat in BILINGUAL_KEYWORD_PAIRS:
                if pair_cat == cat and es_pat not in es_patterns[cat]:
                    es_patterns[cat].append(es_pat)
                    changed = True
        if cat in es_c and cat not in en_c:
            for pair_cat, en_pat, _es_pat in BILINGUAL_KEYWORD_PAIRS:
                if pair_cat == cat and en_pat not in en_patterns[cat]:
                    en_patterns[cat].append(en_pat)
                    changed = True
    if changed:
        en_html = _highlight_with_patterns(en_esc, en_patterns)
        es_html = _highlight_with_patterns(es_esc, es_patterns)
    return en_html, es_html


def _align_category_counts(en_html: str, es_html: str) -> tuple[str, str]:
    """Trim excess marks per category so EN and ES counts match (same category totals)."""
    for cat in ("hl-diet", "hl-exercise", "hl-change", "hl-alert"):
        while True:
            en_n = _category_counter_from_html(en_html).get(cat, 0)
            es_n = _category_counter_from_html(es_html).get(cat, 0)
            if en_n == es_n:
                break
            if en_n > es_n:
                en_html = _remove_last_mark(en_html, cat)
            else:
                es_html = _remove_last_mark(es_html, cat)
    return en_html, es_html


def _balance_bilingual_highlights(
    en_esc: str,
    es_esc: str,
    en_html: str,
    es_html: str,
    en_patterns: Dict[str, List[str]],
    es_patterns: Dict[str, List[str]],
) -> tuple[str, str]:
    """Best-effort count parity: expand patterns on the side with fewer marks per category."""
    for _ in range(4):
        en_c = _category_counter_from_html(en_html)
        es_c = _category_counter_from_html(es_html)
        if en_c == es_c:
            break
        changed = False
        for cat in set(en_c) | set(es_c):
            en_n = en_c.get(cat, 0)
            es_n = es_c.get(cat, 0)
            if en_n == es_n:
                continue
            if en_n < es_n:
                for pat in PARITY_BACKFILL_PATTERNS.get("en", {}).get(cat, []):
                    if pat not in en_patterns[cat]:
                        en_patterns[cat].append(pat)
                        changed = True
                en_html = _highlight_with_patterns(en_esc, en_patterns)
            elif es_n < en_n:
                for pat in PARITY_BACKFILL_PATTERNS.get("es", {}).get(cat, []):
                    if pat not in es_patterns[cat]:
                        es_patterns[cat].append(pat)
                        changed = True
                es_html = _highlight_with_patterns(es_esc, es_patterns)
        if not changed:
            break
    return en_html, es_html


def highlight_behavior_phrases(text: str) -> str:
    return _highlight_with_patterns(text, BEHAVIOR_HIGHLIGHT_PATTERNS)


def format_bilingual_qa_highlight(en_text: str, es_text: str, highlight_enabled: bool) -> tuple[str, str]:
    en_esc = html_module.escape(en_text or "")
    es_esc = html_module.escape(es_text or "")
    if not highlight_enabled:
        return en_esc, es_esc
    en_patterns = _effective_highlight_patterns(en_text, es_text, "en")
    es_patterns = _effective_highlight_patterns(en_text, es_text, "es")
    en_html = _highlight_with_patterns(en_esc, en_patterns)
    es_html = _highlight_with_patterns(es_esc, es_patterns)
    en_html, es_html = _ensure_category_parity(
        en_esc, es_esc, en_html, es_html, en_patterns, es_patterns
    )
    en_html, es_html = _balance_bilingual_highlights(
        en_esc, es_esc, en_html, es_html, en_patterns, es_patterns
    )
    en_html, es_html = _align_category_counts(en_html, es_html)
    return en_html, es_html


def format_qa_text(text: str, highlight_enabled: bool) -> str:
    escaped = html_module.escape(text or "")
    if highlight_enabled:
        return highlight_behavior_phrases(escaped)
    return escaped


def render_behavior_highlight_legend() -> None:
    st.markdown(
        """
        <div class="highlight-legend">
          Keyword assist (not auto-coding):
          <mark class="hl-diet">Diet</mark> food, eating, carbs &nbsp;|&nbsp;
          <mark class="hl-exercise">Exercise</mark> walk, workout, activity &nbsp;|&nbsp;
          <mark class="hl-change">Change</mark> adjust, mindful, habit, rule &nbsp;|&nbsp;
          <mark class="hl-alert">Alert</mark> alarm, spike, beep, puff/pipi, pitada/bip
        </div>
        """,
        unsafe_allow_html=True,
    )


# ----------------------------- UI building blocks -----------------------------

def render_html_markdown(html: str) -> None:
    """Render HTML without CommonMark splitting the block on blank or indented lines."""
    compact = re.sub(r">\s+<", "><", " ".join(html.split()))
    st.markdown(compact, unsafe_allow_html=True)


def render_header_stats(total: int, done_any: int, mine: int, *, show_team: bool = True) -> None:
    remaining = max(0, total - mine)
    pct = (mine / total * 100.0) if total else 0.0
    pills = [f'<span class="stat-pill">Total: <b>{total}</b></span>']
    if show_team:
        pills.append(f'<span class="stat-pill">Any annotator: <b>{done_any}</b></span>')
    pills.append(f'<span class="stat-pill">By you: <b>{mine}</b> ({pct:.1f}%)</span>')
    pills.append(f'<span class="stat-pill">Remaining for you: <b>{remaining}</b></span>')
    render_html_markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
        f'<div style="font-size:26px;font-weight:600;">{html_module.escape(PLATFORM_DISPLAY_NAME)}</div>'
        f'<div style="text-align:right;">{" ".join(pills)}</div></div>'
    )


def _svg_embed_height(svg: str, min_height: int, render_width: float = 960.0) -> int:
    match = re.search(r'viewBox="\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)\s*"', svg)
    if not match:
        return min_height
    vb_w = float(match.group(1))
    vb_h = float(match.group(2))
    if vb_w <= 0:
        return min_height
    scaled = int(vb_h * (render_width / vb_w)) + 48
    return max(min_height, scaled)


def render_svg_embed(filename: str, *, height: int, alt: str = "") -> bool:
    """Render a local SVG via an iframe — reliable when st.image / data-URI img tags fail."""
    path = MANUAL_IMAGES_DIR / filename
    if not path.exists():
        return False
    svg = path.read_text(encoding="utf-8")
    if "<svg" not in svg:
        return False
    safe_alt = html_module.escape(alt)
    embed_height = _svg_embed_height(svg, height)
    styled_svg = svg.replace(
        "<svg ",
        (
            f'<svg aria-label="{safe_alt}" preserveAspectRatio="xMinYMin meet" '
            f'style="width:100%;max-width:960px;height:auto;display:block;" '
        ),
        1,
    )
    components.html(
        f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:transparent;overflow-x:hidden;overflow-y:auto;">
{styled_svg}
</body></html>""",
        height=embed_height,
        scrolling=True,
    )
    return True


def render_g2_study_timeline() -> None:
    if not render_svg_embed(
        G2_STUDY_TIMELINE_SVG,
        height=650,
        alt="G2 study 20-day timeline",
    ):
        st.warning("Study timeline diagram is not available.")
        return
    st.caption(G2_STUDY_TIMELINE_CAPTION)


def render_preliminary_examples() -> None:
    st.markdown(PRELIMINARY_EXAMPLES_INTRO)
    if not render_svg_embed(
        PRELIMINARY_EXAMPLES_SVG,
        height=920,
        alt="Worked scoring examples for Primary 0 through 3",
    ):
        st.warning("Preliminary examples diagram is not available.")
        st.markdown(PRELIMINARY_EXAMPLES_TEXT_MD)


def render_scoring_workflow_visual() -> None:
    if not render_svg_embed(
        SCORING_WORKFLOW_SVG,
        height=900,
        alt="Scoring workflow steps 1 through 11",
    ):
        st.warning("Workflow diagram is not available.")
        st.markdown(
            """
            1. Finish **Initial Training** and pass the **Test Drive**.
            2. Read the **Answer** (only this is scored).
            3. Use the **Question** for context only.
            4. Pick **Primary 0-4**, then confidence, components, rule fields if needed, evidence, save.
            """
        )


def render_contingency_chain_visual() -> None:
    if not render_svg_embed(
        CONTINGENCY_CHAIN_MINI_SVG,
        height=450,
        alt="Context, behavior, outcome, and rule chain",
    ):
        st.warning("Chain diagram is not available.")


def render_what_you_will_do_steps() -> None:
    st.markdown("### What you will do")
    st.markdown(WHAT_YOU_WILL_DO_INTRO)
    st.markdown(
        """
        <div class="section-card card-question">
            <div class="instruction-step-title">1. The PRIMARY HIERARCHY (0–4)</div>
            <div class="instruction-step-body">Assign <strong>one</strong> level for how far the Answer gets along this
            four-part chain. This is the main score — <strong>choose it first</strong>.</div>
            <div class="instruction-step-body" style="margin-top:8px;">
            <strong>Memory hook — ask four questions in order:</strong>
            <em>When/where?</em> → <em>What did they do?</em> → <em>What happened to glucose?</em> →
            <em>What will they do next time?</em>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_contingency_chain_visual()
    st.markdown(
        """
        <div class="section-card card-answer">
            <div class="instruction-step-title">2. The COMPONENTS</div>
            <div class="instruction-step-body">Tick the same four boxes when each part is actually in the Answer:
            <strong>Context</strong>, <strong>Behavior</strong>, <strong>Consequence</strong> (outcome), and
            <strong>Rule</strong>. Only tick what the words support — no guessing.</div>
        </div>
        <div class="section-card card-save">
            <div class="instruction-step-title">3. RULE SOURCE and BEHAVIOR FORM</div>
            <div class="instruction-step-body">When a rule is present (or Primary is 3–4), record
            <strong>Rule Source</strong> and <strong>Behavior Form</strong> — where the rule came from and whether
            change has started or is only planned.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_task_about_content(user: Optional[dict] = None) -> None:
    st.markdown(TASK_ABOUT_STUDY_MD)
    render_what_you_will_do_steps()
    st.markdown(TASK_ABOUT_RULES_MD)
    if user and user_is_admin(user):
        st.markdown(ADMIN_TASK_ABOUT_EXTRA_MD)


def render_primary_hierarchy_panel() -> None:
    with st.expander("Primary Hierarchy reference (0–4) — click to expand", expanded=False):
        st.markdown(
            "Each Answer receives one Primary score. Score only what the Answer itself supports; resolve ambiguity conservatively."
        )
        for lv in primary_levels_for_display():
            st.markdown(
                f"""
                <div class="level-card">
                  <b>Level {lv['level']} — {lv['title']}</b><br/>
                  {lv['definition']}<br/>
                  <i>Example:</i> {lv['example']}
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_secondary_components_panel() -> None:
    with st.expander("Secondary Components (Context/Behavior/Consequence/Rule) — click to expand", expanded=False):
        st.markdown(
            "Mark each component only when it is present in the Answer. Treat the checked components as a structured description of what the Answer includes."
        )
        for c in secondary_components_for_display():
            st.markdown(
                f"""
                <div class="level-card">
                  <b>{c['name']}</b><br/>
                  {c['definition']}<br/>
                  <i>Example:</i> {c['example']}
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_code_definition_hover_list(cands: List[tuple]) -> None:
    if not cands:
        return
    chips = []
    for cid, meta in cands:
        label = html_module.escape(f"{meta['name']} ({cid})")
        definition = html_module.escape(meta.get("definition", ""))
        chips.append(f'<span class="code-hover-chip" title="{definition}">{label}</span>')
    st.markdown(
        '<div class="code-hover-wrap">' + "".join(chips) + "</div>",
        unsafe_allow_html=True,
    )


# ----------------------------- Pages -----------------------------

TASK_SHORT_INTRO = (
    "Welcome! This is a research **scoring** platform for the **G2 continuous glucose "
    "monitoring (CGM) study**. You will read short interview answers and score how each "
    "participant describes the link between their glucose feedback and their behavior. "
    "New here? Open the **Register** tab for a full task overview and to create an account."
)

PRELIMINARY_EXAMPLES_INTRO = (
    "This is an early study with a **small sample**. Below are **four worked examples** — one for each "
    "score from **0 to 3**. Read the **Answer** only; the **Question** is there to set the scene."
)

PRELIMINARY_EXAMPLES_TEXT_MD = """
| Score | Answer (short) | Why |
|-------|----------------|-----|
| **0** | *No. Everything was good.* | General opinion — no link at all |
| **1** | *My glucose was high one morning.* | Outcome only — no cause or plan |
| **2** | *After I drank soda at lunch, my numbers spiked.* | Context + behavior + outcome — no rule |
| **3** | *Walking seems to help, so I'm going to try it after every meal.* | Rule forming — plan, not yet firm |

Score **4** (clear personal rule already in place) is shown in the chain diagram under **What you will do**.
"""

# Kept for markdown manual export (text fallback).
PRELIMINARY_STUDY_EXAMPLES_MD = PRELIMINARY_EXAMPLES_TEXT_MD

TASK_ABOUT_STUDY_MD = """
### About this study
Participants in the **G2 study** wore a **continuous glucose monitor (CGM)** for a period and were
interviewed afterward about what they noticed. We are studying **how people make sense of their
glucose feedback** and whether they begin to form their own **behavior rules** — for example,
*"I noticed tortillas at night spike my glucose, so now I avoid them at dinner."*
"""

WHAT_YOU_WILL_DO_INTRO = (
    "You score each participant **Answer** from these interviews. "
    "For every Answer you will score the same **three things**, always in this order:"
)

TASK_ABOUT_RULES_MD = """
### The golden rule
**Score only the participant's response (the Answer) to the text they were shown — nothing else.**

There is **no room for imagination or inference**. Do **not** add your own interpretation, assumptions,
or personal guesses about what the person "probably" meant, felt, or intended. If something is **not
written in the Answer**, it **does not count** — even if it seems obvious to you.

- Do **not** judge whether the glucose numbers are good or bad.
- Do **not** apply outside medical knowledge or decide what is medically "correct."
- Do **not** infer hidden intent, background, or what you think they *should* have said.

Read the **Answer** first. The **Question** is shown **only** to help you understand the **Context**
(the situation the person was responding to). **Do not score the Question.** Do not use the Question
as evidence — only the Answer counts.

### What to expect
Follow the steps in the left sidebar, in order:
1. **Step 1 · Introduction** — why we are doing this and how the site works (you start here).
2. **Step 2 · User Manual** — plain-language guide to every field on the scoring form.
3. **Step 3 · Initial Training** — practice pass: pocket references and the **Test Drive** (unlocks scoring).
4. **Step 4 · Score Answers** — unlocks after training; score real Answers at your own pace.
5. **Step 5 · My Progress** — your saved scores.
"""

ADMIN_TASK_ABOUT_EXTRA_MD = """
6. **Step 6 · Quality & Agreement** (admin only) — inter-rater agreement, gold check samples, and coder progress.
"""

# Step 3 (Initial Training) — practice-focused copy; do not repeat Step 1 study intro or worked examples.
TRAINING_PAGE_LEDE = (
    "**Step 1** covered the study background and worked examples. **Step 2** covers the full interface. "
    "**This page is practice** — use the pocket references while you complete the Test Drive, then "
    "unlock real scoring."
)

TRAINING_MEMORY_HOOK = (
    "When stuck on Primary, ask in order: **When/where?** → **What did they do?** → "
    "**What happened to glucose?** → **What will they do next time?**"
)

TRAINING_SCORE_RULER: List[tuple[str, str, str, str]] = [
    ("0", "#94a3b8", "No link", "General comment — nothing connects"),
    ("1", "#64748b", "Outcome only", "Glucose mentioned, no cause"),
    ("2", "#8e6cff", "Cause, no plan", "Context + behavior + outcome"),
    ("3", "#f59e0b", "Change starting", "Rule forming or trying something new"),
    ("4", "#35b46b", "Clear rule", "States what they will do from now on"),
]

# Deep, beginner-friendly explanation of the main score and the four-part chain.
# Reused on the Introduction, Register, and User Manual pages so
# the same plain-language definition appears everywhere a new annotator might look.
CONTINGENCY_CHAIN_MD = """
### What "Primary Hierarchy" means (the main score)
**Primary Hierarchy** is the single most important rating, and the one you choose **first**. Don't let
the name worry you — think of it as a **ladder with five rungs (0–4)**. "Hierarchy" just means the rungs
**build on each other**: a higher rung includes the thinking of the rungs below it. Every rung answers
one question: *how far has this person gone in connecting their own actions to their glucose, and in
turning that into a rule for next time?*

### The chain: context → behavior → outcome → rule
Most Answers can be read as a short story with up to four parts. Your job is to see **how many of these
parts appear** and **whether they connect**. **Always start by finding the Context** — without it, the
rest of the story is hard to judge.

- **Context — the situation: when / where / what was going on. This is the most important part to find
  first.** Context is your **anchor**: *"at dinner," "after a long walk," "when I drink soda."* It tells
  you the setting the rest of the story hangs on. **Without a clear Context it is hard to tell whether a
  real behavior → outcome link (let alone a rule) is being expressed**, so **always identify the Context
  before anything else**. Once you have it, the rest of the Answer becomes much easier to read.
- **Behavior — what the person actually did.** *"I ate rice," "I went walking," "I cut my portion."*
  This is the action that can be tied to a glucose change.
- **Outcome (Consequence) — what happened to the glucose afterward.** *"it went up," "it stayed flat,"
  "it came back down."* This is the feedback the person noticed.
- **Rule — the lesson for the future ("from now on I will…").** *"so now I avoid tortillas at dinner."*
  This is the **top of the ladder**: it shows the person *learned* something, not just *observed* it.

### How the chain becomes the 0–4 score
- **0** — Nothing connects; it's a general comment. *("It was fine.")*
- **1** — Only an **outcome** is described, with no cause. *("My sugar went up.")*
- **2** — **Context + Behavior + Outcome** are linked into a real cause-and-effect, but there is **no rule yet**. *("When I eat rice at dinner, it goes up.")*
- **3** — A **rule is forming**: a tentative or planned change based on what they noticed. *("Soda spikes me, so I'm trying water instead.")*
- **4** — A **clear, self-made rule** is stated. *("Tortillas at night spike me, so now I skip them at dinner.")*

**Tip:** find the **Context** first, then check whether a **Behavior**, an **Outcome**, and finally a
**Rule** are attached. The further along the chain the Answer goes, the higher the score. If you are
unsure between two rungs, add a short **comment** and a **review flag** so the item can be discussed —
do not guess.
"""


def page_introduction(user: Optional[dict] = None) -> None:
    st.header("Introduction")
    st.caption("Why this project exists and what we are trying to learn.")

    st.subheader("Why we are collecting this")
    st.markdown(
        """
        People who wear a **continuous glucose monitor (CGM)** can see, in near real time, how their
        glucose responds to food, activity, stress, and timing. A central question for diabetes care is
        whether that feedback actually helps people **learn** — that is, whether they move from simply
        *noticing* a number to **forming their own behavior rules** that guide future choices.

        To study this, **G2 study** participants wore a CGM and were interviewed afterward about what they
        noticed and what they changed. Their interview **Answers** are the raw material for this project.
        By scoring these Answers consistently, we can measure **how and when CGM feedback turns into
        self-management learning**, and use that to design better CGM-based education and coaching.
        """
    )
    st.subheader("How the G2 study worked (20 days)")
    render_g2_study_timeline()
    st.info(
        "This is an early **preliminary study** that uses a **small sample** of participants. "
        "Because the dataset is small, every Answer counts — your careful, consistent scoring directly "
        "shapes the quality of the findings."
    )

    st.subheader("Preliminary examples (read these first)")
    render_preliminary_examples()

    st.subheader("Project goals")
    if user and user_is_admin(user):
        goals_md = """
        1. **Measure language maturity.** Give each Answer a single 0–4 score (the **Primary Hierarchy**,
           explained in detail below) for how strongly it expresses a
           *context → behavior → outcome → rule* relationship.
        2. **Identify the building blocks.** Mark which **Components** (Context, Behavior, Consequence,
           Rule) appear, and, when a rule is present, its **Rule Source** and **Behavior Form**.
        3. **Measure how reliable the scores are.** To judge whether our coders are dependable, several
           annotators score the **same** Answers, and we calculate the **inter-rater agreement** —
           that is, *how often independent coders give the same score on the same items*. High agreement
           is our main signal that the scores are trustworthy and that everyone is applying the scheme the
           same way. Initial Training, a short Test Drive, and hidden quality checks all support this.
        4. **Turn your scores into insight.** Your careful scores are the actual data for this research.
           Once enough Answers are scored the same consistent way, the team can step back and look across
           many participants to ask real questions — for example: *Do people who form their own rules
           (Primary 3–4) end up managing their glucose better? At what point does wearing a sensor start
           to change how someone thinks?* In other words, the small score you give each Answer becomes one
           piece of a much bigger picture about **how people learn from glucose feedback**. None of that
           analysis is possible without consistent, honest scoring — so your work here matters directly.
        """
    else:
        goals_md = """
        1. **Measure language maturity.** Give each Answer a single 0–4 score (the **Primary Hierarchy**)
           for how strongly it expresses a *context → behavior → outcome → rule* relationship.
        2. **Identify the building blocks.** Mark which **Components** (Context, Behavior, Consequence,
           Rule) appear, and, when a rule is present, its **Rule Source** and **Behavior Form**.
        3. **Score consistently and carefully.** Read each Answer on its own words. If something is unclear,
           add a comment and a review flag instead of guessing.
        4. **Your scores matter.** Each Answer you score becomes part of the research on how people learn
           from glucose feedback. Consistent, honest scoring is what makes the findings trustworthy.
        """
    st.markdown(goals_md)

    st.subheader("What you will be doing")
    render_task_about_content(user)

    st.subheader("Where to go next")
    next_steps = [
        "Use the steps in the left sidebar, in order:",
        "- **Step 1 · Introduction** — you are here: the study, the goals, and how to use the site.",
        "- **Step 2 · User Manual** — how the interface works, step by step.",
        "- **Step 3 · Initial Training** — practice with pocket references and the Test Drive (unlocks scoring).",
        "- **Step 4 · Score Answers** — score real Answers once training is complete.",
        "- **Step 5 · My Progress** — your saved scores.",
    ]
    if user and user_is_admin(user):
        next_steps.append(
            "- **Step 6 · Quality & Agreement** — agreement and quality metrics (admin only)."
        )
    st.markdown("\n".join(next_steps))

    st.success(
        "Now you know the goals and how to get around the site. When you are ready, continue to "
        "**Step 2 · User Manual**."
    )


def page_login() -> None:
    st.title(PLATFORM_DISPLAY_NAME)
    st.caption(PLATFORM_LOGIN_CAPTION)
    st.info(TASK_SHORT_INTRO)
    tab_login, tab_register = st.tabs(["Sign In", "Register"])

    with tab_login:
        with st.form("login_form"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            remember = st.checkbox(
                "Keep me signed in on this device (about 30 days)",
                value=True,
            )
            ok = st.form_submit_button("Sign In", type="primary")
        if ok:
            user = authenticate(u, p)
            if user is None:
                st.error("Invalid username or password.")
            else:
                st.session_state.user = user
                st.session_state.pop("_signed_out", None)
                set_auth_cookie(user["username"], remember=remember)
                st.success(f"Welcome, {user.get('display_name', user['username'])}.")
                st.rerun()

    with tab_register:
        st.markdown("#### What is this task?")
        st.markdown(
            "Before you score anything, it helps to know **what participants went through** in the G2 study:"
        )
        render_g2_study_timeline()
        render_task_about_content(None)
        st.caption(
            "After you create an account, open **Step 1 · Introduction** for three worked examples and "
            "**Step 3 · Initial Training** for quick references and the Test Drive."
        )
        st.divider()
        st.markdown("#### Create your account")
        st.caption(
            "Pick a username and password to track your own labels. "
            "There is no email and no personal data required."
        )
        with st.form("register_form"):
            ru = st.text_input("New Username (>=3 chars, lowercased)")
            rd = st.text_input("Display Name (optional)")
            rp = st.text_input("Password (>=6 chars)", type="password")
            rp2 = st.text_input("Confirm Password", type="password")
            create = st.form_submit_button("Create Account", type="primary")
        if create:
            if rp != rp2:
                st.error("Passwords do not match.")
            else:
                err = register_user(ru, rp, rd)
                if err:
                    st.error(err)
                else:
                    st.success("Account created. Please sign in on the Sign In tab.")


def filter_qa_items_for_subject(
    qa_items: List[dict],
    subject_id: str,
    *,
    annotated_map: Dict[str, dict],
    unlabeled_only: bool,
    mine_only: bool,
    username: str,
) -> List[dict]:
    filtered: List[dict] = []
    for item in qa_items:
        if item["subject_id"] != subject_id:
            continue
        qa_id = item["qa_id"]
        if unlabeled_only and qa_id in annotated_map:
            continue
        if mine_only:
            ann = annotated_map.get(qa_id)
            if not ann or ann.get("coder_username") != username:
                continue
        filtered.append(item)
    return filtered


def find_next_subject_with_visible_items(
    subjects: List[str],
    start_subject: str,
    qa_items: List[dict],
    *,
    annotated_map: Dict[str, dict],
    unlabeled_only: bool,
    mine_only: bool,
    username: str,
) -> Optional[str]:
    if start_subject not in subjects:
        return None
    start_idx = subjects.index(start_subject)
    for subject_id in subjects[start_idx + 1 :]:
        if filter_qa_items_for_subject(
            qa_items,
            subject_id,
            annotated_map=annotated_map,
            unlabeled_only=unlabeled_only,
            mine_only=mine_only,
            username=username,
        ):
            return subject_id
    return None


def advance_qa_navigation(
    *,
    subjects: List[str],
    current_subject: str,
    cursor: int,
    filtered: List[dict],
    auto_advance_subject: bool,
    qa_items: List[dict],
    annotated_map: Dict[str, dict],
    unlabeled_only: bool,
    mine_only: bool,
    username: str,
) -> tuple[str, int, Optional[str]]:
    """Move to the next Answer item, or the next subject when at the end of the current list."""
    if not filtered:
        return current_subject, 0, None
    if cursor < len(filtered) - 1:
        return current_subject, cursor + 1, None
    if not auto_advance_subject:
        return current_subject, cursor, None
    next_subject = find_next_subject_with_visible_items(
        subjects,
        current_subject,
        qa_items,
        annotated_map=annotated_map,
        unlabeled_only=unlabeled_only,
        mine_only=mine_only,
        username=username,
    )
    if not next_subject:
        return (
            current_subject,
            cursor,
            "You are on the last visible item. No further subjects match the current filters.",
        )
    return (
        next_subject,
        0,
        f"Finished **{current_subject}**. Moved to next subject: **{next_subject}**.",
    )


def page_annotate(user: dict, theme: str = "Light") -> None:
    if SIMPLE_LABELING_MODE and not simple_training_is_complete(user):
        st.warning(
            "Please complete **Initial Training** before starting formal Answer scoring. "
            "Read the references and pass the short Test Drive to unlock this page."
        )
        st.stop()

    if not SIMPLE_LABELING_MODE and not user.get("training_completed", False):
        st.warning(
            "Before you can start scoring, please review the **Coder Training** page first. "
            "Open it from the sidebar, read through all sections, then click "
            "*'I have completed the Coder Training'* at the bottom of that page."
        )
        st.stop()

    codes_df = load_codes()
    qa_items = build_qa_items()
    annotations_df = load_annotations()
    username = user["username"]

    check_samples = check_sample_map()
    if check_samples:
        attention_status = user_attention_check_status(annotations_df, check_samples, username)
        if attention_status["flagged"]:
            accuracy_pct = (attention_status["accuracy"] or 0) * 100
            st.error(
                f"**Please slow down and read each Answer carefully.** "
                f"You passed only {attention_status['passed']} of "
                f"{attention_status['reached']} attention checks ({accuracy_pct:.0f}%). "
                f"These items have a clear, unambiguous answer, so a low score usually means "
                f"items are being labeled too quickly. Your recent labels may be reviewed. "
                f"Re-read the **Initial Training** references if you are unsure."
            )

    user_annotations_df = (
        annotations_df[annotations_df["coder_username"].astype(str).str.lower() == username].copy()
        if not annotations_df.empty
        else pd.DataFrame(columns=ANNOTATION_COLUMNS)
    )
    annotated_map: Dict[str, dict] = {}
    all_annotated_qa_ids: set[str] = set()
    qa_coder_counts: Dict[str, int] = {}
    if not annotations_df.empty:
        all_annotated_qa_ids = set(annotations_df["qa_id"].astype(str))
        qa_coder_counts = (
            annotations_df.groupby("qa_id")["coder_username"]
            .nunique()
            .astype(int)
            .to_dict()
        )
    if not user_annotations_df.empty:
        annotated_map = {
            str(row["qa_id"]): row.to_dict()
            for _, row in user_annotations_df.iterrows()
            if str(row.get("qa_id", ""))
        }

    subjects = sorted({x["subject_id"] for x in qa_items})
    if not subjects:
        st.warning("No scoring items available.")
        return

    qa_subject_counts = Counter(x["subject_id"] for x in qa_items)

    st.sidebar.header("Filters")
    st.sidebar.caption(
        f"**{len(subjects)}** participants with Answer items to label. "
        "Switch **Subject** below to view each participant."
    )

    if "annotate_subject" not in st.session_state or st.session_state.annotate_subject not in subjects:
        st.session_state.annotate_subject = subjects[0]
    prev_subject = st.session_state.annotate_subject
    subject_filter = st.sidebar.selectbox(
        "Subject",
        subjects,
        index=subjects.index(st.session_state.annotate_subject),
        help=None if SIMPLE_LABELING_MODE else "Switch to a participant's interview Answer items.",
    )
    st.sidebar.caption(
        f"Selected **{subject_filter}** · Answer items {qa_subject_counts.get(subject_filter, 0)}"
    )
    if subject_filter != prev_subject:
        st.session_state.cursor = 0
    st.session_state.annotate_subject = subject_filter

    auto_advance_subject = st.sidebar.checkbox(
        "Auto-advance to next subject when finished",
        value=st.session_state.get("auto_advance_subject", True),
        help=(
            "When you reach the last visible Answer item for this subject, "
            "Next / Save and Next moves to the first item of the next subject "
            "(respects filters). Turn off to stay on the last item and pick a subject manually."
        ),
    )
    st.session_state.auto_advance_subject = auto_advance_subject

    if nav_flash := st.session_state.pop("_nav_flash", None):
        if "No further subjects" in nav_flash:
            st.info(nav_flash)
        else:
            st.success(nav_flash)

    subj_qa_items = [x for x in qa_items if x["subject_id"] == subject_filter]
    total = len(subj_qa_items)
    done = sum(1 for x in subj_qa_items if x["qa_id"] in all_annotated_qa_ids)
    mine = sum(
        1
        for x in subj_qa_items
        if annotated_map.get(x["qa_id"], {}).get("coder_username") == user["username"]
    )
    render_header_stats(total, done, mine, show_team=user_is_admin(user))

    unlabeled_only = st.sidebar.checkbox("Show unlabeled by me only", value=False)
    mine_only = st.sidebar.checkbox("Show only my saved labels", value=False)
    highlight_behavior = False
    highlight_answers_only = True

    filtered = filter_qa_items_for_subject(
        qa_items,
        subject_filter,
        annotated_map=annotated_map,
        unlabeled_only=unlabeled_only,
        mine_only=mine_only,
        username=user["username"],
    )

    _nav_ctx = {
        "subjects": subjects,
        "subject_filter": subject_filter,
        "auto_advance_subject": auto_advance_subject,
        "qa_items": qa_items,
        "annotated_map": annotated_map,
        "unlabeled_only": unlabeled_only,
        "mine_only": mine_only,
        "username": user["username"],
    }

    if not filtered:
        st.warning("No items available under the current filters.")
        return

    if "cursor" not in st.session_state:
        st.session_state.cursor = 0
    st.session_state.cursor = max(0, min(st.session_state.cursor, len(filtered) - 1))

    _render_qa_labeling_workspace(
        user=user,
        theme=theme,
        filtered=filtered,
        annotated_map=annotated_map,
        qa_coder_counts=qa_coder_counts,
        codes_df=codes_df,
        highlight_behavior=highlight_behavior,
        highlight_answers_only=highlight_answers_only,
        always_show_cgm=False,
        nav_ctx=_nav_ctx,
    )

    adjudication_df = build_adjudication_candidates(subject_filter, subj_qa_items, annotated_map)
    annotation_audit = audit_annotation_records(qa_items)
    if user_is_admin(user):
        with st.sidebar.expander("Saved score status", expanded=False):
            st.caption(f"File: `{ANNOTATIONS_PATH.name}`")
            st.write(
                f"Saved rows: **{annotation_audit['total']}** · "
                f"Subjects: **{annotation_audit['subjects']}** · "
                f"Annotators: **{annotation_audit['coders']}**"
            )
            if annotation_audit["issues"]:
                st.warning("Saved score integrity issues detected:")
                for issue in annotation_audit["issues"][:20]:
                    st.markdown(f"- {issue}")
                if len(annotation_audit["issues"]) > 20:
                    st.caption(f"... and {len(annotation_audit['issues']) - 20} more")
            else:
                st.success("All saved score rows pass integrity checks.")
        with st.sidebar.expander("Adjudication queue (this subject)", expanded=False):
            if adjudication_df.empty:
                st.caption("No saved items flagged for adjudication on this subject.")
            else:
                st.caption("Items with confidence 1–2.")
                st.dataframe(adjudication_df, width="stretch", hide_index=True)

    st.sidebar.markdown(f"**Saved by you:** {mine} / {total}")
    if user_is_admin(user):
        st.sidebar.markdown(f"**Saved by any annotator:** {done} / {total}")
    st.sidebar.markdown(f"**Visible:** {len(filtered)}")
    if user_is_admin(user):
        st.sidebar.caption(f"Data file: {ANNOTATIONS_PATH.name}")


def split_into_sentences(text: str) -> List[str]:
    """Split an Answer into pickable sentence chunks for the evidence selector."""
    text = (text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part.strip() for part in parts if part.strip()]


def _render_qa_labeling_workspace(
    *,
    user: dict,
    theme: str,
    filtered: List[dict],
    annotated_map: Dict[str, dict],
    qa_coder_counts: Dict[str, int],
    codes_df: pd.DataFrame,
    highlight_behavior: bool,
    highlight_answers_only: bool,
    always_show_cgm: bool = False,
    nav_ctx: Optional[dict] = None,
) -> None:
    def _go_next() -> None:
        if not nav_ctx:
            st.session_state.cursor = min(len(filtered) - 1, st.session_state.cursor + 1)
            st.rerun()
            return
        new_subject, new_cursor, msg = advance_qa_navigation(
            subjects=nav_ctx["subjects"],
            current_subject=nav_ctx["subject_filter"],
            cursor=st.session_state.cursor,
            filtered=filtered,
            auto_advance_subject=nav_ctx["auto_advance_subject"],
            qa_items=nav_ctx["qa_items"],
            annotated_map=nav_ctx["annotated_map"],
            unlabeled_only=nav_ctx["unlabeled_only"],
            mine_only=nav_ctx["mine_only"],
            username=nav_ctx["username"],
        )
        st.session_state.annotate_subject = new_subject
        st.session_state.cursor = new_cursor
        if msg:
            st.session_state._nav_flash = msg
        st.rerun()

    col_nav1, col_nav2, col_nav3 = st.columns([1, 2, 1])
    with col_nav1:
        if st.button("Previous", width="stretch"):
            st.session_state.cursor = max(0, st.session_state.cursor - 1)
            st.rerun()
    with col_nav2:
        pos = st.number_input(
            "Current Position",
            min_value=1,
            max_value=len(filtered),
            value=st.session_state.cursor + 1,
            step=1,
        )
        st.session_state.cursor = int(pos) - 1
    with col_nav3:
        if st.button("Next", width="stretch"):
            _go_next()

    item = filtered[st.session_state.cursor]
    existing = annotated_map.get(item["qa_id"], {})
    has_existing_annotation = bool(existing)

    # Per-subject progress (for whichever subject is currently displayed)
    cur_subj = item["subject_id"]
    subj_items = [x for x in filtered if x["subject_id"] == cur_subj]
    subj_done = sum(1 for x in subj_items if x["qa_id"] in annotated_map)
    subj_idx_within = next(
        (i for i, x in enumerate(subj_items) if x["qa_id"] == item["qa_id"]),
        0,
    ) + 1
    render_html_markdown(
        f"<div class='stat-pill'><b>Subject:</b> {html_module.escape(str(cur_subj))} | "
        f"<b>Item in subject:</b> {subj_idx_within}/{len(subj_items)} | "
        f"<b>Subject progress:</b> {subj_done}/{len(subj_items)}</div>"
    )
    coded_by = existing.get("coder_username", "") if existing else ""
    coded_at = existing.get("updated_at_utc", "") if existing else ""
    coder_count = int(qa_coder_counts.get(item["qa_id"], 0))

    pill_status = (
        f"<span class='meta-pill'><b>Your status</b>: saved at {coded_at}</span>"
        if coded_by
        else "<span class='meta-pill'><b>Your status</b>: not saved</span>"
    )
    render_html_markdown(
        f'<div>'
        f'<span class="meta-pill"><b>Subject</b>: {html_module.escape(str(item["subject_id"]))}</span> '
        f'<span class="meta-pill"><b>Question line</b>: {item["question_line_no"]}</span> '
        f'<span class="meta-pill"><b>Answer line</b>: {item["answer_line_no"]}</span> '
        f'<span class="meta-pill"><b>Item ID</b>: {html_module.escape(str(item["qa_id"]))}</span> '
        f'<span class="meta-pill"><b>Annotators saved</b>: {coder_count}</span> '
        f'{pill_status}'
        f'</div>'
    )

    highlight_questions = highlight_behavior and not highlight_answers_only
    highlight_answers = highlight_behavior
    q_en, q_es = format_bilingual_qa_highlight(
        item.get("question_en", "") or "",
        item.get("question_es", "") or "",
        highlight_questions,
    )
    a_en, a_es = format_bilingual_qa_highlight(
        item.get("answer_en", "") or "",
        item.get("answer_es", "") or "",
        highlight_answers,
    )

    if highlight_behavior:
        render_behavior_highlight_legend()

    render_html_markdown(
        f'<div class="frozen-qa-spacer"></div>'
        f'<div class="sticky-qa-panel"><div class="sticky-qa-grid">'
        f'<div class="section-card card-question qa-card">'
        f'<div class="qa-title">Question <span class="qa-role-note">(context only)</span></div>'
        f'<div class="qa-text"><span class="qa-label">English:</span> {q_en}</div>'
        f'<div class="qa-text"><span class="qa-label">Spanish:</span> {q_es}</div>'
        f'</div>'
        f'<div class="section-card card-answer qa-card">'
        f'<div class="qa-title">Answer <span class="qa-role-note">(main text to code)</span></div>'
        f'<div class="qa-text"><span class="qa-label">English:</span> {a_en}</div>'
        f'<div class="qa-text"><span class="qa-label">Spanish:</span> {a_es}</div>'
        f'</div></div></div>'
    )

    qa_text = " ".join(
        [
            str(item.get("question_en") or ""),
            str(item.get("question_es") or ""),
            str(item.get("answer_en") or ""),
            str(item.get("answer_es") or ""),
        ]
    )
    show_early_cgm, early_cgm_reason = (
        (False, "")
        if SIMPLE_LABELING_MODE
        else should_show_early_cgm_summary(
            qa_text,
            always_show=always_show_cgm,
        )
    )
    if show_early_cgm:
        render_cgm_coding_context_summary(
            item["subject_id"],
            reason=early_cgm_reason,
            qa_text=qa_text,
            show_table=True,
            show_extras=False,
            theme=theme,
        )

    existing_code_ids_raw = (
        str(existing.get("selected_code_ids", "")) if existing else ""
    )
    if not existing_code_ids_raw:
        legacy = str(existing.get("selected_code_id", "")) if existing else ""
        existing_code_ids = parse_code_ids(legacy) if legacy and legacy != OTHER_CODE else []
    else:
        existing_code_ids = [c for c in parse_code_ids(existing_code_ids_raw) if c != OTHER_CODE]
    existing_is_other = parse_annotation_bool(existing.get("is_other")) if existing else False

    # Build code lookup tables
    codes_df_sorted = codes_df.sort_values(["code_group", "subgroup", "code_name"]).copy()
    code_index: Dict[str, Dict[str, str]] = {}
    for _, r in codes_df_sorted.iterrows():
        code_index[str(r["code_id"])] = {
            "group": str(r["code_group"]),
            "subgroup": str(r["subgroup"]),
            "name": str(r["code_name"]),
            "label": f"{r['code_name']} ({r['code_id']})",
            "definition": str(r["definition"]),
        }
    groups_list = [] if SIMPLE_LABELING_MODE else sorted({v["group"] for v in code_index.values()})

    def subgroups_in(g: str) -> List[str]:
        return sorted({v["subgroup"] for v in code_index.values() if v["group"] == g})

    def codes_in(g: str, sg: str) -> List[tuple]:
        items = [
            (cid, v) for cid, v in code_index.items()
            if v["group"] == g and v["subgroup"] == sg
        ]
        items.sort(key=lambda x: x[1]["name"])
        return items

    def codes_in_group(g: str) -> List[tuple]:
        items = [(cid, v) for cid, v in code_index.items() if v["group"] == g]
        items.sort(key=lambda x: (x[1]["subgroup"], x[1]["name"]))
        return items

    def render_visible_checkbox_group(
        label: str,
        options: List[str],
        defaults: List[str],
        key_prefix: str,
        *,
        columns: int = 2,
        format_func: Optional[Callable[[str], str]] = None,
    ) -> List[str]:
        st.markdown(f"**{label}**")
        selected: List[str] = []
        col_count = max(1, min(columns, len(options) or 1))
        cols = st.columns(col_count)
        default_set = set(defaults)
        for idx, option in enumerate(options):
            with cols[idx % col_count]:
                checked = st.checkbox(
                    format_func(option) if format_func else option,
                    value=option in default_set,
                    key=f"{key_prefix}_{idx}",
                )
            if checked:
                selected.append(option)
        return selected

    qa_id = item["qa_id"]
    legacy_confidence = max(1, min(5, parse_annotation_int(existing.get("confidence"), 3)))
    existing_code_confidences = parse_code_confidences(
        str(existing.get("code_confidences", "")) if existing else ""
    )
    for code_id in existing_code_ids:
        existing_code_confidences.setdefault(code_id, legacy_confidence)
    existing_code_comments = parse_code_comments(
        str(existing.get("code_comments", "")) if existing else ""
    )
    existing_annotation_confidences = parse_annotation_confidences(
        str(existing.get("annotation_confidences", "")) if existing else ""
    )
    existing_annotation_comments = parse_annotation_comments(
        str(existing.get("annotation_comments", "")) if existing else ""
    )

    selected_code_ids: List[str] = []
    selected_code_confidences: Dict[str, int] = {}
    selected_code_comments: Dict[str, str] = {}
    selected_annotation_confidences: Dict[str, int] = {}
    selected_annotation_comments: Dict[str, str] = {}

    def widget_key(prefix: str, mark_id: str) -> str:
        safe_mark_id = re.sub(r"[^A-Za-z0-9_]+", "_", mark_id).strip("_")
        return f"{prefix}_{qa_id}_{safe_mark_id[:90]}"

    def render_feedback_header() -> None:
        h_label, h_conf, h_comment = st.columns([4.5, 2.6, 3.2])
        with h_label:
            st.markdown("**Answer Marking**")
        with h_conf:
            st.markdown("**Coding Confidence**")
        with h_comment:
            st.markdown("**Comment**")

    def render_mark_confidence(mark_id: str, *, enabled: bool = True) -> int:
        default_score = max(1, min(5, existing_annotation_confidences.get(mark_id, legacy_confidence)))
        return int(
            st.radio(
                "Coding Confidence",
                options=[1, 2, 3, 4, 5],
                index=default_score - 1,
                horizontal=True,
                format_func=lambda score: str(score),
                key=widget_key("mark_conf", mark_id),
                disabled=not enabled,
                label_visibility="collapsed",
            )
        )

    def render_mark_comment(mark_id: str, *, enabled: bool = True) -> str:
        return st.text_input(
            "Comment",
            value=existing_annotation_comments.get(mark_id, ""),
            key=widget_key("mark_comment", mark_id),
            disabled=not enabled,
            placeholder="Optional note about this marking",
            label_visibility="collapsed",
        )

    def record_mark_feedback(mark_id: str, confidence_score: int, comment: str, *, enabled: bool = True) -> None:
        if not enabled:
            return
        selected_annotation_confidences[mark_id] = int(confidence_score)
        if comment.strip():
            selected_annotation_comments[mark_id] = comment.strip()

    def render_marking_checkbox_row(
        *,
        mark_id: str,
        label: str,
        default: bool,
        key: str,
    ) -> bool:
        mark_col, conf_col, comment_col = st.columns([4.5, 2.6, 3.2], vertical_alignment="top")
        with mark_col:
            checked = st.checkbox(label, value=default, key=key)
        with conf_col:
            score = render_mark_confidence(mark_id, enabled=checked)
        with comment_col:
            comment = render_mark_comment(mark_id, enabled=checked)
        record_mark_feedback(mark_id, score, comment, enabled=checked)
        return checked

    def render_marking_checkbox_group(
        label: str,
        options: List[str],
        defaults: List[str],
        key_prefix: str,
        mark_prefix: str,
        *,
        format_func: Optional[Callable[[str], str]] = None,
    ) -> List[str]:
        st.markdown(f"**{label}**")
        render_feedback_header()
        selected: List[str] = []
        default_set = set(defaults)
        for idx, option in enumerate(options):
            checked = render_marking_checkbox_row(
                mark_id=f"{mark_prefix}:{option}",
                label=format_func(option) if format_func else option,
                default=option in default_set,
                key=f"{key_prefix}_{idx}",
            )
            if checked:
                selected.append(option)
        return selected

    if not SIMPLE_LABELING_MODE:
        st.markdown('<div class="section-card card-step">', unsafe_allow_html=True)

    for group in groups_list:
        st.markdown(f"### {group}")
        for subgroup in subgroups_in(group):
            st.markdown(f"**{subgroup}**")
            for code_id, meta in codes_in(group, subgroup):
                checked_default = code_id in existing_code_ids
                conf_default = max(1, min(5, existing_code_confidences.get(code_id, 3)))
                comment_default = existing_code_comments.get(code_id, "")
                select_col, text_col, conf_col, comment_col = st.columns([0.6, 4.4, 1.7, 2.4], vertical_alignment="center")
                with select_col:
                    checked = st.checkbox(
                        "Select code",
                        value=checked_default,
                        key=f"code_select_{qa_id}_{code_id}",
                        label_visibility="collapsed",
                    )
                with text_col:
                    render_html_markdown(
                        f'<div class="code-option-row">'
                        f'<div class="code-option-label">{html_module.escape(meta["name"])}</div>'
                        f'<div class="code-option-meta">{html_module.escape(meta["subgroup"])} · {html_module.escape(code_id)}</div>'
                        f'<div class="code-option-definition">{html_module.escape(meta["definition"])}</div>'
                        f'</div>'
                    )
                with conf_col:
                    score = st.selectbox(
                        "Coding Confidence",
                        options=[1, 2, 3, 4, 5],
                        index=conf_default - 1,
                        format_func=confidence_short_label,
                        key=f"code_confidence_{qa_id}_{code_id}",
                        disabled=not checked,
                    )
                with comment_col:
                    comment = st.text_input(
                        "Comment",
                        value=comment_default,
                        key=f"code_comment_{qa_id}_{code_id}",
                        disabled=not checked,
                        placeholder="Optional comment",
                    )
                if checked:
                    selected_code_ids.append(code_id)
                    selected_code_confidences[code_id] = int(score)
                    if comment.strip():
                        selected_code_comments[code_id] = comment.strip()

    if not SIMPLE_LABELING_MODE:
        st.markdown("</div>", unsafe_allow_html=True)

    if SIMPLE_LABELING_MODE:
        is_other = False
        other_reason = ""
    else:
        st.markdown('<div class="section-card card-other">', unsafe_allow_html=True)
        is_other = st.checkbox(
            "Other (this Q&A does not fit the available taxonomy)",
            value=existing_is_other,
            key=f"is_other_{qa_id}",
        )
        default_reason = str(existing.get("other_reason", "")) if existing else ""
        other_reason = st.text_area(
            "Other Reason (required only when 'Other' is checked)",
            value=default_reason,
            height=100,
            disabled=not is_other,
            key=f"other_reason_{qa_id}",
        )
        st.markdown("</div>", unsafe_allow_html=True)

    # Theory-guided coding scales (always-visible definitions panels)
    st.markdown('<div class="section-card card-step">', unsafe_allow_html=True)
    render_primary_hierarchy_panel()
    default_primary = parse_annotation_int(existing.get("primary_hierarchy"), 0)
    default_primary = max(0, min(4, default_primary))
    primary_options = primary_levels_for_display()
    primary_hierarchy_raw = st.radio(
        "Primary Hierarchy (0–4): Language Maturity Level",
        options=[0, 1, 2, 3, 4],
        index=default_primary if has_existing_annotation or not SIMPLE_LABELING_MODE else None,
        horizontal=True,
        format_func=(
            lambda x: f"{x} — {primary_options[x]['title']} ({primary_options[x]['definition']})"
            if SIMPLE_LABELING_MODE
            else f"{x} — {primary_options[x]['title']}"
        ),
        key=f"primary_hierarchy_{qa_id}",
        help=None if SIMPLE_LABELING_MODE else "0 = no contingency-relevant language; 4 = explicit self-generated rule.",
    )
    primary_hierarchy = int(primary_hierarchy_raw) if primary_hierarchy_raw is not None else -1
    if SIMPLE_LABELING_MODE:
        p_label, p_conf, p_comment = st.columns([4.5, 2.6, 3.2], vertical_alignment="top")
        primary_mark_id = "primary_hierarchy"
        if primary_hierarchy_raw is None:
            with p_label:
                st.info("Select one Primary Hierarchy level for the Answer before saving.")
        else:
            with p_label:
                st.markdown(
                    f"<div class='marking-selected-note'><b>Selected Primary:</b> "
                    f"{primary_hierarchy} — {html_module.escape(primary_options[primary_hierarchy]['title'])}</div>",
                    unsafe_allow_html=True,
                )
            with p_conf:
                primary_confidence = render_mark_confidence(primary_mark_id)
            with p_comment:
                primary_comment = render_mark_comment(primary_mark_id)
            record_mark_feedback(primary_mark_id, primary_confidence, primary_comment)

    render_secondary_components_panel()
    component_defs = secondary_components_for_display()
    default_ctx = parse_annotation_bool(existing.get("component_context"))
    default_beh = parse_annotation_bool(existing.get("component_behavior"))
    default_con = parse_annotation_bool(existing.get("component_consequence"))
    default_rule = parse_annotation_bool(existing.get("component_rule"))

    def component_label(component: dict) -> str:
        if SIMPLE_LABELING_MODE:
            return f"{component['name']} ({component['definition']})"
        return component["name"]

    if SIMPLE_LABELING_MODE:
        st.markdown("**Components**")
        render_feedback_header()
        component_context = render_marking_checkbox_row(
            mark_id="component_context",
            label=component_label(component_defs[0]),
            default=default_ctx,
            key=f"component_context_{qa_id}",
        )
        component_behavior = render_marking_checkbox_row(
            mark_id="component_behavior",
            label=component_label(component_defs[1]),
            default=default_beh,
            key=f"component_behavior_{qa_id}",
        )
        component_consequence = render_marking_checkbox_row(
            mark_id="component_consequence",
            label=component_label(component_defs[2]),
            default=default_con,
            key=f"component_consequence_{qa_id}",
        )
        component_rule = render_marking_checkbox_row(
            mark_id="component_rule",
            label=component_label(component_defs[3]),
            default=default_rule,
            key=f"component_rule_{qa_id}",
        )
    else:
        c_ctx, c_beh, c_con, c_rule = st.columns(4)
        with c_ctx:
            component_context = st.checkbox("Context", value=default_ctx, help=component_defs[0]["definition"])
        with c_beh:
            component_behavior = st.checkbox("Behavior", value=default_beh, help=component_defs[1]["definition"])
        with c_con:
            component_consequence = st.checkbox("Consequence", value=default_con, help=component_defs[2]["definition"])
        with c_rule:
            component_rule = st.checkbox("Rule", value=default_rule, help=component_defs[3]["definition"])

    secondary_component_score = (
        int(component_context)
        + int(component_behavior)
        + int(component_consequence)
        + int(component_rule)
    )
    if not SIMPLE_LABELING_MODE:
        st.markdown(
            f"**Contingency Component Score (also called Secondary Component Score, 0–4):** "
            f"`{secondary_component_score}`"
        )
    st.markdown("</div>", unsafe_allow_html=True)

    # Rule taxonomy fields (shown when rule component checked OR Primary >= 3)
    show_rule_taxonomy = component_rule or primary_hierarchy >= 3
    default_rule_sources = parse_delimited_options(
        str(existing.get("rule_source", "")) if existing else "",
        RULE_SOURCE_OPTIONS,
    )
    default_behavior_forms = parse_delimited_options(
        str(existing.get("behavior_form", "")) if existing else "",
        BEHAVIOR_FORM_OPTIONS,
    )

    st.markdown('<div class="section-card card-info">', unsafe_allow_html=True)
    st.markdown(
        "**Rule Taxonomy (complete when the Answer supports Rule or Primary >= 3)**  \n"
        "_Source_ tells you where the Answer says the rule came from. "
        "_Behavior Form_ tells you whether the Answer describes behavior already happening or a stated future intention."
    )
    if show_rule_taxonomy:
        if SIMPLE_LABELING_MODE:
            selected_rule_sources = render_marking_checkbox_group(
                "Rule Source",
                [option for option in RULE_SOURCE_OPTIONS if option != "N/A"],
                default_rule_sources,
                f"rule_source_{qa_id}",
                "rule_source",
                format_func=lambda option: f"{option} ({RULE_SOURCE_DEFINITIONS.get(option, '')})",
            )
            selected_behavior_forms = render_marking_checkbox_group(
                "Behavior Form",
                [option for option in BEHAVIOR_FORM_OPTIONS if option != "N/A"],
                default_behavior_forms,
                f"behavior_form_{qa_id}",
                "behavior_form",
                format_func=lambda option: f"{option} ({BEHAVIOR_FORM_DEFINITIONS.get(option, '')})",
            )
        else:
            rs_col, bf_col = st.columns(2)
            with rs_col:
                selected_rule_sources = render_visible_checkbox_group(
                    "Rule Source",
                    [option for option in RULE_SOURCE_OPTIONS if option != "N/A"],
                    default_rule_sources,
                    f"rule_source_{qa_id}",
                    columns=1,
                    format_func=lambda option: f"{option} ({RULE_SOURCE_DEFINITIONS.get(option, '')})",
                )
            with bf_col:
                selected_behavior_forms = render_visible_checkbox_group(
                    "Behavior Form",
                    [option for option in BEHAVIOR_FORM_OPTIONS if option != "N/A"],
                    default_behavior_forms,
                    f"behavior_form_{qa_id}",
                    columns=1,
                    format_func=lambda option: f"{option} ({BEHAVIOR_FORM_DEFINITIONS.get(option, '')})",
                )
        rule_source = join_delimited_options(selected_rule_sources, RULE_SOURCE_OPTIONS)
        behavior_form = join_delimited_options(selected_behavior_forms, BEHAVIOR_FORM_OPTIONS)
    else:
        st.caption("This Answer does not require rule-taxonomy fields (Primary < 3 and Rule unchecked). Defaults to N/A.")
        rule_source = "N/A"
        behavior_form = "N/A"
    st.markdown("</div>", unsafe_allow_html=True)

    # Evidence + per-item note
    st.markdown('<div class="section-card card-info">', unsafe_allow_html=True)
    if not SIMPLE_LABELING_MODE:
        st.markdown("**Coding Confidence**")
        confidence = st.radio(
            "Coding Confidence",
            options=[1, 2, 3, 4, 5],
            index=legacy_confidence - 1,
            horizontal=True,
            format_func=confidence_option_label,
            key=f"overall_confidence_{qa_id}",
            help=CONFIDENCE_HELP,
        )
    st.markdown("**Answer Evidence and Notes**")
    evidence_help = (
        "Paste the shortest exact phrase or sentence(s) from the Answer that justify the Primary score. "
        "This supports adjudication and later LLM comparison."
    )
    default_evidence_span = str(existing.get("evidence_span", "")) if existing else ""
    if SIMPLE_LABELING_MODE:
        st.caption(
            "Click the sentence(s) in the Answer that show your score — no typing or copying needed "
            "(required for Primary 2–4)."
        )
        answer_text = str(item.get("answer_en") or item.get("answer") or "").strip()
        sentence_options = split_into_sentences(answer_text)
        if sentence_options:
            preselected = [s for s in sentence_options if s and s in default_evidence_span]
            picked = st.multiselect(
                "Which part of the Answer shows this?",
                options=sentence_options,
                default=preselected,
                key=f"evidence_pick_{qa_id}",
            )
            manual_default = default_evidence_span if (default_evidence_span and not preselected) else ""
            with st.expander("Or type / edit the wording yourself (optional)", expanded=bool(manual_default)):
                manual_evidence = st.text_area(
                    "Evidence span (optional manual entry)",
                    value=manual_default,
                    height=70,
                    key=f"evidence_span_{qa_id}",
                )
            evidence_span = " ".join(picked).strip() or manual_evidence.strip()
        else:
            evidence_span = st.text_area(
                "Which part of the Answer shows this? (required for Primary 2–4)",
                value=default_evidence_span,
                height=80,
                key=f"evidence_span_{qa_id}",
            )
    else:
        evidence_span = st.text_area(
            "Answer Evidence Span / Meaning Unit (required for Primary 2–4)",
            value=default_evidence_span,
            height=80,
            key=f"evidence_span_{qa_id}",
            help=evidence_help,
        )
    default_issue_flags = parse_issue_flags(str(existing.get("issue_flags", "")) if existing else "")
    issue_flag_options = (
        [flag for flag in ISSUE_FLAG_OPTIONS if "CGM" not in flag]
        if SIMPLE_LABELING_MODE
        else ISSUE_FLAG_OPTIONS
    )
    default_issue_flags = [flag for flag in default_issue_flags if flag in issue_flag_options]
    if SIMPLE_LABELING_MODE:
        issue_flags = render_marking_checkbox_group(
            "Ambiguity / Review Flags",
            issue_flag_options,
            default_issue_flags,
            f"issue_flags_{qa_id}",
            "issue_flag",
        )
        confidence = min(selected_annotation_confidences.values()) if selected_annotation_confidences else legacy_confidence
    else:
        issue_flags = st.multiselect(
            "Ambiguity / Review Flags",
            options=issue_flag_options,
            default=default_issue_flags,
            key=f"issue_flags_{qa_id}",
            help="Optional structured flags for calibration and adjudication.",
        )
    default_note = str(existing.get("meaning_unit_note", "")) if existing else ""
    meaning_unit_note = st.text_area(
        "Coder Note about this Answer (optional, especially helpful for ambiguous cases)",
        value=default_note,
        height=80,
        key=f"meaning_unit_note_{qa_id}",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    show_full_cgm, full_cgm_reason = (
        (False, "")
        if SIMPLE_LABELING_MODE
        else is_cgm_relevant_for_coding(
            selected_code_ids=selected_code_ids,
            code_index=code_index,
            primary_hierarchy=primary_hierarchy,
            component_context=component_context,
            component_behavior=component_behavior,
            component_consequence=component_consequence,
            component_rule=component_rule,
            qa_text=qa_text,
            always_show=always_show_cgm,
        )
    )
    if show_full_cgm or show_early_cgm:
        render_cgm_coding_context_summary(
            item["subject_id"],
            reason=full_cgm_reason if show_full_cgm else early_cgm_reason,
            qa_text=qa_text,
            selected_code_ids=selected_code_ids,
            code_index=code_index,
            confidence=confidence,
            show_table=not show_early_cgm,
            show_extras=True,
            extras_only=show_early_cgm,
            theme=theme,
        )

    def validate() -> Optional[str]:
        if primary_hierarchy < 0:
            return "Please select one Primary Hierarchy level for the Answer before saving."
        if not SIMPLE_LABELING_MODE and not selected_code_ids and not is_other:
            return "Please select at least one code, or check 'Other' and provide a reason."
        if not SIMPLE_LABELING_MODE and selected_code_ids and is_other:
            return "Use either selected code(s) or 'Other', not both."
        if is_other and not other_reason.strip():
            return "You checked 'Other'. Please provide a reason."
        if primary_hierarchy >= 2 and not evidence_span.strip():
            return "Please select (or type) the part of the Answer that supports your Primary 2–4 score."
        if primary_hierarchy >= 3 and not component_rule:
            return "Primary 3–4 requires the Rule component because it indicates future-oriented self-guidance."
        selected_rule_sources = parse_delimited_options(rule_source, RULE_SOURCE_OPTIONS)
        selected_behavior_forms = parse_delimited_options(behavior_form, BEHAVIOR_FORM_OPTIONS)
        if show_rule_taxonomy and not selected_rule_sources:
            return "Rule Source is required when the Answer supports Primary >= 3 or the Rule component is checked. Use Mixed/Unclear if needed."
        if show_rule_taxonomy and not selected_behavior_forms:
            return "Behavior Form is required when the Answer supports Primary >= 3 or the Rule component is checked."
        if primary_hierarchy == 4 and "Self-generated" not in selected_rule_sources:
            return "Primary 4 requires Rule Source = Self-generated because the Answer must show the rule came from the participant's own experience."
        return None

    def warn_if_adjudication_without_note() -> None:
        computed = (
            pd.DataFrame()
            if SIMPLE_LABELING_MODE
            else enrich_computed_with_phase(get_cgm_computed_for_subject(item["subject_id"]))
        )
        mismatch = compute_cgm_mismatch_message(qa_text, computed) if not computed.empty else None
        flagged, adj_reason = is_adjudication_candidate(
            confidence,
            mismatch_message=mismatch,
        )
        if flagged and not meaning_unit_note.strip():
            st.warning(
                f"Adjudication candidate ({adj_reason}). Consider adding a coder note before saving."
            )

    st.markdown('<div class="section-card card-save">', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save", type="primary", width="stretch"):
            err = validate()
            if err:
                st.error(err)
            else:
                warn_if_adjudication_without_note()
                save_annotation(
                    item,
                    selected_code_ids,
                    selected_code_confidences,
                    selected_code_comments,
                    is_other,
                    other_reason,
                    primary_hierarchy,
                    component_context,
                    component_behavior,
                    component_consequence,
                    component_rule,
                    rule_source,
                    behavior_form,
                    confidence,
                    selected_annotation_confidences,
                    selected_annotation_comments,
                    evidence_span,
                    issue_flags,
                    meaning_unit_note,
                    user.get("display_name", user["username"]),
                    user["username"],
                )
                st.success("Saved.")
                st.cache_data.clear()
                st.rerun()
    with c2:
        if st.button("Save and Next", width="stretch"):
            err = validate()
            if err:
                st.error(err)
            else:
                warn_if_adjudication_without_note()
                save_annotation(
                    item,
                    selected_code_ids,
                    selected_code_confidences,
                    selected_code_comments,
                    is_other,
                    other_reason,
                    primary_hierarchy,
                    component_context,
                    component_behavior,
                    component_consequence,
                    component_rule,
                    rule_source,
                    behavior_form,
                    confidence,
                    selected_annotation_confidences,
                    selected_annotation_comments,
                    evidence_span,
                    issue_flags,
                    meaning_unit_note,
                    user.get("display_name", user["username"]),
                    user["username"],
                )
                st.cache_data.clear()
                _go_next()
    st.markdown("</div>", unsafe_allow_html=True)

    if not SIMPLE_LABELING_MODE:
        st.divider()
        st.markdown("### Participant Context")
        st.caption(
            "Reference for this subject — demographics and full CGM charts stay the same as you move between Q/A items. "
            "When an item is CGM-relevant, a **CGM Summary for Coding** appears below the Q/A (and coding notes after confidence). "
            "Use the sidebar **Always show CGM summary** toggle if you want it on every item."
        )
        render_participant_context_panel(cur_subj, theme, compact=False)


def render_training_golden_rules() -> None:
    render_html_markdown(
        '<div class="section-card card-answer">'
        '<div class="instruction-step-title">Answer only</div>'
        '<div class="instruction-step-body">Score the <strong>Answer</strong> text — never the Question, never your guess.</div>'
        '</div>'
        '<div class="section-card card-question">'
        '<div class="instruction-step-title">No inference</div>'
        '<div class="instruction-step-body">If it is not written in the Answer, it does not count.</div>'
        '</div>'
        '<div class="section-card card-save">'
        '<div class="instruction-step-title">Question = context</div>'
        '<div class="instruction-step-body">The Question tells you what they were asked about — use it only for context.</div>'
        '</div>'
    )


def render_training_score_ruler() -> None:
    rows: List[str] = []
    for num, color, title, hint in TRAINING_SCORE_RULER:
        rows.append(
            '<div class="score-ruler-row">'
            f'<span class="score-badge" style="background:{color};">{num}</span>'
            '<div>'
            f'<span class="score-ruler-title">{html_module.escape(title)}</span> '
            f'<span class="score-ruler-hint">— {html_module.escape(hint)}</span>'
            "</div></div>"
        )
    render_html_markdown(f'<div class="section-card card-info score-ruler-card">{"".join(rows)}</div>')
    st.caption(TRAINING_MEMORY_HOOK)


def render_training_field_references() -> None:
    with st.expander("Primary Hierarchy (0–4)", expanded=False):
        for lv in primary_levels_for_display():
            render_html_markdown(
                f'<div class="level-card">'
                f'<b>{html_module.escape(str(lv["level"]))} · {html_module.escape(lv["title"])}</b><br/>'
                f'{html_module.escape(lv["definition"])}<br/>'
                f'<i>Example:</i> {html_module.escape(lv["example"])}'
                f'</div>'
            )

    with st.expander("Components (Context · Behavior · Consequence · Rule)", expanded=False):
        for component in secondary_components_for_display():
            render_html_markdown(
                f'<div class="level-card">'
                f'<b>{html_module.escape(component["name"])}</b><br/>'
                f'{html_module.escape(component["definition"])}<br/>'
                f'<i>Example:</i> {html_module.escape(component["example"])}'
                f'</div>'
            )

    with st.expander("Rule Source (when a rule is present)", expanded=False):
        st.caption("Use N/A when there is no rule. Primary 4 should usually be Self-generated.")
        render_html_markdown(
            '<div class="level-card"><b>N/A</b><br/>No behavior-guiding rule in the Answer.</div>'
        )
        for name, definition in RULE_SOURCE_DEFINITIONS.items():
            render_html_markdown(
                f'<div class="level-card">'
                f'<b>{html_module.escape(name)}</b><br/>'
                f'{html_module.escape(definition)}.'
                f'</div>'
            )

    with st.expander("Behavior Form (when a rule is present)", expanded=False):
        st.caption("Has a diet or exercise change started, or is it only planned?")
        render_html_markdown(
            '<div class="level-card"><b>N/A</b><br/>No behavior-guiding rule in the Answer.</div>'
        )
        for name, definition in BEHAVIOR_FORM_DEFINITIONS.items():
            render_html_markdown(
                f'<div class="level-card">'
                f'<b>{html_module.escape(name)}</b><br/>'
                f'{html_module.escape(definition)}.'
                f'</div>'
            )


def render_test_drive_item_feedback(item: dict, idx: int, user_primary: Optional[int]) -> None:
    levels = primary_levels_for_display()
    expected = item["expected_primary"]
    correct = user_primary == expected
    expected_meta = levels[expected]
    if user_primary is None:
        user_label = "Not selected"
    else:
        user_label = f"{user_primary} — {levels[user_primary]['title']}"
    card_class = "card-save" if correct else "card-other"
    status = "Correct" if correct else "Review"
    steps = item.get("explanation_steps") or [item.get("rationale", "")]
    steps_html = "".join(
        f'<div class="instruction-step-body">{step}</div>' for step in steps
    )
    render_html_markdown(
        f'<div class="section-card {card_class}">'
        f'<div class="instruction-step-title">Answer key · {status}</div>'
        f'<div class="instruction-step-body"><strong>Your choice:</strong> '
        f"{html_module.escape(user_label)}</div>"
        f'<div class="instruction-step-body"><strong>Correct Primary:</strong> '
        f"{expected} — {html_module.escape(expected_meta['title'])}</div>"
        f"{steps_html}"
        f"</div>"
    )


def page_simple_labeling_training(user: dict) -> None:
    if st.session_state.get("user"):
        user = st.session_state.user
    st.header("Initial Training")
    st.caption("Practice pass · complete the Test Drive to unlock Step 4 · Score Answers.")

    training_done = simple_training_is_complete(user)
    if training_done:
        ts = user.get("simple_training_completed_at_utc") or "previously"
        st.success(f"Training complete ({ts}). You may review references or retake the Test Drive anytime.")
    else:
        st.warning("Submit the Test Drive below to unlock real Answer scoring.")

    st.subheader("Where you are")
    st.markdown(TRAINING_PAGE_LEDE)
    if not training_done:
        st.caption("Need the full study story or worked examples? Go back to **Step 1 · Introduction**.")

    st.subheader("Three rules")
    render_training_golden_rules()

    st.subheader("Primary score at a glance")
    render_training_score_ruler()

    st.subheader("Pocket references")
    st.caption("Collapsed cheat sheets — open only when the Test Drive item is unclear.")
    render_training_field_references()

    st.divider()
    st.subheader("Test Drive")
    st.markdown(
        "Score **Primary only** on four clear practice items (0, 2, 3, and 4). After you submit, the "
        "**answer key and explanation appear under each item** — adjust any **Review** items and submit "
        "again until all four match. Primary **1** is in **Step 1 · Introduction**; here we focus on "
        "**3 vs 4**."
    )
    test_drive_items = simple_test_drive_items()
    primary_options = [0, 1, 2, 3, 4]
    show_feedback = bool(st.session_state.get("test_drive_show_feedback"))
    stored_answers: Dict[str, Optional[int]] = st.session_state.get("test_drive_answers") or {}

    if st.session_state.pop("test_drive_miss_message", False):
        st.error(
            "Almost there — items marked **Review** below need another look. "
            "Read the explanation under each one, adjust your score, and submit again."
        )
    if st.session_state.pop("test_drive_pass_message", False):
        st.success("Test Drive passed. Initial Training complete; **Step 4 · Score Answers** is now unlocked.")
        st.balloons()

    for idx, item in enumerate(test_drive_items, start=1):
        st.markdown(f"#### Item {idx}")
        render_html_markdown(
            f'<div class="section-card card-question">'
            f'<span class="qa-label">Question:</span> {html_module.escape(item["question"])}'
            f'</div>'
            f'<div class="section-card card-answer">'
            f'<span class="qa-label">Answer:</span> {html_module.escape(item["answer"])}'
            f'</div>'
        )
        st.radio(
            "Primary Hierarchy",
            options=primary_options,
            index=None,
            horizontal=True,
            format_func=lambda x: f"{x} - {primary_levels_for_display()[x]['title']}",
            key=f"training_primary_{item['id']}",
        )
        if show_feedback:
            render_test_drive_item_feedback(
                item,
                idx,
                stored_answers.get(item["id"], st.session_state.get(f"training_primary_{item['id']}")),
            )
        st.divider()

    submitted = st.button("Submit Test Drive", type="primary", width="stretch")

    if not submitted:
        return

    submitted_answers: Dict[str, Optional[int]] = {
        item["id"]: st.session_state.get(f"training_primary_{item['id']}") for item in test_drive_items
    }
    misses: List[str] = []
    unanswered = 0
    for idx, item in enumerate(test_drive_items, start=1):
        primary = submitted_answers[item["id"]]
        if primary is None:
            unanswered += 1
            continue
        if primary != item["expected_primary"]:
            misses.append(
                f"Item {idx}: this Answer is a clear Primary {item['expected_primary']} "
                f"({primary_levels_for_display()[item['expected_primary']]['title']}). {item['rationale']}"
            )

    if unanswered:
        st.session_state.test_drive_show_feedback = False
        st.warning(f"Please select a Primary Hierarchy level for all {len(test_drive_items)} items.")
        return

    st.session_state.test_drive_show_feedback = True
    st.session_state.test_drive_answers = submitted_answers
    persist_user_session(user.get("username"))

    if misses:
        st.session_state.test_drive_miss_message = True
        st.rerun()

    if not training_done:
        mark_simple_training_completed(user["username"])
    persist_user_session(user["username"])
    st.session_state.test_drive_pass_message = True
    st.rerun()


def page_my_stats(user: dict) -> None:
    st.header("My Progress")
    annotations_df = load_annotations()
    check_samples = check_sample_map()
    admin = user_is_admin(user)
    if annotations_df.empty:
        st.info("No saved scores yet.")
        return
    mine_df = annotations_df[annotations_df["coder_username"] == user["username"]].copy()
    st.write(f"Total saved by you: **{len(mine_df)}**")

    if mine_df.empty:
        return

    if admin:
        qa_items = build_qa_items()
        user_ann_map = {
            str(row["qa_id"]): row.to_dict()
            for _, row in mine_df.iterrows()
            if str(row.get("qa_id", ""))
        }
        adjudication_rows: List[pd.DataFrame] = []
        for subject_id in sorted(mine_df["subject_id"].unique()):
            subject_adj = build_adjudication_candidates(subject_id, qa_items, user_ann_map)
            if not subject_adj.empty:
                subject_adj.insert(0, "Subject", subject_id)
                adjudication_rows.append(subject_adj)
        adjudication_all = (
            pd.concat(adjudication_rows, ignore_index=True) if adjudication_rows else pd.DataFrame()
        )

        st.subheader("Adjudication Queue")
        if adjudication_all.empty:
            st.caption("No items flagged for adjudication in your saved scores.")
        else:
            st.caption("Flagged when confidence is 1–2.")
            st.dataframe(adjudication_all, width="stretch", hide_index=True)

        if check_samples:
            st.subheader("Check Sample Agreement")
            check_rows = []
            for qa_id, expected in check_samples.items():
                ann = user_ann_map.get(qa_id)
                if ann:
                    check_rows.append(compare_annotation_to_check_sample(ann, expected))
            if not check_rows:
                st.caption("You have not reached any hidden check samples yet.")
            else:
                check_df = pd.DataFrame(check_rows)
                matched = int(check_df["primary_match"].sum())
                total_checks = len(check_df)
                st.write(f"Primary agreement on hidden check samples: **{matched}/{total_checks}**")

                attention_df = check_df[check_df["is_attention_check"]]
                attention_reached = len(attention_df)
                if attention_reached:
                    attention_passed = int(attention_df["primary_match"].sum())
                    attention_accuracy = attention_passed / attention_reached
                    st.write(
                        f"Attention checks passed: **{attention_passed}/{attention_reached}** "
                        f"({attention_accuracy * 100:.0f}%)"
                    )
                    if (
                        attention_reached >= ATTENTION_CHECK_MIN_REACHED
                        and attention_accuracy < ATTENTION_CHECK_PASS_THRESHOLD
                    ):
                        st.warning(
                            "Your accuracy on the clear attention-check items is below "
                            f"{ATTENTION_CHECK_PASS_THRESHOLD * 100:.0f}%. These items have an "
                            "unambiguous answer — please slow down and read each Answer carefully."
                        )

                st.dataframe(
                    check_df.rename(
                        columns={
                            "qa_id": "Item ID",
                            "subject_id": "Subject",
                            "saved_primary": "Your Primary",
                            "expected_primary": "Expected Primary",
                            "primary_match": "Primary Match",
                            "component_matches": "Component Matches",
                            "components_all_match": "All Components Match",
                            "rule_source_match": "Rule Source Match",
                            "behavior_form_match": "Behavior Form Match",
                            "rule_taxonomy_expected": "Rule Taxonomy Expected",
                            "is_attention_check": "Attention Check",
                            "attention_check_pass": "Attention Check Pass",
                            "rationale": "Rationale",
                        }
                    ),
                    width="stretch",
                    hide_index=True,
                )

    by_subject = (
        mine_df.groupby("subject_id")["qa_id"].count().reset_index().rename(columns={"qa_id": "count"})
    )
    by_primary = (
        mine_df.groupby("primary_hierarchy")["qa_id"].count().reset_index().rename(columns={"qa_id": "count"})
    )
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("By Subject")
        st.dataframe(by_subject, width="stretch", hide_index=True)
    with c2:
        st.subheader("By Primary Hierarchy")
        st.dataframe(by_primary, width="stretch", hide_index=True)

    st.subheader("Recent Saved Scores")
    cols = [
        "qa_id",
        "subject_id",
        "primary_hierarchy",
        "secondary_component_score",
        "rule_source",
        "behavior_form",
        "confidence",
        "code_confidences",
        "evidence_span",
        "issue_flags",
        "selected_code_ids",
        "is_other",
        "updated_at_utc",
    ]
    st.dataframe(
        mine_df[cols].sort_values("updated_at_utc", ascending=False).head(50),
        width="stretch",
        hide_index=True,
    )


def page_agreement_dashboard(user: dict) -> None:
    st.header("Quality & Agreement")
    st.caption(
        "Recommended read: use Primary QWK as the main inter-rater agreement metric because "
        "Primary Hierarchy is ordinal from 0-4. Exact agreement is shown beside it for an "
        "easy face-valid check. Kappa can be N/A when there is no score variation or too little overlap."
    )

    annotations_df = load_annotations()
    users = load_users()
    check_samples = check_sample_map()
    ready_df = agreement_ready_annotations(annotations_df)
    username = str(user.get("username", "")).strip().lower()

    if ready_df.empty:
        st.info("No saved scores yet, so agreement cannot be calculated.")
        return

    coder_count = ready_df["coder_username"].nunique()
    item_count = ready_df["qa_id"].nunique()
    total_saved = len(ready_df)
    c1, c2, c3 = st.columns(3)
    c1.metric("Saved Scores", total_saved)
    c2.metric("Coders With Scores", coder_count)
    c3.metric("Unique Q/A Items", item_count)

    pairwise_df = build_pairwise_agreement_table(ready_df)
    check_summary_df = build_check_sample_agreement_table(ready_df, check_samples)

    st.subheader("Your Agreement")
    my_saved = ready_df[ready_df["coder_username"] == username]
    st.write(f"Total saved by you: **{len(my_saved)}**")

    if check_samples:
        st.markdown("**Your Hidden Check Sample Performance**")
        my_check = (
            check_summary_df[check_summary_df["coder"] == username]
            if not check_summary_df.empty
            else pd.DataFrame()
        )
        if my_check.empty or int(my_check.iloc[0]["check_samples_reached"]) == 0:
            st.caption("You have not reached any hidden check samples yet.")
        else:
            formatted_my_check = format_check_sample_agreement_table(my_check, users)
            st.dataframe(formatted_my_check, width="stretch", hide_index=True)
            detail_df = user_check_sample_details(ready_df, check_samples, username)
            if not detail_df.empty:
                st.dataframe(
                    detail_df.rename(
                        columns={
                            "qa_id": "Item ID",
                            "subject_id": "Subject",
                            "saved_primary": "Your Primary",
                            "expected_primary": "Expected Primary",
                            "primary_match": "Primary Match",
                            "component_matches": "Component Matches",
                            "components_all_match": "All Components Match",
                            "rule_source_match": "Rule Source Match",
                            "behavior_form_match": "Behavior Form Match",
                            "rationale": "Gold Rationale",
                        }
                    ),
                    width="stretch",
                    hide_index=True,
                )
    else:
        st.caption("No hidden check sample key is available.")

    st.markdown("**Your Pairwise Agreement With Other Coders**")
    if pairwise_df.empty:
        st.caption("No overlapping scores between coders yet.")
    else:
        my_pairs = pairwise_df[
            (pairwise_df["coder_a"] == username) | (pairwise_df["coder_b"] == username)
        ].copy()
        if my_pairs.empty:
            st.caption("You do not yet overlap with another coder on the same Q/A item.")
        else:
            st.dataframe(
                format_pairwise_agreement_table(my_pairs, users),
                width="stretch",
                hide_index=True,
            )
            if bool(my_pairs["low_overlap"].any()):
                st.caption(
                    f"Rows with fewer than {AGREEMENT_MIN_OVERLAP} shared items should be treated as early signals, not stable estimates."
                )

    if not user_is_admin(user):
        return

    st.divider()
    st.subheader("Admin Backend")
    st.caption(
        "This section is visible to admin users. It summarizes overlap, agreement, hidden check performance, and progress."
    )

    progress_df = (
        ready_df.groupby("coder_username")
        .agg(
            saved_labels=("qa_id", "count"),
            unique_items=("qa_id", "nunique"),
            subjects=("subject_id", "nunique"),
            last_saved_utc=("updated_at_utc", "max"),
        )
        .reset_index()
    )
    progress_display = progress_df.copy()
    progress_display["Coder"] = progress_display["coder_username"].map(
        lambda coder: coder_display_label(coder, users)
    )
    progress_display = progress_display[
        ["Coder", "saved_labels", "unique_items", "subjects", "last_saved_utc"]
    ].rename(
        columns={
            "saved_labels": "Saved Scores",
            "unique_items": "Unique Q/A Items",
            "subjects": "Subjects",
            "last_saved_utc": "Last Saved UTC",
        }
    )
    st.markdown("**Coder Progress**")
    st.dataframe(progress_display, width="stretch", hide_index=True)

    st.markdown("**Primary QWK Matrix**")
    coders = sorted(ready_df["coder_username"].astype(str).unique())
    st.dataframe(build_qwk_matrix(pairwise_df, coders, users), width="stretch")

    st.markdown("**All Pairwise Agreement**")
    if pairwise_df.empty:
        st.caption("No coder pairs have overlapping scores yet.")
    else:
        st.dataframe(
            format_pairwise_agreement_table(pairwise_df, users),
            width="stretch",
            hide_index=True,
        )

    if check_samples:
        st.markdown("**Hidden Check Sample Gold Agreement**")
        if check_summary_df.empty:
            st.caption("No coder has reached a hidden check sample yet.")
        else:
            flagged = check_summary_df[check_summary_df["attention_flag"]]
            if not flagged.empty:
                flagged_labels = [
                    coder_display_label(str(row["coder"]), users)
                    for _, row in flagged.iterrows()
                ]
                st.warning(
                    "Attention-check review needed for: "
                    + ", ".join(flagged_labels)
                    + f". Primary accuracy on the clear attention checks is below "
                    f"{ATTENTION_CHECK_PASS_THRESHOLD * 100:.0f}% "
                    f"(after reaching at least {ATTENTION_CHECK_MIN_REACHED} of them)."
                )
            st.dataframe(
                format_check_sample_agreement_table(check_summary_df, users),
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "Gold accuracy compares saved scores to the embedded expected scores. "
                "It is not inter-rater agreement, but it is useful for ongoing quality control. "
                "Attention checks are the clear, unambiguous (no-contingency) items used to confirm "
                "annotators are reading carefully; the Attention Flag marks coders to review."
            )


def page_coder_training(user: Optional[dict] = None) -> None:
    st.header("Coder Training")
    st.caption(
        "This page trains coders on the functional logic behind the codes. "
        "Goal: agreement based on shared interpretation of function and controlling relations, not intuition."
    )

    if user and not user.get("training_completed", False):
        st.info(
            "You have not completed the Coder Training yet. Read through every section below, "
            "then confirm at the bottom of this page to unlock the Annotate page. "
            "For interface operations and CGM features, also see **User Manual** in the sidebar."
        )
    elif user:
        ts = user.get("training_completed_at_utc") or "previously"
        st.success(f"You completed Coder Training at: {ts}")

    st.subheader("1. Primary Hierarchy with Examples (0–4)")
    for lv in PRIMARY_LEVELS:
        st.markdown(
            f"""
            <div class="level-card">
              <b>Level {lv['level']} — {lv['title']}</b><br/>
              {lv['definition']}<br/>
              <i>Example:</i> {lv['example']}
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.subheader("2. Secondary Components (Context, Behavior, Consequence, Rule)")
    for c in SECONDARY_COMPONENTS:
        st.markdown(
            f"""
            <div class="level-card">
              <b>{c['name']}</b><br/>
              {c['definition']}<br/>
              <i>Example:</i> {c['example']}
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.subheader("3. Decision Rules When Coding Each Utterance")
    st.markdown(
        """
        1. Is a glucose-related consequence named or clearly implied?
        2. Is a behavior named or clearly implied?
        3. Is a context, timing, condition, or situation named or clearly implied?
        4. Is there evidence that later behavior changed, is changing, or is intended to change because of that consequence?
        5. If future-oriented self-guidance is present, does it appear self-generated or borrowed from another source?

        A statement should receive a higher Primary level only when justified by the language itself.
        Avoid inferring hidden cognitive states or insight when the utterance does not specify an observable contingency relation.
        Resolve ambiguous cases conservatively.
        """
    )

    st.subheader("4. Functional Categories With Sample Phrasing")
    st.markdown(
        """
        - **Descriptive tact-like language**: report of a fact or trend without linkage.
          - "It went up at noon."
          - "My sugar was 180 yesterday."
        - **Contingency recognition language**: links behavior/context to consequence.
          - "When I eat rice my sugar rises."
          - "I noticed walking after dinner keeps it flat."
        - **Emerging self-rule**: tentative or planned change.
          - "I'm trying to skip rice at night now."
          - "I think I should walk more after meals."
        - **Explicit self-generated rule**: clear self-derived rule from CGM experience.
          - "If I eat rice at night, I always spike, so I skip it."
          - "Whenever the alert goes off after a tortilla, I switch to a smaller portion next time."
        - **Borrowed rule**: external or generic source — code as **Borrowed** in Rule Source.
          - "The doctor said avoid sugar."
          - "Everyone knows you shouldn't eat carbs at night."
        - **Ambiguous case**: vague or conditional, missing key components.
          - "Maybe sometimes I notice things, I'm not sure."
          - "Yeah, I guess it depends."
        """
    )

    st.subheader("4a. Functional Principles — Do NOT rely on lexical shortcuts")
    st.markdown(
        """
        Words like **because, when, I learned, my rule is, I should** do not by themselves justify a higher Primary level.
        These phrases occur in functionally distinct utterances. Always evaluate the **relation** the utterance expresses
        and the **controlling variables** it implies, not the surface words.

        Examples:
        - "*I should* eat better." → vague aspiration without a contingency. **Not** Level 3.
        - "*Because* I'm pre-diabetic, I have to be careful." → general health framing, not CGM-derived. **Not** Level 4.
        - "*I learned* that rice spikes me, so now I skip it at dinner." → a CGM-linked self-generated rule. **Level 4**.
        """
    )

    st.subheader("4b. What does NOT count as high-level evidence")
    st.markdown(
        """
        Do not score the following as Level 3+ evidence of contingency learning:

        - **General concern / approval / motivation** without a behavior–consequence relation.
          - "I really care about my health."
          - "It's important to eat well."
        - **Generic health rules not tied to participant's own CGM**.
          - "Sugar is bad for you."
          - "You should drink more water."
        - **Stated intentions that lack a CGM-linked consequence** ("should" without contact).
          - "I should exercise more."
        - **Repetition of standard medical advice** received from clinicians or family.
          - "My nutritionist told me to eat smaller portions." → **Borrowed**, not self-generated.
        """
    )

    st.subheader("4c. Ambiguous case handling")
    st.markdown(
        """
        When an utterance is unclear, follow these rules:
        1. Resolve **conservatively** — choose the lower Primary level if uncertain.
        2. Paste the exact phrase/sentence in **Evidence Span / Meaning Unit** when Primary is 2–4.
        3. Use **Ambiguity / Review Flags** for recurring issues such as segmentation ambiguity, bilingual drift, or rule-vs-intent confusion.
        4. Use the **Coder Note** field to explain the ambiguity (e.g., "missing context", "intention vs enacted unclear").
        5. Use **Confidence 1–2** to flag for adjudication (see score definitions on the coding form).
        6. If a rule is mentioned but its source is unclear, set Rule Source to **Mixed/Unclear**.

        Examples to discuss in calibration:
        - "I cut back, kind of." → Behavior maybe, but no consequence and no clear rule. Likely Level 1 or 2.
        - "Sometimes I eat less rice." → Pattern hint without explicit rule. Likely Level 2.
        - "I try to walk if I can." → Aspiration, no CGM linkage. Likely Level 1; flag as ambiguous.
        """
    )

    st.subheader("4d. Enacted change vs Stated intention")
    st.markdown(
        """
        These two forms must be distinguished and recorded in the **Behavior Form** field:

        - **Enacted change** — current or ongoing correspondence between language and action.
          - "Now I walk after dinner."
          - "I switched to half a tortilla."
        - **Stated intention** — aspiration, plan, or emerging verbal regulation.
          - "I should walk after dinner."
          - "I'm planning to cut back next week."

        Both can occur at Level 3. Level 4 typically requires enacted change paired with a self-generated rule.
        """
    )

    st.subheader("4e. Rule Source — Self-generated vs Borrowed")
    st.markdown(
        """
        When a rule is present, classify its source in the **Rule Source** field:

        - **Self-generated** — derived from direct CGM-linked experience.
          - "After watching the sensor, I figured out tortillas at night spike me, so I skip them."
        - **Borrowed** — externally provided source (clinician, family, generic health messaging).
          - "My doctor told me to avoid carbs at night."
        - **Mixed/Unclear** — combination or unclear origin.
          - "I always heard sugar is bad, and the sensor confirmed it, so I cut back."
        """
    )

    st.subheader("4f. Using CGM Summary While Coding (supporting evidence only)")
    st.markdown(
        """
        The annotate page may show a **CGM Summary for Coding** when an item mentions diet, exercise, change, or alerts,
        or when you select Learning Outcome / device-use codes. CGM is **supporting or conflicting evidence** for the
        participant's language — **not** a substitute for coding the utterance itself.

        **Calibration examples:**

        1. **Language says improvement; full Phase 2 not improved yet, but last 3 days better**
           - Answer: "I started eating less rice after the alerts."
           - CGM: Phase 2 (all) `>140 mg/dL` still similar to Phase 1, but **last 3 days** improved.
           - Coding: Can still be **Primary 3** if contingency language is clear. Note the lag pattern in **Coder Note**;
             **last 3d** supports emerging change without requiring full Phase 2 improvement.

        2. **Language says improvement; CGM Phase 2 not improved yet (all or last 3d)**
           - Answer: "I started eating less rice after the alerts."
           - CGM: Phase 2 `>140 mg/dL` similar to or higher than Phase 1.
           - Coding: Can still be **Primary 3** if contingency language is clear. Note the mismatch; use **Stated intention**
             if change is not clearly enacted; lower **Confidence** if unsure.

        3. **Clear self-generated rule with plausible CGM support**
           - Answer: "After the alerts I figured out tortillas at night spike me, so I skip them now."
           - CGM: Phase 2 mean glucose or `>140 mg/dL` improved vs Phase 1.
           - Coding: **Primary 4**, **Self-generated**, **Enacted change**; higher confidence is reasonable.

        4. **Vague improvement language without CGM support**
           - Answer: "Yeah, I think I'm doing better with food."
           - CGM: Phase 2 worsened on `>140 mg/dL` and Time in Range.
           - Coding: Likely **Primary 1–2** (generic/vague). Flag mismatch in **Coder Note**; use **Confidence 1–2**
             for adjudication if you are uncertain between Level 1 and 2.

        **Remember:** The interview is retrospective. CGM shows study-period patterns; the participant may describe
        changes that are real but not yet visible in Phase 2 averages.
        """
    )

    st.subheader("5. Treatment of Accuracy")
    st.markdown(
        """
        Accuracy is **not** a primary coding dimension when working from transcript text alone.
        Code the contingency structure and rule source first. The **CGM Summary for Coding** panel helps you notice
        when language and glucose patterns align or conflict, but it should not automatically determine Primary level.
        Detailed CGM validation belongs in secondary review/adjudication.
        """
    )

    st.subheader("6. Aggregation and Transcript-Level Scoring")
    st.markdown(
        """
        - Highest Primary level reached in the transcript
        - Proportion of utterances at each Primary level
        - Mean secondary component score across coded utterances
        - Number or proportion of explicit self-generated rules
        """
    )

    st.subheader("7. Code-Level Reference Quotes (from G2 Study Codebook 3.0)")
    st.caption(
        "These are the official Example Quotes attached to each code in the codebook. "
        "Use them as your ground truth for what each code looks like in real participant speech."
    )
    tree = load_codebook_tree()
    for g in tree.get("groups", []):
        with st.expander(f"Code Group: {g['code_group']}", expanded=False):
            for sg in g.get("subgroups", []):
                st.markdown(f"**Subgroup: {sg['subgroup']}**")
                for c in sg.get("codes", []):
                    st.markdown(
                        f"- **{c['code_name']}** ({c.get('type', '')}) — {c.get('definition', '')}"
                    )
                    quotes = c.get("example_quotes") or []
                    if not quotes:
                        st.markdown("  - _(no example quotes available)_")
                    for q in quotes:
                        st.markdown(f"  - Example: \"{q}\"")
                    if c.get("additional_note"):
                        st.markdown(f"  - _Note:_ {c['additional_note']}")
                st.markdown("---")

    if user:
        st.subheader("8. Confirm Training Completion")
        if user.get("training_completed", False):
            st.success(
                f"Training already marked complete for {user.get('display_name', user['username'])}. "
                "You can re-read this page anytime."
            )
        else:
            confirm = st.checkbox(
                "I have read every section above, including the Codebook Reference Quotes, "
                "and I understand the Primary Hierarchy and Secondary Components."
            )
            if st.button("I have completed the Coder Training", type="primary", disabled=not confirm):
                mark_training_completed(user["username"])
                reload_user_into_session()
                st.success("Coder Training marked complete. The Annotate page is now unlocked.")
                st.rerun()


def render_manual_visual_guide() -> None:
    st.subheader("Visual Guide — Annotate Screenshots")
    st.caption(
        "Real interface captures from the platform (American English UI). "
        "Use with the step-by-step workflow below."
    )
    diagrams = [item for item in MANUAL_VISUAL_GUIDE if item["file"].endswith(".svg")]
    screenshots = [item for item in MANUAL_VISUAL_GUIDE if item["file"].endswith(".png")]
    available_diagrams = [item for item in diagrams if (MANUAL_IMAGES_DIR / item["file"]).exists()]
    available_screenshots = [item for item in screenshots if (MANUAL_IMAGES_DIR / item["file"]).exists()]

    if available_diagrams:
        st.markdown("#### Layout & workflow diagrams")
        for item in available_diagrams:
            st.markdown(f"**{item['title']}**")
            st.caption(item["caption"])
            st.image(str(MANUAL_IMAGES_DIR / item["file"]), width="stretch")
            st.divider()

    if available_screenshots:
        st.markdown("#### Real interface screenshots")
        for item in available_screenshots:
            st.markdown(f"**{item['title']}**")
            st.caption(item["caption"])
            st.image(str(MANUAL_IMAGES_DIR / item["file"]), width="stretch")
            st.divider()
    else:
        st.warning(
            "Real interface PNG screenshots are not installed on this server yet. "
            "You should still see the SVG diagrams above. Ask your admin to bundle "
            f"`docs/manual_images/*.png`, or run the screenshot capture script locally."
        )

    if not available_diagrams and not available_screenshots:
        st.info("Visual guide images are not bundled yet. See the Full Manual tab.")


def simple_manual_categories() -> List[dict]:
    return [
        {
            "title": "1. Question / Answer and Navigation",
            "file": "simple-01-overview-qa-navigation.png",
            "caption": "The fixed panel keeps the Question and Answer visible. Treat the Answer as the main text to code; use the Question only for context.",
            "notes": [
                "Start with the Answer. This is the response you are scoring.",
                "Use the Question to understand what the participant is responding to, but do not score the Question itself.",
                "Read both English and Spanish Answer text when available; use the Question only to resolve context.",
                "Use Previous, Next, and Current Position only for navigation; your work is saved only when you click Save or Save and Next.",
            ],
        },
        {
            "title": "2. Primary Hierarchy",
            "file": "simple-02-primary-hierarchy.png",
            "caption": "Primary Hierarchy is your main rating of what the Answer says.",
            "notes": [
                "Choose exactly one Primary level for the Answer before saving.",
                "New Answer items intentionally start blank to prevent accidental repeated scores.",
                "When the Answer could fit two adjacent levels, add a comment and a review flag instead of guessing.",
            ],
        },
        {
            "title": "3. Primary Confidence and Comment",
            "file": "simple-03-primary-selected-confidence-comment.png",
            "caption": "After selecting Primary, add confidence and an optional comment for that Primary decision about the Answer.",
            "notes": [
                "Confidence belongs to your selected Primary decision for this Answer, not to the whole interview.",
                "Use 1-2 when the item likely needs adjudication.",
                "Use the comment to explain what in the Answer supports the Primary level or why it is uncertain.",
            ],
        },
        {
            "title": "4. Components",
            "file": "simple-04-components-confidence-comments.png",
            "caption": "Components identify which pieces of a contingency relation are present in the Answer.",
            "notes": [
                "Check Context, Behavior, Consequence, or Rule only when the Answer supports it.",
                "Each checked component has its own confidence and comment field.",
                "Do not check a component only because it seems plausible from the Question or clinical context; it must be in the Answer language.",
            ],
        },
        {
            "title": "5. Rule Taxonomy",
            "file": "simple-05-rule-taxonomy.png",
            "caption": "Rule Taxonomy appears when the Answer supports Rule or when your Primary rating is 3 or 4.",
            "notes": [
                "Mark Rule Source based on how the Answer presents the source of the rule.",
                "Mark Behavior Form based on whether the Answer describes behavior already happening or only a future intention.",
                "Primary 4 requires self-generated rule evidence in the Answer; if the source is unclear, mark uncertainty and explain in comments.",
            ],
        },
        {
            "title": "6. Evidence, Review Flags, Notes, and Save",
            "file": "simple-06-evidence-flags-notes-save.png",
            "caption": "Use this section to document the exact Answer evidence, ambiguity, and item-level notes before saving.",
            "notes": [
                "For Primary 2-4, click the sentence in the Answer that shows the Primary level (no typing needed).",
                "Review flags are for calibration and adjudication; they are not mistakes.",
                "Coder Note is for Answer-level explanation that does not belong to one specific marking.",
                "Save and Next should be used only after reviewing required fields.",
            ],
        },
    ]


def render_simple_manual_screenshot_card(category: dict) -> None:
    st.subheader(category["title"])
    image_path = MANUAL_IMAGES_DIR / category["file"]
    st.caption(category["caption"])
    if image_path.exists():
        st.image(str(image_path), width="stretch")
    else:
        st.warning(f"Screenshot not found: {category['file']}")
    st.markdown("**Annotation notes**")
    for note in category["notes"]:
        st.markdown(f"- {note}")


PLAIN_OVERVIEW_MD = """
### The job in one minute
People wore a small **glucose sensor** for a while, then talked about what they noticed. You read each
short **Answer** and decide **one main thing first**: *how clearly does this person connect their own
actions to their glucose — and do they turn it into a rule for next time?* You give that a single score
from **0 to 4**. Then you tick a few boxes for the pieces that actually appear in the Answer. That is the
core of the task.

You score **only the Answer**. The **Question** is shown just so you know what the person was replying
to — do not score the Question.

> **Remember:** do **not** add any interpretation, assumption, or guess of your own. Focus only on what
> the **response (the Answer)** actually says. If it is not in the Answer, it does not count.

### The 0–4 score in everyday words
Each level below comes with **three sample Answers** so you can see the pattern:

- **0 — They don't connect anything** (a general comment, no link at all).
  - *"It was fine."*
  - *"No, everything was good."*
  - *"I don't really remember anything specific."*
- **1 — They just describe something happening, with no cause.**
  - *"My sugar went up."*
  - *"It was high one morning."*
  - *"I saw some spikes on the app."*
- **2 — They link an action or situation to a result, but make no plan.**
  - *"When I eat rice, my glucose goes up."*
  - *"After I drank soda, it spiked."*
  - *"If I don't walk, my numbers stay higher."*
- **3 — They are starting to change something because of what they noticed.**
  - *"Soda spikes me, so I'm trying to drink water instead."*
  - *"Bread seems bad for me, so I'm cutting back."*
  - *"I'm planning to walk after dinner because it seems to help."*
- **4 — They state a clear personal rule they worked out themselves.**
  - *"Tortillas at night spike me, so now I skip them at dinner."*
  - *"Big portions raise me, so now I eat smaller plates."*
  - *"Walking after meals brings me down, so now I always walk after eating."*

### The four boxes (Components)
Tick a box **only if that piece is actually in the Answer**. Here is what each one means, with three
short **Question → Answer** examples (the box words are in **bold**):

- **Context — the situation: when / where / what was going on.** This is the scene the rest of the
  story hangs on, so look for it first.
  - Q: "When do your readings go up?" → A: "**At dinner**, my numbers climb."
  - Q: "When did you feel different?" → A: "**After a long walk**, it was lower."
  - Q: "When does it spike?" → A: "**When I drink soda**, it goes up."
- **Behavior — what the person actually did** (an action).
  - Q: "What did you eat that day?" → A: "**I ate rice** with lunch."
  - Q: "Did you change your routine?" → A: "**I went walking** in the evening."
  - Q: "How did you react?" → A: "**I cut my portion** in half."
- **Consequence — what happened to the glucose afterward** (the result they noticed).
  - Q: "What happened next?" → A: "**My glucose went up.**"
  - Q: "And the reading?" → A: "**It stayed flat.**"
  - Q: "What did the sensor show?" → A: "**It came back down** quickly."
- **Rule — the lesson for the future** ("from now on I will…").
  - Q: "Any general rule for yourself?" → A: "**So now I avoid tortillas at dinner.**"
  - Q: "What will you do going forward?" → A: "**I'll walk after meals from now on.**"
  - Q: "Did you make a plan?" → A: "**From now on I'll drink water instead of soda.**"

### Extra details — only when there is a rule
Fill these in **only** when the Answer actually contains a rule (your score is usually 3 or 4).

- **Rule Source — where did the idea come from?**
  - **Self-generated** — the person worked it out from their **own** sensor experience.
    *("I figured out that tortillas spike me…")*
  - **Borrowed (doctor, family, general advice)** — the idea came from **someone else** or general advice.
    *("My doctor told me sugary drinks raise glucose…")*
  - **Mixed/Unclear** — it's a bit of both, or the Answer does not make the source clear.
- **Behavior Form — has a diet or activity change started? Are they already exercising?**
  Ask yourself: *Have they already changed what they eat or how they move — or are they only planning to?*
  - **Enacted change (already doing it)** — a **diet or exercise change has already started** and is happening now.
    *("I already stopped drinking soda," "so now I walk after dinner," "I cut my portions.")*
  - **Stated intention (planning to do it)** — they **plan** a diet or exercise change but have **not started yet**.
    *("I'm going to start walking," "I plan to eat less bread," "I want to cut back on soda.")*

### A few more fields
- **Confidence (1–5)** — how sure are you? 1 = mostly guessing, 5 = certain.
- **Comment** — a quick note on why you chose what you chose.
- **Evidence span** — for scores **2–4**, just **click the sentence in the Answer** that best shows your
  score. **No typing or copying needed** — you simply pick the part that supports your choice.
- **Review flag** — "this one is tricky; someone should double-check."
"""

PLAIN_GLOSSARY_MD = """
Plain-language meanings for the terms you will see in this tool:

- **Primary Hierarchy** — the main 0–4 score for the Answer.
- **Components** — the four building-block boxes (Context, Behavior, Consequence, Rule).
- **Rule Taxonomy** — the extra details about a rule (Rule Source and Behavior Form).
- **Rule Source** — where the rule came from: the person themselves, or outside advice.
- **Behavior Form** — whether a diet or exercise change has **already started** or is **only planned**.
- **Evidence span / Meaning unit** — the sentence you **click** in the Answer as proof of your score (no typing needed).
- **Coding Confidence** — how sure you are about a choice (1–5).
- **Coder Note** — a general note about the whole Answer (not tied to one box).
- **Contingency language** — words that link a cause to an effect, and sometimes a rule.
- **Check sample** — a hidden item that already has a known answer, used to check accuracy.
- **Attention check** — a very clear hidden item; getting it wrong usually means reading too fast.
- **Calibration** — making sure everyone scores the same Answer the same way.
- **Adjudication** — a later review by the team to settle tricky or disagreeing items.
- **Inter-rater agreement** — how often two coders give the same score on the same items.
- **Test Drive** — the short practice check that unlocks scoring.
"""


def build_simple_user_manual_markdown(*, admin: bool = False) -> str:
    primary_ref = "\n".join(
        [
            f"- **{lv['level']} - {lv['title']}**: {lv['definition']} Example: {lv['example']}"
            for lv in primary_levels_for_display()
        ]
    )
    component_ref = "\n".join(
        [
            f"- **{c['name']}**: {c['definition']} Example: {c['example']}"
            for c in secondary_components_for_display()
        ]
    )
    confidence_ref = "\n".join(
        [
            f"- **{level['score']} - {level['title']}**: {level['description']} {level['guidance']}"
            for level in CODING_CONFIDENCE_LEVELS
        ]
    )
    rule_source_ref = "\n".join(
        [
            f"- **{option}**: {definition}."
            for option, definition in RULE_SOURCE_DEFINITIONS.items()
        ]
    )
    behavior_form_ref = "\n".join(
        [
            f"- **{option}**: {definition}."
            for option, definition in BEHAVIOR_FORM_DEFINITIONS.items()
        ]
    )
    issue_flag_ref = "\n".join([f"- {flag}" for flag in ISSUE_FLAG_OPTIONS if "CGM" not in flag])
    screenshot_ref = "\n\n".join(
        [
            "\n".join(
                [
                    f"### {category['title']}",
                    f"![{category['title']}](docs/manual_images/{category['file']})",
                    category["caption"],
                    "",
                    "**Annotation notes**",
                    *[f"- {note}" for note in category["notes"]],
                ]
            )
            for category in simple_manual_categories()
        ]
    )
    admin_workflow_step = (
        "\n14. Use `Quality & Agreement` (admin) to review hidden check samples and inter-rater agreement.\n"
        if admin
        else "\n"
    )
    admin_saving_lines = (
        "- `Quality & Agreement` (admin): hidden check sample performance and inter-rater agreement.\n"
        if admin
        else ""
    )
    admin_quality_section = (
        """
## 13. Quick Quality Checklist

Before saving, check:

- Primary level matches only what the Answer explicitly supports.
- Components are checked only when present in the Answer.
- Rule Source and Behavior Form are completed when the Answer supports Rule or Primary 3-4 is selected.
- Every selected marking has a confidence rating.
- Comments explain difficult or uncertain choices.
- Evidence span is present for Primary 2-4.

## 14. Plain-Language Glossary
"""
        if admin
        else """
## 13. Plain-Language Glossary
"""
    )

    return f"""# Simple Scoring User Manual

This manual is written for you as the annotator. You do not need any medical or technical background to
do this well — just careful reading. For each item, the **Answer** is the response you should score. The
**Question** is shown so you understand what the participant was responding to, but you should not score
the Question itself.

## 0. Start Here (Plain Language)
{PLAIN_OVERVIEW_MD}

## 0b. Preliminary Examples (Scores 0-3)
{PRELIMINARY_EXAMPLES_TEXT_MD}
Score 4 is illustrated in the chain diagram (What you will do section).
{CONTINGENCY_CHAIN_MD}

## 1. Goal

For each item, score what the **Answer** explicitly supports:

- the main 0–4 score for how clearly the person connects actions to glucose and forms a rule (`Primary Hierarchy`);
- which of the four building blocks are present (`Context`, `Behavior`, `Consequence`, `Rule`);
- rule details when relevant (`Rule Source`, `Behavior Form`);
- how sure you are and anything a reviewer should know (`Coding Confidence`, comments, evidence span, review flags).

Score only what the Answer actually says. Do not guess at hidden intent, medical truth, or background
that is not written in the Answer. Use the Question only to understand what the Answer means. When the
Answer is unclear, add a comment and a review flag instead of guessing.

## 2. Basic Workflow

1. Sign in.
2. Complete `Initial Training`. Read the references and pass the short Test Drive (a basic Primary Hierarchy check on a few clear items) to unlock formal scoring.
3. Open **Step 4 · Score Answers**.
4. Select the participant in the sidebar if needed.
5. Read the `Answer` first. Use the `Question` only as context for interpreting that Answer.
6. Choose one `Primary Hierarchy` level for the Answer.
7. Add `Coding Confidence` and an optional `Comment` for the selected Primary rating.
8. Check any `Components` that are clearly present in the Answer, and for each checked component add confidence and an optional comment.
9. If the Answer supports `Rule` or Primary is 3-4, complete `Rule Source` and `Behavior Form`, again with confidence and optional comments for each selected option.
10. Add an `Answer Evidence Span / Meaning Unit` when Primary is 2-4.
11. Add `Ambiguity / Review Flags` when useful, with confidence/comments for selected flags.
12. Add a broader `Coder Note` if the item needs explanation.
13. Click `Save` or `Save and Next`.
{admin_workflow_step}
## 3. Screenshots and Category-Specific Notes

{screenshot_ref}

## 4. Primary Hierarchy Reference

{primary_ref}

## 5. Components Reference

{component_ref}

A component should be checked only when it is supported by the Answer. Missing or merely implied information should usually remain unchecked.

## 6. Rule Taxonomy

Complete this section when the Answer contains a rule-like statement or when the Primary rating is 3 or 4.

### Rule Source

{rule_source_ref}

### Behavior Form

{behavior_form_ref}

## 7. Coding Confidence

Every selected marking has its own `Coding Confidence`; rate how confident you are that the Answer supports that specific marking.

{confidence_ref}

Use lower confidence when the Answer allows competing interpretations, has translation drift, uses vague wording, lacks context, or sits between adjacent Primary levels.

## 8. Comments

Each selected marking has its own optional `Comment` field. Use it to explain which part of the Answer supports that specific mark or why it was uncertain.

Examples:

- Primary comment: `Could be Level 2 or 3; future action is implied but not explicit.`
- Component comment: `Behavior present: eating tortillas.`
- Rule Source comment: `Self-generated is likely, but source is not fully explicit.`

The broader `Coder Note` field is for Answer-level comments that do not belong to one specific marking.

## 9. Evidence Span / Meaning Unit

When Primary is 2-4, click the sentence in the Answer that shows the Primary rating — no typing or copying needed. (You can still type or edit the wording manually if you prefer.)

Good evidence spans:

- `when I eat rice my reading goes up`
- `so now I walk after dinner`
- `I figured out tortillas at night affect me`

Avoid pasting the whole Answer unless the whole Answer is needed.

## 10. Ambiguity / Review Flags

Use flags when an item may need later review.

{issue_flag_ref}

Flags are not errors. They help calibration and adjudication.

## 11. Saving and Navigation

- `Save`: saves your scores for the current Answer and stays on the same item.
- `Save and Next`: saves your scores for the current Answer and moves to the next visible Answer item.
- `Previous` / `Next`: moves between items.
- `Current Position`: jumps to an item number within the current filtered set.
- Sidebar subject selector: switches participants.
{admin_saving_lines}- **My Progress**: shows your saved scores and recent saved records.

## 12. What Not To Use

The simplified version does not ask you to assign codebook codes. It also hides CGM, demographics, and highlighted words. Base your score on the **Answer** text shown at the top; use the Question only as context.

{admin_quality_section}
{PLAIN_GLOSSARY_MD}
"""


@st.cache_data(show_spinner=False)
def build_simple_user_manual_pdf(admin: bool = False) -> bytes:
    return build_manual_pdf_bytes(
        build_simple_user_manual_markdown(admin=admin),
        Path(__file__).resolve().parent,
    )


def page_simple_user_manual(user: dict) -> None:
    admin = user_is_admin(user)
    st.header("User Manual")
    st.caption(
        "A plain-language guide to scoring. No medical or technical background needed — just careful "
        "reading. You score the **Answer**; the **Question** is only there for context."
    )

    manual_md = build_simple_user_manual_markdown(admin=admin)
    try:
        manual_pdf = build_simple_user_manual_pdf(admin=admin)
    except Exception as exc:
        manual_pdf = None
        st.warning(f"PDF export is unavailable ({exc}). You can still read the manual in the tabs below.")

    if manual_pdf:
        st.download_button(
            label="Download manual (PDF)",
            data=manual_pdf,
            file_name="CGM_Contingency_Speech_Scoring_User_Manual.pdf",
            mime="application/pdf",
            width="stretch",
        )
    else:
        st.download_button(
            label="Download manual (Markdown fallback)",
            data=manual_md,
            file_name="simple_labeling_user_manual.md",
            mime="text/markdown",
            width="stretch",
        )

    tab_labels = [
        "Start Here",
        "Workflow",
        "Screenshots & Notes",
        "Field Reference",
        "Confidence & Comments",
        "Glossary",
    ]
    if admin:
        tab_labels.append("Quality Checklist")
    tabs = st.tabs(tab_labels)
    tab_intro = tabs[0]
    tab_start = tabs[1]
    tab_screens = tabs[2]
    tab_fields = tabs[3]
    tab_rules = tabs[4]
    tab_glossary = tabs[5]
    tab_quality = tabs[6] if admin else None

    with tab_intro:
        st.subheader("Start Here (Plain Language)")
        st.markdown(PLAIN_OVERVIEW_MD)
        st.divider()
        st.subheader("Preliminary examples (scores 0–3)")
        render_preliminary_examples()
        st.divider()
        st.markdown(CONTINGENCY_CHAIN_MD)

    with tab_start:
        st.subheader("Step-by-step, in plain words")
        st.caption("Follow these 11 steps for every Answer. Dashed boxes = only when the condition applies.")
        render_scoring_workflow_visual()
        st.info(
            "This simplified screen hides extra material (codebook codes, glucose charts, demographics, "
            "highlighted words) on purpose. Your score should come from the **Answer text** alone."
        )

    with tab_glossary:
        st.subheader("Plain-Language Glossary")
        st.caption("Quick, everyday meanings for the terms used in this tool.")
        st.markdown(PLAIN_GLOSSARY_MD)

    with tab_screens:
        st.subheader("Screenshots by Scoring Category")
        st.caption("Each section shows the current simplified interface and category-specific annotation notes.")
        for category in simple_manual_categories():
            render_simple_manual_screenshot_card(category)
            st.divider()

    with tab_fields:
        st.subheader("Primary Hierarchy")
        for lv in primary_levels_for_display():
            st.markdown(
                f"""
                <div class="level-card">
                  <b>{lv['level']} - {lv['title']}</b><br/>
                  {lv['definition']}<br/>
                  <i>Example:</i> {lv['example']}
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.subheader("Components")
        for c in secondary_components_for_display():
            st.markdown(
                f"""
                <div class="level-card">
                  <b>{c['name']}</b><br/>
                  {c['definition']}<br/>
                  <i>Example:</i> {c['example']}
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.subheader("Rule details (only when there is a rule)")
        st.caption(
            "Fill these in only when the Answer contains a rule, or when your Primary score is 3 or 4."
        )
        st.markdown("**Rule Source** — where did the idea come from?")
        for option, definition in RULE_SOURCE_DEFINITIONS.items():
            st.markdown(f"- **{option}**: {definition}.")
        st.markdown("**Behavior Form** — are they doing it yet?")
        for option, definition in BEHAVIOR_FORM_DEFINITIONS.items():
            st.markdown(f"- **{option}**: {definition}.")

    with tab_rules:
        st.subheader("Coding Confidence")
        for level in CODING_CONFIDENCE_LEVELS:
            st.markdown(
                f"- **{level['score']} - {level['title']}**: "
                f"{level['description']} {level['guidance']}"
            )

        st.subheader("How to Use Comments")
        st.markdown(
            """
            Each choice you make has its own **Comment** box. Use it to say, in a few words, which part of
            the Answer made you choose that.

            The broader **Coder Note** box is for a comment about the whole Answer — for example: the
            translation was unclear, the wording was confusing, or this one is tricky and the team should
            double-check it.
            """
        )

        st.subheader("Evidence Span (click the sentence)")
        st.markdown(
            """
            For scores **2–4**, just **click the sentence** in the Answer that best shows your score —
            **no typing or copying needed**. A manual text box is still available if you want to
            fine-tune the wording.
            """
        )

    if tab_quality is not None:
        with tab_quality:
            st.subheader("Before Saving (admin)")
            st.markdown(
                """
                - Code only what the Answer explicitly supports.
                - Use the Question only as context, not as evidence to score.
                - When uncertain between two levels, add a comment and a review flag instead of guessing.
                - Check Components only when they are present in the Answer.
                - Complete Rule Source and Behavior Form when the Answer supports Rule or Primary 3-4 is selected.
                - Use confidence 1-2 for items that should likely be adjudicated.
                - Use comments to explain ambiguous or difficult judgments.
                - Confirm Evidence Span is filled for Primary 2-4.
                """
            )


def page_user_manual(user: dict) -> None:
    if SIMPLE_LABELING_MODE:
        page_simple_user_manual(user)
        return

    st.header("User Manual")
    st.caption(
        "Complete guide for coders and clinicians: platform design, annotation workflow, "
        "CGM integration, and adjudication."
    )
    if not USER_MANUAL_PATH.exists():
        st.error(f"Manual file not found: {USER_MANUAL_PATH.name}")
        return

    st.markdown(
        """
        **Quick links in this manual:**
        - **Visual Guide** (screenshots & layout diagrams) — tab below
        - Platform design philosophy & G2 Phase design
        - Step-by-step **Annotate** workflow (codes, Primary, CGM summary)
        - **Participant Context** (demographics, 12 metrics, phase comparison)
        - **Adjudication** & saved record format
        """
    )
    st.download_button(
        label="Download manual (PDF)",
        data=build_manual_pdf_bytes(
            USER_MANUAL_PATH.read_text(encoding="utf-8"),
            Path(__file__).resolve().parent,
        ),
        file_name="G2_Coding_Labeling_User_Manual.pdf",
        mime="application/pdf",
        width="stretch",
    )

    tab_visual, tab_text = st.tabs(["Visual Guide", "Full Manual"])
    with tab_visual:
        render_manual_visual_guide()
    with tab_text:
        st.markdown(USER_MANUAL_PATH.read_text(encoding="utf-8"))


# ----------------------------- App entry -----------------------------

def main() -> None:
    st.set_page_config(page_title=PLATFORM_PAGE_TITLE, layout="wide")

    st.sidebar.header("Display")
    theme = st.sidebar.radio("Theme", options=["Light", "Dark"], horizontal=True)
    render_theme_css(theme)

    init_auth_state()
    get_cookie_manager()

    if st.session_state.get("_signed_out"):
        logout_retries = int(st.session_state.get("_logout_cookie_retries", 0))
        if read_auth_token() and logout_retries < 5:
            st.session_state._logout_cookie_retries = logout_retries + 1
            clear_auth_cookie()
            st.rerun()
        st.session_state.pop("_logout_cookie_retries", None)
        st.session_state.pop("_signed_out", None)
        st.session_state.user = None
        page_login()
        return

    if st.session_state.user is None:
        if not try_restore_auth_session():
            retries = int(st.session_state.get("_auth_cookie_retries", 0))
            cookies_pending = get_cookie_manager().get_all(key="auth_main_get_all") is None
            if cookies_pending and retries < 8:
                st.session_state._auth_cookie_retries = retries + 1
                st.rerun()
            else:
                st.session_state.pop("_auth_cookie_retries", None)

    if st.session_state.user is None:
        page_login()
        return

    user = st.session_state.user
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Signed in as:** {user.get('display_name', user['username'])}")
    st.sidebar.caption(
        "Your session is remembered on this device (refresh-safe for about 30 days when "
        "'Keep me signed in' is checked)."
    )
    if st.sidebar.button("Sign out", width="stretch"):
        sign_out_user()
        st.rerun()

    st.sidebar.header("Navigation")
    training_label = (
        "Step 3 \u00b7 Initial Training"
        if SIMPLE_LABELING_MODE
        else "Step 3 \u00b7 Coder Training"
    )
    nav_pages: List[tuple[str, Callable[[], None]]] = [
        ("Step 1 \u00b7 Introduction", lambda: page_introduction(st.session_state.user)),
        ("Step 2 \u00b7 User Manual", lambda: page_user_manual(st.session_state.user)),
        (
            training_label,
            (
                (lambda: page_simple_labeling_training(st.session_state.user))
                if SIMPLE_LABELING_MODE
                else (lambda: page_coder_training(st.session_state.user))
            ),
        ),
        ("Step 4 \u00b7 Score Answers", lambda: page_annotate(st.session_state.user, theme)),
        ("Step 5 \u00b7 My Progress", lambda: page_my_stats(st.session_state.user)),
    ]
    # Step 6 (Quality & Agreement) is an admin-only view.
    if user_is_admin(user):
        nav_pages.append(
            ("Step 6 \u00b7 Quality & Agreement", lambda: page_agreement_dashboard(st.session_state.user))
        )
    nav_labels = [label for label, _ in nav_pages]
    nav_handlers = {label: handler for label, handler in nav_pages}

    training_ready = (
        simple_training_is_complete(st.session_state.user)
        if SIMPLE_LABELING_MODE
        else bool(st.session_state.user.get("training_completed", False))
    )
    default_label = "Step 4 \u00b7 Score Answers" if training_ready else "Step 1 \u00b7 Introduction"
    if not training_ready:
        st.sidebar.warning("Complete Initial Training (Step 3) before scoring real Answers.")
    default_idx = nav_labels.index(default_label)
    page = st.sidebar.radio("Page", options=nav_labels, index=default_idx)
    nav_handlers[page]()


if __name__ == "__main__":
    main()
