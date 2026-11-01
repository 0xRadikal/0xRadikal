#!/usr/bin/env python3
"""Build the profile artwork with the Python standard library.

The original Raydikalx raster mark is embedded unchanged. Only decorative
strokes animate; all text and links remain available in the Markdown.
"""

from base64 import b64encode
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "profile"
WHITE = "#EFF2F9"
ICE = "#EFF2F9"
FONT = "Arial, Helvetica, 'DejaVu Sans', sans-serif"


def text(x, y, value, size, weight=400, color=WHITE, anchor=None, spacing=None):
    extra = f' text-anchor="{anchor}"' if anchor else ""
    if spacing is not None:
        extra += f' letter-spacing="{spacing}"'
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-family="{FONT}" '
        f'font-size="{size}" font-weight="{weight}"{extra}>{escape(value)}</text>'
    )


def start(width, height, title, description):
    stops = (
        '<stop stop-color="#155ACB"/><stop offset=".6" stop-color="#1B62D5"/><stop offset="1" stop-color="#1757C8"/>'
        if width == 720 else
        '<stop stop-color="#165CD0"/><stop offset=".62" stop-color="#1B62D5"/><stop offset=".86" stop-color="#247EFD"/><stop offset="1" stop-color="#1958C6"/>'
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title>
<desc id="desc">{escape(description)}</desc>
<defs>
  <linearGradient id="blue" x1="0" y1="0" x2="1" y2=".8">
    {stops}
  </linearGradient>
  <radialGradient id="light" cx=".35" cy="0" r=".9">
    <stop stop-color="#CAE2FF" stop-opacity=".04"/><stop offset="1" stop-color="#CAE2FF" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="porcelain" x1="0" y1="0" x2=".35" y2="1">
    <stop stop-color="#F7F9FD"/><stop offset=".55" stop-color="#EFF2F9"/><stop offset="1" stop-color="#C8DBF7"/>
  </linearGradient>
  <filter id="soft" x="-40%" y="-40%" width="180%" height="180%" color-interpolation-filters="sRGB">
    <feDropShadow dx="0" dy="8" stdDeviation="8" flood-color="#12489F" flood-opacity=".32"/>
  </filter>
  <clipPath id="canvas"><rect width="{width}" height="{height}" rx="28"/></clipPath>
</defs>
<style>
  .signal {{ animation: travel 12s linear infinite; }}
  @keyframes travel {{ from {{ transform: translateX(0); }} to {{ transform: translateX({width-128}px); }} }}
  @media (prefers-reduced-motion: reduce) {{ .signal {{ animation: none; opacity: 0; }} }}
</style>
<g clip-path="url(#canvas)">
  <rect width="{width}" height="{height}" fill="url(#blue)"/>
  <rect width="{width}" height="{height}" fill="url(#light)"/>
  <rect x="1" y="1" width="{width-2}" height="{height-2}" rx="27" fill="none" stroke="#EFF2F9" stroke-opacity=".18"/>
'''


def finish(name, body):
    (OUT / name).write_text(body + "</g>\n</svg>\n", encoding="utf-8")


def logo(x, y, size):
    encoded = b64encode((OUT / "brand-original.png").read_bytes()).decode("ascii")
    return (
        f'<defs><clipPath id="mark"><rect x="{x}" y="{y}" width="{size}" height="{size}" rx="24"/></clipPath></defs>'
        f'<image x="{x}" y="{y}" width="{size}" height="{size}" '
        f'clip-path="url(#mark)" preserveAspectRatio="xMidYMid meet" href="data:image/png;base64,{encoded}"/>'
    )


def track(width, y):
    return (
        f'<path d="M64 {y}H{width-64}" stroke="{WHITE}" stroke-opacity=".22"/>'
        f'<rect class="signal" x="64" y="{y-1}" width="40" height="2" rx="1" fill="{WHITE}" opacity=".55"/>'
    )


def hero(mobile=False):
    w, h = (720, 760) if mobile else (1200, 430)
    s = start(w, h, "Raydikalx — 0xRadikal", "Mohammad Shirvani. Open networks. Useful tools. Network tooling, Telegram systems and Web3 research.")
    if mobile:
        s += logo(240, 48, 240)
        s += text(360, 338, "RAYDIKALX / BUILDER PORTFOLIO", 16, 700, ICE, "middle", 2)
        s += text(360, 439, "0xRadikal", 92, 700, anchor="middle", spacing=-4)
        s += text(360, 491, "Mohammad Shirvani", 30, color=ICE, anchor="middle")
        s += text(360, 573, "Open networks. Useful tools.", 33, 700, anchor="middle", spacing=-.7)
        s += text(360, 621, "Network tooling · Telegram systems", 23, color=ICE, anchor="middle")
        s += text(360, 656, "Web3 research · Web applications", 23, color=ICE, anchor="middle")
        s += track(w, 710)
    else:
        s += text(64, 62, "RAYDIKALX / BUILDER PORTFOLIO", 14, 700, ICE, spacing=2.2)
        s += text(58, 171, "0xRadikal", 100, 700, spacing=-4.5)
        s += text(64, 219, "Mohammad Shirvani", 27, color=ICE)
        s += text(64, 290, "Open networks. Useful tools.", 37, 700, spacing=-.8)
        s += text(65, 328, "Network tooling · Telegram systems · Web3 research", 20, color=ICE)
        s += logo(856, 62, 280)
        s += track(w, 375)
        s += text(64, 405, "INDEPENDENT BUILDER", 12, 700, ICE, spacing=1.7)
        s += text(1136, 405, "github.com/0xRadikal", 13, color=ICE, anchor="end")
    finish("hero-mobile.svg" if mobile else "hero.svg", s)


def icon(kind, x, y, scale=1):
    if kind == "network":
        paths = '''<path d="M-41 27 0-27 41 27M-34 35H34" fill="none" stroke="url(#porcelain)" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
<g fill="url(#porcelain)"><circle cx="0" cy="-34" r="16"/><circle cx="-44" cy="34" r="16"/><circle cx="44" cy="34" r="16"/></g>'''
    else:
        paths = '''<path d="M-41-38H41Q54-38 54-25V23Q54 36 41 36H-8L-34 53V36H-41Q-54 36-54 23V-25Q-54-38-41-38Z" fill="none" stroke="url(#porcelain)" stroke-width="10" stroke-linejoin="round"/>
<g fill="url(#porcelain)"><circle cx="-24" cy="-1" r="6"/><circle cx="0" cy="-1" r="6"/><circle cx="24" cy="-1" r="6"/></g>'''
    return f'<g transform="translate({x} {y}) scale({scale})" filter="url(#soft)">{paths}</g>'


def project(name, title, eyebrow, detail, kind, mobile=False):
    w, h = (720, 360) if mobile else (1200, 230)
    s = start(w, h, title, detail)
    if mobile:
        s += icon(kind, 102, 104, .78)
        s += text(180, 96, eyebrow, 17, 700, ICE, spacing=1.6)
        s += text(180, 128, "RAYDIKALX / OPEN SOURCE", 14, 700, ICE, spacing=1.3)
        s += text(48, 218, title, 48, 700, spacing=-1.2)
        for j, line in enumerate(detail.split(" | ")):
            s += text(50, 267 + j * 33, line, 23, color=ICE)
        s += '<path d="M646 94h29m-11-11 11 11-11 11" fill="none" stroke="#EFF2F9" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
    else:
        s += icon(kind, 117, 116)
        s += text(227, 58, eyebrow, 14, 700, ICE, spacing=1.8)
        s += text(224, 120, title, 49, 700, spacing=-1.2)
        s += text(228, 160, detail.replace(" | ", " · "), 21, color=ICE)
        s += '<path d="M1080 111h45m-15-15 15 15-15 15" fill="none" stroke="#EFF2F9" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>'
        s += text(228, 200, "RAYDIKALX / OPEN SOURCE", 12, 700, ICE, spacing=1.8)
    finish(f"project-{name}{'-mobile' if mobile else ''}.svg", s)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for mobile in (False, True):
        hero(mobile)
        project("v2ray", "Free V2Ray Configs", "01 / OPEN CONNECTIVITY", "Collect · Test · Publish | Client-ready subscriptions", "network", mobile)
        project("telegram", "Free Telegram Proxy", "02 / TELEGRAM CONNECTIVITY", "Datacenter checks | Proxy lists + dashboard", "chat", mobile)
    print("Built 6 profile SVGs; preserved the original Raydikalx mark.")


if __name__ == "__main__":
    main()
