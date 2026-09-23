#!/usr/bin/env python3
"""Render a captured terminal transcript (with ANSI colors) as an SVG.

    FORCE_COLOR=1 examples/signed-handoffs/demo.sh > demo.ansi 2>&1
    python3 tools/term-svg.py demo.ansi docs/demo/signed-handoffs.svg --title "..."
    python3 tools/term-svg.py demo.ansi docs/demo/signed-handoffs-full.svg --static

The animated form replays the transcript line by line, paced by what each
line is: a `# ...` narration line pauses, a `$ ...` command line pauses a
little less, and output follows quickly. It loops, holding the last screen.
Nothing is retyped or edited: every character comes from the capture.
Stdlib only, so the docs can be rebuilt anywhere.
"""

from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass

SGR = re.compile(r"\x1b\[([0-9;]*)m")

PALETTE = {
    "bg": "#0e1116",
    "bar": "#1a1f27",
    "fg": "#d5dbe3",
    "dim": "#7d8896",
    "31": "#ff7b72",
    "32": "#7ee787",
    "33": "#f2cc60",
    "36": "#79c0ff",
}

FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', 'Liberation Mono', monospace"
SIZE = 13.5
CHAR_W = 8.13  # advance of a 13.5px monospace glyph, close enough across the stack above
LINE_H = 19
PAD_X = 18
BAR_H = 34
PAD_TOP = 14


@dataclass
class Span:
    text: str
    color: str | None
    bold: bool
    dim: bool


def parse(raw: str) -> list[list[Span]]:
    lines: list[list[Span]] = []
    color, bold, dim = None, False, False
    for line in raw.rstrip("\n").split("\n"):
        spans: list[Span] = []
        pos = 0
        for m in SGR.finditer(line):
            if m.start() > pos:
                spans.append(Span(line[pos : m.start()], color, bold, dim))
            for code in (m.group(1) or "0").split(";"):
                if code in ("", "0"):
                    color, bold, dim = None, False, False
                elif code == "1":
                    bold = True
                elif code == "2":
                    dim = True
                elif code in ("22",):
                    bold = dim = False
                elif code in ("39",):
                    color = None
                elif code in PALETTE:
                    color = code
            pos = m.end()
        if pos < len(line):
            spans.append(Span(line[pos:], color, bold, dim))
        lines.append(spans)
    return lines


def plain(spans: list[Span]) -> str:
    return "".join(s.text for s in spans)


def timeline(lines: list[list[Span]]) -> list[float]:
    """Reveal time in seconds for each line."""
    t, out = 0.6, []
    prev = ""
    for spans in lines:
        text = plain(spans)
        if text.startswith("# "):
            t += 1.5
        elif text.startswith("$ "):
            t += 0.9 if prev.startswith("# ") else 1.3
        elif text.strip() == "":
            pass
        elif prev.startswith("$ "):
            t += 0.55  # the command runs
        else:
            t += 0.08
        out.append(round(t, 2))
        if text.strip():
            prev = text
    return out


def tspan(s: Span) -> str:
    fill = PALETTE["dim"] if s.dim and not s.color else PALETTE.get(s.color or "", PALETTE["fg"])
    attrs = f' fill="{fill}"'
    if s.bold:
        attrs += ' font-weight="700"'
    return f"<tspan{attrs}>{html.escape(s.text, quote=False)}</tspan>"


def render(lines: list[list[Span]], title: str, rows: int | None, static: bool, font: str = FONT) -> str:
    cols = max((len(plain(s)) for s in lines), default=80)
    cols = max(cols, 72)
    n_rows = len(lines) if static or rows is None else min(rows, len(lines))
    width = round(PAD_X * 2 + cols * CHAR_W)
    body_h = PAD_TOP * 2 + n_rows * LINE_H
    height = BAR_H + body_h

    times = timeline(lines)
    hold = 5.0
    total = times[-1] + hold if times else hold

    css: list[str] = []
    text_rows: list[str] = []
    for i, spans in enumerate(lines):
        y = PAD_TOP + (i + 1) * LINE_H - 5
        cls = ""
        if not static:
            cls = f' class="l{i}"'
            p = 100 * times[i] / total
            css.append(
                f"@keyframes k{i}{{0%,{p:.3f}%{{opacity:0}}{p + 0.001:.3f}%,99.5%{{opacity:1}}100%{{opacity:0}}}}"
            )
            css.append(f".l{i}{{opacity:0;animation:k{i} {total:.2f}s step-end infinite}}")
        content = "".join(tspan(s) for s in spans if s.text)
        text_rows.append(f'<text x="{PAD_X}" y="{y}"{cls} xml:space="preserve">{content}</text>')

    scroll = ""
    if not static and len(lines) > n_rows:
        frames = ["0%{transform:translateY(0px)}"]
        for i in range(n_rows, len(lines)):
            p = 100 * times[i] / total
            frames.append(f"{p:.3f}%{{transform:translateY({-(i - n_rows + 1) * LINE_H}px)}}")
        frames.append("100%{transform:translateY(0px)}")
        css.append("@keyframes scroll{" + "".join(frames) + "}")
        css.append(f".scroll{{animation:scroll {total:.2f}s step-end infinite}}")
        scroll = ' class="scroll"'

    if not static:
        css.append(
            "@media (prefers-reduced-motion: reduce){[class^=l],.scroll{animation:none!important;opacity:1!important}}"
        )

    dots = "".join(
        f'<circle cx="{PAD_X + 6 + k * 18}" cy="{BAR_H / 2}" r="5.5" fill="{c}"/>'
        for k, c in enumerate(("#ff5f57", "#febc2e", "#28c840"))
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">'
        f"<title>{html.escape(title)}</title>"
        f"<style>{''.join(css)}</style>"
        f'<rect width="{width}" height="{height}" rx="10" fill="{PALETTE["bg"]}"/>'
        f'<path d="M0 10a10 10 0 0 1 10-10h{width - 20}a10 10 0 0 1 10 10v{BAR_H - 10}h-{width}z" fill="{PALETTE["bar"]}"/>'
        f"{dots}"
        f'<text x="{width / 2}" y="{BAR_H / 2 + 4.5}" text-anchor="middle" fill="{PALETTE["dim"]}" '
        f'font-family="{html.escape(font)}" font-size="12.5">{html.escape(title)}</text>'
        f'<svg x="0" y="{BAR_H}" width="{width}" height="{body_h}" viewBox="0 0 {width} {body_h}">'
        f'<g{scroll} font-family="{html.escape(font)}" font-size="{SIZE}">'
        f"{''.join(text_rows)}"
        "</g></svg></svg>\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("transcript")
    ap.add_argument("out")
    ap.add_argument("--title", default="desk")
    ap.add_argument("--rows", type=int, default=24, help="visible rows in the animated form")
    ap.add_argument("--static", action="store_true", help="every line visible, no animation")
    ap.add_argument("--font", default=FONT, help="font-family (a single installed face renders best to PNG)")
    a = ap.parse_args()
    raw = open(a.transcript, encoding="utf-8").read()
    raw = raw.lstrip("\n")
    svg = render(parse(raw), a.title, a.rows, a.static, a.font)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(svg)


if __name__ == "__main__":
    main()
