#!/usr/bin/env python3
"""
Dazhbog Graph — SVG dashboard generator.
Pulls live metrics from the IDA Lumina relay and renders a HUD-style SVG.
"""

import json
import sys
import urllib.request
import ssl
from datetime import datetime, timezone

API_URL = "https://ida.int.mov:1234/api/metrics"
OUTPUT = "dazhbog-stats.svg"

# ── colour palette ────────────────────────────────────────────────────────────
BG = "#1a1d23"
BG_CARD = "#22262e"
BORDER = "#2d3340"
GREEN_ACCENT = "#4ade80"
GREEN_BAR = "#3ec96a"
TEXT_TITLE = "#8b95a5"
TEXT_VALUE = "#e8ecf2"
TEXT_SUB = "#5e6878"
TEXT_TAG = "#5e6878"
BOTTOM_BG = "#1e2129"
BOTTOM_BORDER = "#2a2f3a"
RATE_COLOR = "#4ade80"

# ── layout constants ──────────────────────────────────────────────────────────
W = 1540
SECTION_X = 30
SECTION_W = W - 60
CARD_GAP = 12
SECTION_GAP = 24
ROW_H = 160
BOTTOM_H = 90

# ── helpers ───────────────────────────────────────────────────────────────────


def fmt_num(n):
    """Format number with commas: 9014542 → 9,014,542"""
    return f"{n:,}"


def fmt_bytes(b):
    """Format bytes as human-readable: 4833680349 → 4.5 GB"""
    if b < 1024:
        return f"{b} B"
    for unit in ["KB", "MB", "GB", "TB"]:
        b /= 1024
        if b < 1024 or unit == "TB":
            if b >= 100:
                return f"{b:.0f} {unit}"
            else:
                return f"{b:.1f} {unit}"
    return f"{b:.1f} PB"


def fmt_uptime(secs):
    """Format seconds as Xd Xh Xm."""
    days = secs // 86400
    hours = (secs % 86400) // 3600
    mins = (secs % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h {mins}m"
    elif hours > 0:
        return f"{hours}h {mins}m"
    else:
        return f"{mins}m"


def mini_bars(x, y, n=5, color=GREEN_BAR):
    """Render a tiny bar chart indicator (decorative)."""
    bars = ""
    heights = [8, 14, 11, 16, 10]
    for i in range(n):
        bx = x + i * 6
        bh = heights[i % len(heights)]
        by = y + 18 - bh
        bars += f'<rect x="{bx}" y="{by}" width="4" height="{bh}" rx="1" fill="{color}" opacity="0.7"/>\n'
    return bars


def escape(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── card renderers ────────────────────────────────────────────────────────────


def render_card(x, y, w, h, title, tag, value, subtitle):
    """Render a single metric card."""
    svg = ""
    svg += f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{BG_CARD}" stroke="{BORDER}" stroke-width="1"/>\n'
    svg += f'<rect x="{x}" y="{y + 8}" width="3" height="{h - 16}" rx="1.5" fill="{GREEN_ACCENT}" opacity="0.6"/>\n'
    svg += f'<text x="{x + 16}" y="{y + 28}" font-family="\'JetBrains Mono\',\'SF Mono\',\'Fira Code\',monospace" font-size="11" font-weight="600" letter-spacing="1.5" fill="{TEXT_TITLE}">{escape(title)}</text>\n'
    svg += f'<text x="{x + w - 16}" y="{y + 28}" font-family="\'JetBrains Mono\',\'SF Mono\',monospace" font-size="10" fill="{TEXT_TAG}" text-anchor="end" letter-spacing="1">{escape(tag)}</text>\n'
    svg += f'<text x="{x + 16}" y="{y + 80}" font-family="\'JetBrains Mono\',\'SF Mono\',\'Fira Code\',monospace" font-size="40" font-weight="700" fill="{TEXT_VALUE}">{escape(value)}</text>\n'
    svg += f'<text x="{x + 16}" y="{y + h - 18}" font-family="\'JetBrains Mono\',\'SF Mono\',monospace" font-size="11" fill="{TEXT_SUB}">{escape(subtitle)}</text>\n'
    svg += mini_bars(x + w - 46, y + h - 36)
    return svg


def render_cards_row(cy, cards):
    """Render a row of N cards, evenly spaced across section width."""
    n = len(cards)
    card_w = (SECTION_W - CARD_GAP * (n - 1) - 8) // n
    card_h = ROW_H - 30
    svg = ""
    for i, (title, tag, val, sub) in enumerate(cards):
        cx = SECTION_X + 4 + i * (card_w + CARD_GAP)
        svg += render_card(cx, cy, card_w, card_h, title, tag, val, sub)
    return svg


def render_section_header(x, y, w, label, sec_id):
    """Render a section header bar."""
    svg = ""
    svg += f'<line x1="{x}" y1="{y}" x2="{x + w}" y2="{y}" stroke="{BORDER}" stroke-width="1"/>\n'
    svg += f'<rect x="{x}" y="{y}" width="3" height="24" rx="1" fill="{GREEN_ACCENT}" opacity="0.5"/>\n'
    svg += f'<text x="{x + 16}" y="{y + 16}" font-family="\'JetBrains Mono\',\'SF Mono\',monospace" font-size="12" font-weight="600" letter-spacing="2" fill="{TEXT_TITLE}">{escape(label)}</text>\n'
    svg += f'<text x="{x + w - 8}" y="{y + 16}" font-family="\'JetBrains Mono\',\'SF Mono\',monospace" font-size="10" fill="{TEXT_TAG}" text-anchor="end" letter-spacing="1">{escape(sec_id)}</text>\n'
    return svg


def render_bottom_stat(x, y, w, label, value, rate=None):
    """Render a single bottom-bar stat cell."""
    svg = ""
    # right separator
    svg += f'<line x1="{x + w}" y1="{y + 10}" x2="{x + w}" y2="{y + BOTTOM_H - 10}" stroke="{BOTTOM_BORDER}" stroke-width="1"/>\n'
    # label
    svg += f'<text x="{x + w // 2}" y="{y + 24}" font-family="\'JetBrains Mono\',\'SF Mono\',monospace" font-size="9" font-weight="600" letter-spacing="1.2" fill="{TEXT_TAG}" text-anchor="middle">{escape(label)}</text>\n'
    # value
    svg += f'<text x="{x + w // 2}" y="{y + 52}" font-family="\'JetBrains Mono\',\'SF Mono\',\'Fira Code\',monospace" font-size="22" font-weight="700" fill="{TEXT_VALUE}" text-anchor="middle">{escape(value)}</text>\n'
    # underline decoration
    lw = 40
    svg += f'<line x1="{x + w // 2 - lw // 2}" y1="{y + 62}" x2="{x + w // 2 + lw // 2}" y2="{y + 62}" stroke="{BOTTOM_BORDER}" stroke-width="2"/>\n'
    # rate
    if rate is not None:
        svg += f'<text x="{x + w // 2}" y="{y + 78}" font-family="\'JetBrains Mono\',\'SF Mono\',monospace" font-size="9" fill="{RATE_COLOR}" text-anchor="middle">{escape(rate)}</text>\n'
    return svg


# ── main SVG composition ─────────────────────────────────────────────────────


def build_svg(data):
    """Build the full dashboard SVG from API data."""

    body = ""
    cy = 16

    # ── SECTION 0: DATABASE STATUS (4 cards) ──────────────────────────────
    body += render_section_header(
        SECTION_X, cy, SECTION_W, "DATABASE STATUS", "SEC-000"
    )
    cy += 30
    body += render_cards_row(
        cy,
        [
            ("INDEXED FUNCTIONS", "IDX", fmt_num(data["indexed_funcs"]), "Unique Keys"),
            ("STORAGE USED", "STD", fmt_bytes(data["storage_bytes"]), "Segment Data"),
            ("SEARCH DOCS", "DOC", fmt_num(data["search_docs"]), "Searchable"),
            ("UNIQUE BINARIES", "BIN", fmt_num(data["unique_binaries"]), "Observed"),
        ],
    )
    cy += ROW_H + SECTION_GAP - 30

    # ── SECTION 1: TRAFFIC ANALYSIS (3 cards) ─────────────────────────────
    body += render_section_header(
        SECTION_X, cy, SECTION_W, "TRAFFIC ANALYSIS", "SEC-001"
    )
    cy += 30
    body += render_cards_row(
        cy,
        [
            (
                "QUERIES PROCESSED",
                "QRY",
                fmt_num(data["queried_funcs"]),
                "Total Lookups",
            ),
            (
                "UPSTREAM RELAY",
                "UPS",
                fmt_num(data["upstream_requests"]),
                "Lumina Requests",
            ),
            (
                "UPSTREAM FETCHED",
                "FTC",
                fmt_num(data["upstream_fetched"]),
                "From Origin",
            ),
        ],
    )
    cy += ROW_H + SECTION_GAP - 30

    # ── SECTION 2: INDEX OPERATIONS (4 cards) ─────────────────────────────
    body += render_section_header(
        SECTION_X, cy, SECTION_W, "INDEX OPERATIONS", "SEC-002"
    )
    cy += 30
    body += render_cards_row(
        cy,
        [
            ("NEW FUNCTIONS", "NEW", fmt_num(data["new_funcs"]), "Unique Indexed"),
            ("PULL OPERATIONS", "PUL", fmt_num(data["pulls"]), "Metadata Syncs"),
            ("PUSH OPERATIONS", "PSH", fmt_num(data["pushes"]), "Submissions"),
            (
                "SCORING BATCHES",
                "SCR",
                fmt_num(data["scoring_batches"]),
                "Version Selection",
            ),
        ],
    )
    cy += ROW_H + SECTION_GAP - 30

    # ── BOTTOM STATUS BAR (2 cells) ───────────────────────────────────────
    bottom_y = cy
    body += f'<rect x="{SECTION_X}" y="{bottom_y}" width="{SECTION_W}" height="{BOTTOM_H}" rx="4" fill="{BOTTOM_BG}" stroke="{BOTTOM_BORDER}" stroke-width="1"/>\n'
    bottom_stats = [
        ("TOTAL RECORDS", fmt_num(data["total_records"]), "+0.00/s"),
        ("VERSIONS SCORED", fmt_num(data["scoring_versions_considered"]), "+0.00/s"),
    ]
    cell_w = SECTION_W // len(bottom_stats)
    for i, (label, val, rate) in enumerate(bottom_stats):
        bx = SECTION_X + i * cell_w
        body += render_bottom_stat(bx, bottom_y, cell_w, label, val, rate=rate)
    cy = bottom_y + BOTTOM_H

    # ── timestamp watermark ───────────────────────────────────────────────
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    uptime = fmt_uptime(data.get("uptime_secs", 0))
    cy += 22
    total_h = cy
    body += f'<text x="{W - 20}" y="{total_h - 2}" font-size="9" fill="{TEXT_TAG}" text-anchor="end" opacity="0.6">Updated {escape(now)} · Uptime {escape(uptime)}</text>\n'

    # ── assemble final SVG ────────────────────────────────────────────────
    header = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {total_h}" width="{W}" height="{total_h}">
<defs>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&amp;display=swap');
    text {{ font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Cascadia Code', monospace; }}
  </style>
  <pattern id="scanlines" width="4" height="4" patternUnits="userSpaceOnUse">
    <rect width="4" height="2" fill="white" opacity="0.008"/>
  </pattern>
</defs>
<rect width="{W}" height="{total_h}" fill="{BG}" rx="8"/>
<rect width="{W}" height="{total_h}" fill="url(#scanlines)" rx="8"/>
'''
    return header + body + "</svg>\n"


# ── entry point ───────────────────────────────────────────────────────────────


def fetch_metrics():
    """Fetch metrics from the API, with TLS verification disabled for self-signed certs."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(API_URL, headers={"User-Agent": "dazhbog-graph/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main():
    output = OUTPUT
    if len(sys.argv) > 1:
        output = sys.argv[1]

    print(f"[dazhbog] Fetching metrics from {API_URL} ...")
    data = fetch_metrics()
    print(f"[dazhbog] Got {len(data)} fields")

    svg = build_svg(data)

    with open(output, "w") as f:
        f.write(svg)
    print(f"[dazhbog] Wrote {output} ({len(svg)} bytes)")


if __name__ == "__main__":
    main()
