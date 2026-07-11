#!/usr/bin/env python3
"""arxiv_scout.py — pull a professor's recent arXiv output and emit match signals.

Usage:
    python arxiv_scout.py --author "Marco Hutter" [--months 18] [--max 40]

Prints a signal report and appends a pre-scored row skeleton to labs.csv.
Only stdlib is used (urllib + xml), so it runs anywhere.

The score is a STARTING POINT. The human decides. The point of the script is to make
'evaluate 40 labs' cost minutes instead of weekends, and to force the same rubric on
every lab so December-you can trust September-you's numbers.
"""

import argparse
import csv
import datetime as dt
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ARXIV_API = "http://export.arxiv.org/api/query?search_query={q}&start=0&max_results={n}&sortBy=submittedDate&sortOrder=descending"
NS = {"a": "http://www.w3.org/2005/Atom"}

# Match signals tied to Kartik's actual assets. Edit weights as the niche sharpens.
SIGNALS = {
    "data_acquisition": (3, r"data (acquisition|collection|curation)|teleoperation|demonstration data|dataset (creation|generation)|data-centric"),
    "sim_to_real":      (3, r"sim-?to-?real|domain randomi[sz]ation|reality gap"),
    "temporal_models":  (2, r"temporal|sequence model|time[- ]series|sliding window|trajectory prediction"),
    "world_models":     (2, r"world model|latent dynamics|model-based (rl|reinforcement)|jepa|predictive (coding|model)"),
    "humanoid_manip":   (2, r"humanoid|manipulation|dexterous|legged|quadruped"),
    "infra_repro":      (2, r"docker|container|reproducib|benchmark(ing)? (suite|framework)|open[- ]source (framework|stack|platform)"),
    "multimodal":       (1, r"multi-?modal|vision-language|proprioceptio"),
}


def fetch(author: str, max_results: int):
    q = urllib.parse.quote(f'au:"{author}"')
    url = ARXIV_API.format(q=q, n=max_results)
    with urllib.request.urlopen(url, timeout=30) as r:
        return ET.fromstring(r.read())


def analyze(feed, months: int):
    cutoff = dt.datetime.now() - dt.timedelta(days=30 * months)
    papers = []
    for e in feed.findall("a:entry", NS):
        published = dt.datetime.strptime(e.findtext("a:published", "", NS)[:10], "%Y-%m-%d")
        if published < cutoff:
            continue
        papers.append({
            "title": re.sub(r"\s+", " ", e.findtext("a:title", "", NS)).strip(),
            "date": published.date().isoformat(),
            "abstract": re.sub(r"\s+", " ", e.findtext("a:summary", "", NS)).strip(),
            "url": e.findtext("a:id", "", NS),
        })
    hits, score = Counter(), 0
    for p in papers:
        text = (p["title"] + " " + p["abstract"]).lower()
        p["matched"] = []
        for name, (w, pat) in SIGNALS.items():
            if re.search(pat, text):
                hits[name] += 1
                p["matched"].append(name)
        score += len(p["matched"])
    return papers, hits, score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--author", required=True)
    ap.add_argument("--months", type=int, default=18)
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--csv", default=str(Path(__file__).with_name("labs.csv")))
    args = ap.parse_args()

    papers, hits, score = analyze(fetch(args.author, args.max), args.months)
    print(f"\n=== {args.author} — {len(papers)} papers in last {args.months} months ===")
    for name, (w, _) in sorted(SIGNALS.items(), key=lambda kv: -hits.get(kv[0], 0) * kv[1][0]):
        if hits.get(name):
            print(f"  {name:<18} {hits[name]:>2} papers  (weight {w})")
    print(f"  raw match score: {score}")
    print("\n  Most recent, signal-matching papers (candidate email hooks):")
    shown = 0
    for p in papers:
        if p["matched"] and shown < 5:
            print(f"   - [{p['date']}] {p['title']}\n     {p['url']}  <- {', '.join(p['matched'])}")
            shown += 1
    if shown == 0:
        print("   (none matched — likely a poor-fit lab; deprioritize)")

    # Append skeleton row; human fills the judgment columns.
    csv_path = Path(args.csv)
    new = not csv_path.exists()
    with open(csv_path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["professor", "institution", "raw_match_score", "papers_18mo",
                        "top_hook_paper", "publishes_code", "hosts_visitors_evidence",
                        "swiss_public_institution", "fit_1to5_HUMAN", "status", "email_sent",
                        "followup_date", "notes"])
        hook = next((p["title"] for p in papers if p["matched"]), "")
        w.writerow([args.author, "", score, len(papers), hook, "", "", "", "", "unscored", "", "", ""])
    print(f"\n  row appended to {csv_path} — fill the HUMAN columns before drafting any email.")


if __name__ == "__main__":
    sys.exit(main())
