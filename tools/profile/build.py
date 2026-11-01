#!/usr/bin/env python3
"""Build the profile artwork in assets/profile/.

    python3 tools/profile/build.py            # render SVGs from assets/profile/data.json
    python3 tools/profile/build.py --fetch    # refresh data.json from live sources, then render
    python3 tools/profile/build.py --check    # exit 1 if committed SVGs differ from a fresh render

Why the SVGs look the way they do
---------------------------------
GitHub serves repository images from raw.githubusercontent.com with
``Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox``
and shows them through <img>. Inside that sandbox an SVG cannot load fonts,
scripts or remote images. So every word in the artwork is shaped with HarfBuzz
and written out as vector outlines, the brand mark is embedded byte-for-byte as
a data: PNG, and motion is plain CSS that `prefers-reduced-motion` switches off.

Every number shown is read from a public source by `--fetch`. A source that
fails, or returns something implausible, keeps its last good value instead of
being drawn as 0 - a profile that silently shows "0 stars" would be lying.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html
import io
import json
import math
import os
import re
import sys
import urllib.request

import uharfbuzz as hb
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(REPO, "assets", "profile")
DATA = os.path.join(OUT, "data.json")
FONTS = os.path.join(HERE, "fonts")
BRAND_PNG = os.path.join(OUT, "brand-mark.png")
BRAND_SHA256 = "0ae50d5ae3d7fcb25eb8ca958888f6e984e49f64658d8920b8117bfb5c6a6a5c"

USER = "0xRadikal"
CHANNELS = ("Raydikalx", "crypttopiaa", "TgPriceNft", "v2adikal")

# ─────────────────────────────────────────────────────────────────────────────
# Palette — Raydikalx electric blue (#247EFD) and cool white (#EFF2F9)
# ─────────────────────────────────────────────────────────────────────────────
THEMES = {
    "dark": {
        "bg0": "#050B18", "bg1": "#0A1A3A", "glow": "#1F6BFF", "grid": "#7FA8FF",
        "card": "#0B1730", "stroke": "#1C3463", "ink": "#EEF3FF", "muted": "#93A7CC",
        "quiet": "#5E739A", "accent": "#3D8DFF", "accent2": "#8EC2FF", "chip": "#11244A",
        "chipInk": "#CFE0FF", "root": "#2F7BFF", "pulse": "#BFDCFF",
        "heat": ["#132447", "#173F88", "#1E5FD6", "#3D8DFF", "#A9D0FF"],
        "markShadow": "#000000", "glowOp": "0.55", "dotOp": "0.16", "shadowOp": "0.55",
    },
    "light": {
        "bg0": "#FFFFFF", "bg1": "#EAF2FF", "glow": "#7FB4FF", "grid": "#247EFD",
        "card": "#FFFFFF", "stroke": "#D7E3F5", "ink": "#11203A", "muted": "#53657F",
        "quiet": "#8291AA", "accent": "#247EFD", "accent2": "#1359DF", "chip": "#EEF4FF",
        "chipInk": "#1A4FB8", "root": "#247EFD", "pulse": "#0D47B8",
        "heat": ["#E7EEF9", "#BCD5FF", "#7EAEFF", "#247EFD", "#0D47B8"],
        "markShadow": "#12489F", "glowOp": "0.42", "dotOp": "0.13", "shadowOp": "0.30",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Type — shaped by HarfBuzz, emitted as outlines
# ─────────────────────────────────────────────────────────────────────────────


class Typeface:
    def __init__(self, filename: str):
        font = TTFont(os.path.join(FONTS, filename))
        self.variable = "fvar" in font
        font.flavor = None
        buf = io.BytesIO()
        font.save(buf)
        self.face = hb.Face(buf.getvalue())
        self.font = hb.Font(self.face)
        self.upem = self.face.upem
        self.cmap = font.getBestCmap()

    def covers(self, text: str) -> bool:
        return all(ord(ch) in self.cmap or ch.isspace() for ch in text)

    def shape(self, text: str, size: float, weight: float | None, tracking: float):
        if self.variable and weight is not None:
            self.font.set_variations({"wght": weight})
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.font, buf, {"kern": True, "liga": True})
        scale = size / self.upem
        glyphs, x = [], 0.0
        track = tracking * size
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            glyphs.append((info.codepoint, x + pos.x_offset * scale, pos.y_offset * scale))
            x += pos.x_advance * scale + track
        width = x - track if glyphs else 0.0
        return glyphs, width, scale


def _n(v: float) -> str:
    s = f"{v:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
    return "0" if s == "-0" else s


class _PathPen:
    def __init__(self, ox: float, oy: float, scale: float):
        self.ox, self.oy, self.s = ox, oy, scale
        self.out: list[str] = []

    def _p(self, pt):
        return f"{_n(self.ox + pt[0] * self.s)} {_n(self.oy - pt[1] * self.s)}"

    def moveTo(self, pt):
        self.out.append("M" + self._p(pt))

    def lineTo(self, pt):
        self.out.append("L" + self._p(pt))

    def qCurveTo(self, *pts):
        # TrueType allows implied on-curve points between consecutive controls.
        *ctrls, end = pts
        for i, c in enumerate(ctrls):
            if i < len(ctrls) - 1:
                nxt = ctrls[i + 1]
                mid = ((c[0] + nxt[0]) / 2, (c[1] + nxt[1]) / 2)
                self.out.append("Q" + self._p(c) + " " + self._p(mid))
            else:
                self.out.append("Q" + self._p(c) + " " + self._p(end))

    def curveTo(self, *pts):
        c1, c2, end = pts
        self.out.append("C" + self._p(c1) + " " + self._p(c2) + " " + self._p(end))

    def closePath(self):
        self.out.append("Z")

    endPath = closePath


FACES: dict[str, Typeface] = {}
GLYPHS: dict[str, str] = {}  # glyph outlines used by the document being built


def face(name: str) -> Typeface:
    files = {
        "sans": "manrope-latin.woff2",
        "mono": "jetbrainsmono-medium.woff2",
        "monob": "jetbrainsmono-bold.woff2",
        "fa": "estedad-arabic.woff2",
    }
    if name not in FACES:
        FACES[name] = Typeface(files[name])
    return FACES[name]


def measure(text: str, font: str, size: float, weight: float | None = None, tracking: float = 0.0) -> float:
    return face(font).shape(text, size, weight, tracking)[1]


def text(txt: str, x: float, y: float, *, font: str = "sans", size: float = 20, weight: float | None = None,
         fill: str = "ink", anchor: str = "start", tracking: float = 0.0, cls: str = "",
         opacity: float | None = None) -> str:
    tf = face(font)
    if not tf.covers(txt):
        missing = sorted({ch for ch in txt if ord(ch) not in tf.cmap and not ch.isspace()})
        raise SystemExit(f"build: font {font!r} has no glyph for {missing} in {txt!r}")
    glyphs, width, scale = tf.shape(txt, size, weight, tracking)
    ox = x - (width / 2 if anchor == "middle" else width if anchor == "end" else 0)
    uses = []
    for gid, gx, gy in glyphs:
        key = f"{font}{int(weight or 0)}-{gid}"
        if key not in GLYPHS:
            pen = _PathPen(0, 0, 1)  # font units, y flipped; placed by the <g> transform
            tf.font.draw_glyph_with_pen(gid, pen)
            GLYPHS[key] = "".join(pen.out)
        if GLYPHS[key]:
            uses.append(f'<use href="#{key}" x="{_n(gx / scale)}" y="{_n(-gy / scale)}"/>')
    if not uses:
        return ""
    klass = f' class="{cls}"' if cls else ""
    op = f' opacity="{opacity}"' if opacity is not None else ""
    return (f'<g{klass} fill="{col(fill)}"{op} transform="translate({_n(ox)} {_n(y)}) scale({scale:.5g})">'
            + "".join(uses) + "</g>")


def fmt(n: int) -> str:
    return f"{n:,}"


# ─────────────────────────────────────────────────────────────────────────────
# Data — fetched from public sources, fail-closed
# ─────────────────────────────────────────────────────────────────────────────

UA = {"User-Agent": "0xRadikal-profile-builder (+https://github.com/0xRadikal/0xRadikal)"}


def _get(url: str, token: str | None = None, timeout: int = 30) -> bytes:
    headers = dict(UA)
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/vnd.github+json"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        if res.status != 200:
            raise RuntimeError(f"HTTP {res.status} for {url}")
        return res.read()


def _json(url: str, token: str | None = None):
    return json.loads(_get(url, token).decode("utf-8"))


def _pos_int(v, name: str, minimum: int = 0) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ValueError(f"{name}: implausible value {v!r}")
    return v


def fetch_github(token):
    user = _json(f"https://api.github.com/users/{USER}", token)
    repos, page = [], 1
    while True:
        batch = _json(f"https://api.github.com/users/{USER}/repos?per_page=100&type=owner&page={page}", token)
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    own = [r for r in repos if not r.get("fork") and not r.get("private")]
    stars = {r["name"]: r["stargazers_count"] for r in own}
    out = {
        "followers": _pos_int(user.get("followers"), "followers"),
        "public_repos": _pos_int(len(own), "public repos", 1),
        "stars_total": _pos_int(sum(stars.values()), "stars total", 1),
        "stars": {k: _pos_int(stars.get(k), f"stars[{k}]") for k in ("Free-v2ray-Configs", "Free-Telegram-Proxy")},
    }
    return out


def fetch_v2ray():
    idx = _json("https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/index.json")
    return {
        "verified": _pos_int(idx["cascade_categories"]["verified"]["unique"], "v2ray verified", 1),
        "countries": _pos_int(idx["countries"]["count"], "v2ray countries", 1),
        "interval_min": _pos_int(idx["update_interval_minutes"], "v2ray interval", 1),
    }


def fetch_mtproto():
    idx = _json("https://raw.githubusercontent.com/0xRadikal/Free-Telegram-Proxy/main/index.json")
    f = idx["funnel"]
    out = {
        "collected": _pos_int(f["links_collected"], "mtproto collected", 1),
        "dns_ok": _pos_int(f["dns_ok"], "mtproto dns ok", 1),
        "tcp_ok": _pos_int(f["tcp_ok"], "mtproto tcp ok", 1),
        "dc_ok": _pos_int(f["dc_ok_any_round"], "mtproto dc ok", 1),
        "verified_links": _pos_int(f["verified_links"], "mtproto verified links", 1),
        "verified_servers": _pos_int(f["verified_servers"], "mtproto verified servers", 1),
    }
    steps = [out[k] for k in ("collected", "dns_ok", "tcp_ok", "dc_ok", "verified_links")]
    if steps != sorted(steps, reverse=True):
        raise ValueError(f"mtproto funnel is not monotonic: {steps}")
    return out


def fetch_channel(name: str) -> int:
    page = _get(f"https://t.me/{name}").decode("utf-8", "replace")
    m = re.search(r'<div class="tgme_page_extra">\s*([\d\s\u00a0\u202f]+)\s+(?:subscribers|members)', page)
    if not m:
        raise ValueError(f"t.me/{name}: subscriber count not found")
    return _pos_int(int(re.sub(r"\D", "", m.group(1))), f"t.me/{name}", 1)


_ORD = re.compile(r"(\d+)(st|nd|rd|th)")


def fetch_contributions():
    page = _get(f"https://github.com/users/{USER}/contributions").decode("utf-8", "replace")
    m = re.search(r"<h2[^>]*>\s*([\d,]+)\s+contributions?\s+in the last year", page, re.S)
    if not m:
        raise ValueError("contribution total not found")
    total = int(m.group(1).replace(",", ""))
    cells = re.findall(r'data-date="(\d{4}-\d\d-\d\d)" id="contribution-day-component-(\d)-(\d+)" data-level="(\d)"', page)
    tips = dict(re.findall(r'<tool-tip[^>]*for="(contribution-day-component-\d-\d+)"[^>]*>([^<]*)</tool-tip>', page))
    days = []
    for date, row, col, level in cells:
        tip = tips.get(f"contribution-day-component-{row}-{col}", "")
        cm = re.match(r"\s*(No|\d+) contributions?", tip)
        if not cm:
            raise ValueError(f"no count for {date}")
        count = 0 if cm.group(1) == "No" else int(cm.group(1))
        days.append([date, int(row), int(col), int(level), count])
    days.sort(key=lambda d: d[0])
    if not 360 <= len(days) <= 372:
        raise ValueError(f"unexpected calendar length {len(days)}")
    if sum(d[4] for d in days) != total:
        raise ValueError(f"day counts sum to {sum(d[4] for d in days)}, header says {total}")
    return {"total": total, "days": days}


def refresh(prev: dict) -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    data = json.loads(json.dumps(prev))  # deep copy
    jobs = {
        "github": lambda: fetch_github(token),
        "v2ray": fetch_v2ray,
        "mtproto": fetch_mtproto,
        "contributions": fetch_contributions,
    }
    failed = []
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    synced = data.setdefault("synced", {})
    for key, job in jobs.items():
        try:
            data[key] = job()
            synced[key] = today
            print(f"fetch: {key:<14} ok")
        except Exception as exc:  # noqa: BLE001 - every failure keeps the last good value
            failed.append(key)
            print(f"fetch: {key:<14} FAILED ({exc}) - keeping last good value")
    tg = dict(data.get("telegram", {}))
    for ch in CHANNELS:
        try:
            tg[ch] = fetch_channel(ch)
            synced[f"t.me/{ch}"] = today
            print(f"fetch: t.me/{ch:<10} ok")
        except Exception as exc:  # noqa: BLE001
            failed.append(f"t.me/{ch}")
            print(f"fetch: t.me/{ch:<10} FAILED ({exc}) - keeping last good value")
    data["telegram"] = tg
    for key in ("github", "v2ray", "mtproto", "contributions"):
        if key not in data:
            raise SystemExit(f"build: no data for {key!r} and no previous value - refusing to render")
    for ch in CHANNELS:
        if ch not in tg:
            raise SystemExit(f"build: no data for t.me/{ch} and no previous value - refusing to render")
    if failed:
        print(f"fetch: {len(failed)} source(s) kept their previous value: {', '.join(failed)}")
    return data


def contribution_stats(days):
    counts = [d[4] for d in days]
    active = sum(1 for c in counts if c > 0)
    longest = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)
    i = len(counts) - 1
    if i >= 0 and counts[i] == 0:
        i -= 1  # today may simply not have started yet
    current = 0
    while i >= 0 and counts[i] > 0:
        current += 1
        i -= 1
    best = max(days, key=lambda d: (d[4], d[0]))
    return {"active": active, "longest": longest, "current": current, "best_count": best[4], "best_date": best[0]}


def pretty_date(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')} {d.year}"


# ─────────────────────────────────────────────────────────────────────────────
# Composition
# ─────────────────────────────────────────────────────────────────────────────

CUR: dict = THEMES["dark"]


def col(name: str) -> str:
    return CUR[name] if name in CUR else name


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def rect(x, y, w, h, rx=0, fill="card", stroke=None, sw=1.0, opacity=None, extra="") -> str:
    s = f' stroke="{col(stroke)}" stroke-width="{_n(sw)}"' if stroke else ""
    o = f' opacity="{opacity}"' if opacity is not None else ""
    r = f' rx="{_n(rx)}"' if rx else ""
    return f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}"{r} fill="{col(fill)}"{s}{o}{extra}/>'


def star(cx, cy, r, fill="accent") -> str:
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append(f"{_n(cx + rr * math.cos(a))},{_n(cy + rr * math.sin(a))}")
    return f'<polygon fill="{col(fill)}" stroke="{col(fill)}" stroke-width="{_n(r * 0.18)}" stroke-linejoin="round" points="{" ".join(pts)}"/>'


def chip(x, y, label, *, size=12.5, h=30, fill="chip", ink="chipInk", stroke="stroke", font="monob", tracking=0.06):
    w = measure(label, font, size, tracking=tracking) + 26
    out = rect(x, y, w, h, h / 2, fill, stroke, 1)
    out += text(label, x + 13, y + h / 2 + size * 0.36, font=font, size=size, fill=ink, tracking=tracking)
    return out, w


def wrap(txt: str, font: str, size: float, maxw: float, weight=None) -> list[str]:
    lines, cur = [], ""
    for word in txt.split():
        trial = f"{cur} {word}".strip()
        if cur and measure(trial, font, size, weight) > maxw:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


_BRAND_URI = ""


def brand_uri() -> str:
    global _BRAND_URI
    if not _BRAND_URI:
        raw = open(BRAND_PNG, "rb").read()
        if hashlib.sha256(raw).hexdigest() != BRAND_SHA256:
            raise SystemExit("build: brand-mark.png is not the original Raydikalx mark (sha256 mismatch)")
        _BRAND_URI = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    return _BRAND_URI


def brand(x, y, s, cid="mk") -> str:
    """The original mark, byte-for-byte, in an app-icon squircle with a soft shadow."""
    r = s * 0.24
    return (
        f'<g filter="url(#sh)"><rect x="{_n(x)}" y="{_n(y)}" width="{_n(s)}" height="{_n(s)}" rx="{_n(r)}" fill="#247EFD"/></g>'
        f'<clipPath id="{cid}"><rect x="{_n(x)}" y="{_n(y)}" width="{_n(s)}" height="{_n(s)}" rx="{_n(r)}"/></clipPath>'
        f'<image clip-path="url(#{cid})" x="{_n(x)}" y="{_n(y)}" width="{_n(s)}" height="{_n(s)}" href="{brand_uri()}"/>'
    )


BASE_CSS = """
.pulse{animation:pulse 2.4s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
.blink{animation:blink 1.1s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
.spin{transform-box:fill-box;transform-origin:center;animation:spin 28s linear infinite}
.spin.r{animation-direction:reverse;animation-duration:40s}
@keyframes spin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
"""


def doc(w, h, title, desc, body, *, css="", defs="", rx=24) -> str:
    T = CUR
    defs = "".join(f'<path id="{k}" d="{d}"/>' for k, d in sorted(GLYPHS.items()) if d) + defs
    GLYPHS.clear()
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-labelledby="t d" fill="none">'
        f'<title id="t">{esc(title)}</title><desc id="d">{esc(desc)}</desc>'
        f'<defs>'
        f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{T["bg0"]}"/><stop offset="1" stop-color="{T["bg1"]}"/></linearGradient>'
        f'<radialGradient id="gl"><stop stop-color="{T["glow"]}" stop-opacity="{T["glowOp"]}"/><stop offset="1" stop-color="{T["glow"]}" stop-opacity="0"/></radialGradient>'
        f'<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.1" fill="{T["grid"]}" opacity="{T["dotOp"]}"/></pattern>'
        f'<filter id="sh" x="-40%" y="-40%" width="180%" height="190%" color-interpolation-filters="sRGB">'
        f'<feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="{T["markShadow"]}" flood-opacity="{T["shadowOp"]}"/></filter>'
        f'<clipPath id="cv"><rect width="{w}" height="{h}" rx="{rx}"/></clipPath>'
        f'{defs}</defs>'
        f'<style>{BASE_CSS}{css}</style>'
        f'<g clip-path="url(#cv)">'
        f'<rect width="{w}" height="{h}" fill="url(#bg)"/><rect width="{w}" height="{h}" fill="url(#dots)"/>'
        f'{body}</g>'
        f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="{rx}" stroke="{T["stroke"]}"/>'
        f'</svg>\n'
    )


def glow(cx, cy, rx, ry=None) -> str:
    return f'<ellipse cx="{_n(cx)}" cy="{_n(cy)}" rx="{_n(rx)}" ry="{_n(ry or rx)}" fill="url(#gl)"/>'


def polyline_len(pts) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def radical(pts, width, cls_len) -> str:
    """The radical sign (√) as a stroke, with a signal pulse running along it."""
    d = "M" + " L".join(f"{_n(x)} {_n(y)}" for x, y in pts)
    L = polyline_len(pts)
    return (
        f'<path d="{d}" stroke="{col("root")}" stroke-width="{_n(width)}" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<path class="{cls_len}" d="{d}" stroke="{col("pulse")}" stroke-width="{_n(width * 0.55)}" '
        f'stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="70 {_n(L + 70)}" stroke-dashoffset="70"/>'
    ), L


def trace_css(cls, L, dur) -> str:
    return (f".{cls}{{animation:{cls} {dur}s cubic-bezier(.5,0,.3,1) infinite}}"
            f"@keyframes {cls}{{0%{{stroke-dashoffset:70}}70%,100%{{stroke-dashoffset:{_n(-L)}}}}}")


TAGLINE = "Open networks. Verified, not promised."
ROLE = "Mohammad Shirvani  ·  building open-network tools under Raydikalx"
HERO_CHIPS = ("PROXY PIPELINES", "TELEGRAM BOTS", "PYTHON · TYPESCRIPT", "WEB3 RESEARCH")


def hero(data, mobile=False) -> str:
    title = "0xRadikal — Mohammad Shirvani, Raydikalx"
    desc = (f"The radical sign √ drawn over the name 0xRadikal, the Raydikalx Root-R mark, and the line "
            f"'{TAGLINE}'")
    b = []
    if not mobile:
        W, H = 1200, 430
        b.append(glow(1010, 190, 330, 260))
        b.append(glow(220, 470, 420, 200))
        b.append(text("RAYDIKALX  ·  TEHRAN  ·  OPEN SOURCE", 64, 64, font="monob", size=13, fill="quiet", tracking=0.18))
        size, tx, base = 108, 222, 222
        wm, tw = wordmark(tx, base, size)
        top = base - size * 0.86
        pts = [(64, base - 44), (92, base - 58), (136, base + 18), (192, top), (tx + tw + 34, top)]
        r, L = radical(pts, 9, "tr")
        b.append(r)
        b.append(wm)
        b.append(text(ROLE, 66, 286, size=23, weight=600, fill="muted"))
        b.append(text("$", 66, 336, font="monob", size=20, fill="accent"))
        b.append(text(TAGLINE, 92, 336, font="mono", size=20, fill="ink"))
        cx = 92 + measure(TAGLINE, "mono", 20) + 6
        b.append(rect(cx, 318, 11, 22, 1.5, "accent", extra=' class="blink"'))
        x = 66
        for lab in HERO_CHIPS:
            c, w = chip(x, 364, lab)
            b.append(c)
            x += w + 10
        # mark + orbits
        mx, my, ms = 940, 112, 150
        cxm, cym = mx + ms / 2, my + ms / 2
        b.append(f'<circle class="spin" cx="{_n(cxm)}" cy="{_n(cym)}" r="122" stroke="{col("accent")}" stroke-opacity=".55" stroke-width="1.5" stroke-dasharray="2 9" stroke-linecap="round"/>')
        b.append(f'<circle class="spin r" cx="{_n(cxm)}" cy="{_n(cym)}" r="158" stroke="{col("accent2")}" stroke-opacity=".35" stroke-width="1.2" stroke-dasharray="70 30 6 30"/>')
        b.append(f'<g class="spin"><circle cx="{_n(cxm + 122)}" cy="{_n(cym)}" r="5" fill="{col("accent")}"/></g>'.replace(
            'class="spin"', f'class="spin" style="transform-origin:{_n(cxm)}px {_n(cym)}px;transform-box:view-box"'))
        b.append(brand(mx, my, ms))
        b.append(text("رِیدیکال", cxm, my + ms + 60, font="fa", size=26, weight=None, fill="muted", anchor="middle"))
        css = trace_css("tr", L, 7)
    else:
        W, H = 600, 560
        b.append(glow(470, 110, 220, 180))
        b.append(brand(40, 44, 84))
        b.append(text("RAYDIKALX", 142, 78, font="monob", size=13, fill="accent", tracking=0.2))
        b.append(text("TEHRAN  ·  OPEN SOURCE", 142, 104, font="monob", size=12, fill="quiet", tracking=0.16))
        size, tx, base = 76, 130, 262
        wm, tw = wordmark(tx, base, size)
        top = base - size * 0.86
        pts = [(40, base - 30), (60, base - 40), (88, base + 12), (122, top), (tx + tw + 20, top)]
        r, L = radical(pts, 7, "tr")
        b.append(r)
        b.append(wm)
        b.append(text("Mohammad Shirvani", 42, 318, size=24, weight=700, fill="ink"))
        b.append(text("building open-network tools under Raydikalx", 42, 350, size=19, weight=600, fill="muted"))
        y = 404
        for i, line in enumerate(("Open networks.", "Verified, not promised.")):
            if i == 0:
                b.append(text("$", 42, y, font="monob", size=19, fill="accent"))
            b.append(text(line, 66, y + i * 30, font="mono", size=19))
        cx = 66 + measure("Verified, not promised.", "mono", 19) + 6
        b.append(rect(cx, y + 30 - 17, 10, 21, 1.5, "accent", extra=' class="blink"'))
        x, y = 42, 468
        for lab in HERO_CHIPS:
            w = measure(lab, "monob", 12, tracking=0.06) + 26
            if x + w > W - 40:
                x, y = 42, y + 40
            c, w = chip(x, y, lab, size=12)
            b.append(c)
            x += w + 10
        css = trace_css("tr", L, 7)
    return doc(W, H, title, desc, "".join(b), css=css)


def wordmark(x, base, size) -> tuple[str, float]:
    """'0x' in JetBrains Mono (dotted zero, accent) + 'Radikal' in Manrope ExtraBold."""
    ms = size * 0.92
    w0 = measure("0x", "monob", ms, tracking=-0.04)
    gap = size * 0.04
    w1 = measure("Radikal", "sans", size, 800, -0.02)
    out = text("0x", x, base, font="monob", size=ms, fill="accent", tracking=-0.04)
    out += text("Radikal", x + w0 + gap, base, size=size, weight=800, tracking=-0.02)
    return out, w0 + gap + w1


def section_head(x, y, eyebrow, right=None, W=1200, pad=56, live=True) -> str:
    out = text(eyebrow, x, y, font="monob", size=13, fill="accent", tracking=0.18)
    if right:
        rw = measure(right, "monob", 12, tracking=0.12)
        rx = W - pad - rw
        out += text(right, rx, y, font="monob", size=12, fill="quiet", tracking=0.12)
        if live:
            out += f'<circle class="pulse" cx="{_n(rx - 14)}" cy="{_n(y - 4.5)}" r="4.5" fill="{col("accent")}"/>'
    return out


def stats(data, mobile=False) -> str:
    g, v, m, tg = data["github"], data["v2ray"], data["mtproto"], data["telegram"]
    reach = sum(tg[c] for c in CHANNELS)
    sync = max(data.get("synced", {}).values(), default="")
    tiles = [
        ("star", fmt(g["stars_total"]), "GitHub stars", f"across {g['public_repos']} public repositories"),
        ("dot", fmt(v["verified"]), "verified V2Ray configs", f"{v['countries']} countries · rebuilt every {v['interval_min']} min"),
        ("dot", fmt(m["verified_links"]), "MTProto proxies proven 3×", f"on {fmt(m['verified_servers'])} distinct servers"),
        ("dot", fmt(reach), "Telegram subscriptions", f"across {len(CHANNELS)} channels and groups"),
    ]
    title = "Signal report — live numbers from 0xRadikal's projects"
    desc = "; ".join(f"{t[1]} {t[2]} ({t[3]})" for t in tiles) + (f". Last synced {sync}." if sync else ".")
    b = []
    if not mobile:
        W, H, pad = 1200, 250, 56
        b.append(glow(140, 260, 360, 160))
        b.append(section_head(pad, 58, "SIGNAL REPORT", f"LIVE · SYNCED {sync}" if sync else "LIVE", W, pad))
        tw = (W - 2 * pad - 3 * 16) / 4
        for i, (icon, big, lab, sub) in enumerate(tiles):
            x, y = pad + i * (tw + 16), 84
            b.append(rect(x, y, tw, 128, 18, "card", "stroke", 1, opacity=None))
            b.append(text(big, x + 22, y + 60, size=40, weight=800, tracking=-0.02))
            bw = measure(big, "sans", 40, 800, -0.02)
            if icon == "star":
                b.append(star(x + 22 + bw + 18, y + 45, 10))
            else:
                b.append(f'<circle class="pulse" cx="{_n(x + 22 + bw + 14)}" cy="{_n(y + 48)}" r="4.5" fill="{col("accent")}"/>')
            b.append(text(lab, x + 22, y + 88, size=16, weight=700, fill="ink"))
            b.append(text(sub, x + 22, y + 110, size=13, weight=600, fill="muted"))
    else:
        W, H, pad = 600, 400, 32
        b.append(section_head(pad, 50, "SIGNAL REPORT", f"SYNCED {sync}" if sync else "LIVE", W, pad))
        tw = (W - 2 * pad - 12) / 2
        for i, (icon, big, lab, sub) in enumerate(tiles):
            x, y = pad + (i % 2) * (tw + 12), 74 + (i // 2) * 158
            b.append(rect(x, y, tw, 146, 18, "card", "stroke", 1))
            b.append(text(big, x + 20, y + 54, size=36, weight=800, tracking=-0.02))
            bw = measure(big, "sans", 36, 800, -0.02)
            if icon == "star":
                b.append(star(x + 20 + bw + 16, y + 41, 9))
            else:
                b.append(f'<circle class="pulse" cx="{_n(x + 20 + bw + 12)}" cy="{_n(y + 43)}" r="4" fill="{col("accent")}"/>')
            for j, line in enumerate(wrap(lab, "sans", 15, tw - 36, 700)[:2]):
                b.append(text(line, x + 20, y + 84 + j * 20, size=15, weight=700))
            for j, line in enumerate(wrap(sub, "sans", 12.5, tw - 36, 600)[:2]):
                b.append(text(line, x + 20, y + 112 + j * 17 + (0 if len(wrap(lab, "sans", 15, tw - 36, 700)) < 2 else 6), size=12.5, weight=600, fill="muted"))
    return doc(W, H, title, desc, "".join(b))


def heatmap(data, mobile=False) -> str:
    c = data["contributions"]
    days = c["days"]
    heat = CUR["heat"]
    cols = sorted({d[2] for d in days})
    if mobile:
        cols = cols[-26:]
    keep = [d for d in days if d[2] in cols]
    st = contribution_stats(keep)
    yst = contribution_stats(days)
    c0 = cols[0]
    title = f"{fmt(c['total'])} contributions in the last year"
    desc = (f"GitHub contribution calendar for 0xRadikal: {fmt(c['total'])} contributions in the last year, "
            f"{yst['active']} active days, longest streak {yst['longest']} days, best day {yst['best_count']} "
            f"contributions on {pretty_date(yst['best_date'])}."
            + (f" This view shows the last 26 weeks: {fmt(sum(d[4] for d in keep))} contributions." if mobile else ""))
    W, pad = (1200, 56) if not mobile else (600, 32)
    step = (W - 2 * pad + 4) / len(cols)
    cell = step - 4
    b = [glow(W - 160, -20, 360, 200)]
    b.append(section_head(pad, 58 if not mobile else 50, "CONTRIBUTION SIGNAL", "LAST 12 MONTHS" if not mobile else "LAST 26 WEEKS", W, pad, live=False))
    total_txt = fmt(c["total"]) if not mobile else fmt(sum(d[4] for d in keep))
    b.append(text(total_txt, pad, 118 if not mobile else 108, size=46 if not mobile else 40, weight=800, tracking=-0.02))
    tw = measure(total_txt, "sans", 46 if not mobile else 40, 800, -0.02)
    b.append(text("contributions", pad + tw + 14, 118 if not mobile else 108, size=19 if not mobile else 17, weight=700, fill="muted"))
    gy = 168 if not mobile else 152
    # month labels at the first column where a month starts
    seen = set()
    for d in keep:
        date = dt.date.fromisoformat(d[0])
        key = (date.year, date.month)
        if date.day <= 7 and d[1] == 0 and key not in seen:
            seen.add(key)
            x = pad + (d[2] - c0) * step
            if x < W - pad - 24:
                b.append(text(date.strftime("%b").upper(), x, gy - 12, font="mono", size=11, fill="quiet", tracking=0.08))
    last = days[-1][0]
    for d in keep:
        x, y = pad + (d[2] - c0) * step, gy + d[1] * step
        extra = ' class="pulse"' if d[0] == last and d[4] > 0 else ""
        b.append(f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(cell)}" height="{_n(cell)}" rx="{_n(cell * 0.24)}" fill="{heat[d[3]]}"{extra}/>')
    sy = gy + 7 * step + 34
    facts = [
        (fmt(st["active"]), "active days"),
        (f"{st['longest']} days", "longest streak"),
        (f"{st['current']} days", "current streak"),
        (fmt(st["best_count"]), f"best day · {pretty_date(st['best_date'])}"),
    ]
    if mobile:
        facts = facts[:2] + facts[3:]
    fx = pad
    for big, lab in facts:
        b.append(text(big, fx, sy, size=20, weight=800))
        bw = measure(big, "sans", 20, 800)
        b.append(text(lab, fx + bw + 8, sy, size=13.5, weight=600, fill="muted"))
        fx += bw + 8 + measure(lab, "sans", 13.5, 600) + (34 if not mobile else 20)
    if not mobile:
        lx = W - pad - (5 * 16 + 4 * 4) - 44
        b.append(text("less", lx - 40, sy - 1, font="mono", size=11, fill="quiet"))
        for i, hcol in enumerate(heat):
            b.append(f'<rect x="{_n(lx + i * 20)}" y="{_n(sy - 13)}" width="16" height="16" rx="4" fill="{hcol}"/>')
        b.append(text("more", lx + 5 * 20 + 6, sy - 1, font="mono", size=11, fill="quiet"))
    H = sy + 36
    return doc(W, int(H), title, desc, "".join(b))


def card_frame(W, H, pad, eyebrow, title_txt, stars, lines, chips, mobile):
    """Left column of a project card: eyebrow, title, star count, description, stack chips."""
    b = [section_head(pad, 54 if not mobile else 48, eyebrow, None, W, pad)]
    ty = 104 if not mobile else 96
    tsize = 38 if not mobile else 32
    b.append(text(title_txt, pad, ty, size=tsize, weight=800, tracking=-0.015))
    if stars is not None:
        tw = measure(title_txt, "sans", tsize, 800, -0.015)
        sx = pad + tw + 18
        s = fmt(stars)
        cw = measure(s, "monob", 14) + 46
        b.append(rect(sx, ty - 26, cw, 30, 15, "chip", "stroke", 1))
        b.append(star(sx + 17, ty - 11, 7.5))
        b.append(text(s, sx + 31, ty - 6, font="monob", size=14, fill="chipInk"))
    y = ty + (38 if not mobile else 34)
    for line in lines:
        b.append(text(line, pad, y, size=17 if not mobile else 16, weight=600, fill="muted"))
        y += 27 if not mobile else 25
    y += 14
    x = pad
    for lab in chips:
        w = measure(lab, "monob", 12, tracking=0.06) + 26
        if mobile and x + w > W - pad:
            x, y = pad, y + 40
        c, w = chip(x, y, lab, size=12)
        b.append(c)
        x += w + 10
    return "".join(b), y + 30


def card_v2ray(data, mobile=False):
    v, g = data["v2ray"], data["github"]
    stars = g["stars"]["Free-v2ray-Configs"]
    desc_txt = ("Collects public V2Ray / Xray configs, removes duplicates and sends a real request through "
                "every one of them. Only the ones that answer in all three rounds reach the verified list.")
    title = "Free V2Ray Configs"
    desc = (f"{title}: {fmt(stars)} stars. {desc_txt} Currently {fmt(v['verified'])} verified configs from "
            f"{v['countries']} countries, rebuilt every {v['interval_min']} minutes.")
    W, pad = (1200, 56) if not mobile else (600, 32)
    lw = 600 if not mobile else W - 2 * pad
    lines = wrap(desc_txt, "sans", 17 if not mobile else 16, lw, 600)
    left, ly = card_frame(W, 0, pad, "FLAGSHIP  ·  01", title, stars, lines,
                          ("PYTHON", "GITHUB ACTIONS", "XRAY · SING-BOX · MIHOMO"), mobile)
    b = [glow(W - 200 if not mobile else W - 100, 40, 320, 220), left]
    # three test rounds -> verified
    if not mobile:
        ox, oy, H = 760, 70, 330
    else:
        ox, oy = pad, ly + 10
        H = int(oy + 230)
    rw = (W - pad - ox) if not mobile else W - 2 * pad
    b.append(rect(ox, oy, rw, 230, 20, "card", "stroke", 1))
    b.append(text("EVERY CONFIG, EVERY RUN", ox + 24, oy + 36, font="monob", size=11.5, fill="quiet", tracking=0.14))
    nodes = ["ROUND 1", "ROUND 2", "ROUND 3"]
    span = rw - 48
    for i, lab in enumerate(nodes):
        cx = ox + 24 + 22 + i * (span - 44) / 2
        cy = oy + 84
        if i < 2:
            nx = ox + 24 + 22 + (i + 1) * (span - 44) / 2
            b.append(f'<line x1="{_n(cx + 24)}" y1="{_n(cy)}" x2="{_n(nx - 24)}" y2="{_n(cy)}" stroke="{col("stroke")}" stroke-width="2"/>')
            b.append(f'<line class="flow" style="animation-delay:{i * 0.6:.1f}s" x1="{_n(cx + 24)}" y1="{_n(cy)}" x2="{_n(nx - 24)}" y2="{_n(cy)}" '
                     f'stroke="{col("accent")}" stroke-width="2.4" stroke-linecap="round" stroke-dasharray="14 400"/>')
        b.append(f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="20" fill="{col("chip")}" stroke="{col("accent")}" stroke-width="1.6"/>')
        b.append(text("✓", cx, cy + 6.5, font="monob", size=18, fill="accent", anchor="middle"))
        b.append(text(lab, cx, cy + 44, font="monob", size=11, fill="muted", anchor="middle", tracking=0.08))
    big = fmt(v["verified"])
    b.append(text(big, ox + 24, oy + 190, size=44, weight=800, tracking=-0.02))
    bw = measure(big, "sans", 44, 800, -0.02)
    b.append(text("verified now", ox + 24 + bw + 12, oy + 170, size=14, weight=700, fill="ink"))
    b.append(text(f"{v['countries']} countries · every {v['interval_min']} min", ox + 24 + bw + 12, oy + 190, size=13, weight=600, fill="muted"))
    css = (".flow{animation:flow 2.4s linear infinite}"
           "@keyframes flow{from{stroke-dashoffset:14}to{stroke-dashoffset:-400}}")
    H = 330 if not mobile else H + 32
    return doc(W, int(H), title, desc, "".join(b), css=css)


def card_mtproto(data, mobile=False):
    m, g = data["mtproto"], data["github"]
    stars = g["stars"]["Free-Telegram-Proxy"]
    title = "Free Telegram Proxy"
    desc_txt = ("An MTProto proxy index. A proxy is published only after it relays a real request to a "
                "Telegram datacenter and returns our nonce, in all three rounds.")
    steps = [("collected", m["collected"]), ("DNS resolved", m["dns_ok"]), ("TCP open", m["tcp_ok"]),
             ("reached a Telegram DC", m["dc_ok"]), ("verified 3 / 3", m["verified_links"])]
    desc = (f"{title}: {fmt(stars)} stars. {desc_txt} Last funnel: "
            + ", ".join(f"{fmt(n)} {lab}" for lab, n in steps) + ".")
    W, pad = (1200, 56) if not mobile else (600, 32)
    lw = 600 if not mobile else W - 2 * pad
    lines = wrap(desc_txt, "sans", 17 if not mobile else 16, lw, 600)
    left, ly = card_frame(W, 0, pad, "FLAGSHIP  ·  02", title, stars, lines,
                          ("PYTHON", "MTPROTO", "GITHUB PAGES"), mobile)
    b = [glow(W - 200 if not mobile else W - 100, 40, 320, 220), left]
    if not mobile:
        ox, oy = 760, 70
    else:
        ox, oy = pad, ly + 10
    rw = (W - pad - ox) if not mobile else W - 2 * pad
    b.append(rect(ox, oy, rw, 230, 20, "card", "stroke", 1))
    b.append(text("LAST RUN · PROOF FUNNEL", ox + 24, oy + 36, font="monob", size=11.5, fill="quiet", tracking=0.14))
    top = steps[0][1]
    bar_w = rw - 48
    for i, (lab, n) in enumerate(steps):
        y = oy + 58 + i * 33
        w = max(6.0, bar_w * n / top)
        last = i == len(steps) - 1
        b.append(rect(ox + 24, y, bar_w, 8, 4, "chip"))
        b.append(f'<rect x="{_n(ox + 24)}" y="{_n(y)}" width="{_n(w)}" height="8" rx="4" '
                 f'fill="{col("accent") if last else col("accent2")}" opacity="{1 if last else 0.55}"/>')
        b.append(text(fmt(n), ox + 24, y + 26, font="monob", size=12.5, fill="ink" if last else "muted"))
        nw = measure(fmt(n), "monob", 12.5)
        b.append(text(lab, ox + 24 + nw + 8, y + 26, size=12.5, weight=700 if last else 600, fill="ink" if last else "muted"))
    H = 330 if not mobile else oy + 230 + 32
    return doc(W, int(H), title, desc, "".join(b))


def card_bot(data, mobile=False):
    tg = data["telegram"]
    title = "@ConfigExBot"
    desc_txt = ("The Raydikalx Telegram bot. It is connected to the Free V2Ray Configs repository and hands "
                "out free configs inside the chat — no browser, no long URLs.")
    flow = ["Tested repository data", "The bot sends you a config", "Import into your app & connect"]
    desc = f"{title}, v2Ray Extractor: {desc_txt} Flow: " + " → ".join(flow) + "."
    W, pad = (1200, 56) if not mobile else (600, 32)
    lw = 600 if not mobile else W - 2 * pad
    lines = wrap(desc_txt, "sans", 17 if not mobile else 16, lw, 600)
    left, ly = card_frame(W, 0, pad, "INSIDE TELEGRAM  ·  03", title, None, lines,
                          ("t.me/ConfigExBot", f"@Raydikalx · {fmt(tg['Raydikalx'])}", f"@v2adikal · {fmt(tg['v2adikal'])}"), mobile)
    b = [glow(W - 200 if not mobile else W - 100, 40, 320, 220), left]
    if not mobile:
        ox, oy = 760, 70
    else:
        ox, oy = pad, ly + 10
    rw = (W - pad - ox) if not mobile else W - 2 * pad
    b.append(rect(ox, oy, rw, 230, 20, "card", "stroke", 1))
    b.append(text("HOW THE BOT WORKS", ox + 24, oy + 36, font="monob", size=11.5, fill="quiet", tracking=0.14))
    for i, lab in enumerate(flow):
        y = oy + 66 + i * 52
        cx = ox + 44
        if i < len(flow) - 1:
            b.append(f'<line x1="{_n(cx)}" y1="{_n(y + 18)}" x2="{_n(cx)}" y2="{_n(y + 52 - 18)}" stroke="{col("stroke")}" stroke-width="2"/>')
        last = i == len(flow) - 1
        pcls = ' class="pulse"' if last else ""
        b.append(f'<circle{pcls} cx="{_n(cx)}" cy="{_n(y)}" r="16" fill="{col("accent") if last else col("chip")}" stroke="{col("accent")}" stroke-width="1.5"/>')
        b.append(text(str(i + 1), cx, y + 5, font="monob", size=14, fill="#FFFFFF" if last else "accent", anchor="middle"))
        b.append(text(lab, cx + 30, y + 6, size=16, weight=700, fill="ink"))
    H = 330 if not mobile else oy + 230 + 32
    return doc(W, int(H), title, desc, "".join(b))


# ─────────────────────────────────────────────────────────────────────────────
# Output
# ─────────────────────────────────────────────────────────────────────────────

ASSETS = {
    "hero": hero,
    "stats": stats,
    "contributions": heatmap,
    "project-v2ray": card_v2ray,
    "project-mtproto": card_mtproto,
    "project-bot": card_bot,
}


def render_all(data) -> dict[str, str]:
    global CUR
    out = {}
    for theme, palette in THEMES.items():
        CUR = palette
        for name, fn in ASSETS.items():
            out[f"{name}-{theme}.svg"] = fn(data, mobile=False)
            out[f"{name}-{theme}-mobile.svg"] = fn(data, mobile=True)
    for fname, svg in out.items():
        if re.search(r"(?:href|src)=\"(?!data:|#)", svg) or "url(http" in svg or "@import" in svg:
            raise SystemExit(f"build: {fname} references an external resource")
    return out


def load_data() -> dict:
    if not os.path.exists(DATA):
        return {}
    with open(DATA, encoding="utf-8") as fh:
        return json.load(fh)


def dump_data(data) -> str:
    # one contribution day per line keeps refresh diffs readable
    days = data.get("contributions", {}).get("days")
    if days is None:
        return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    shallow = json.loads(json.dumps(data))
    shallow["contributions"]["days"] = "@@DAYS@@"
    body = json.dumps(shallow, indent=2, ensure_ascii=False, sort_keys=True)
    rows = ",\n".join("      " + json.dumps(d) for d in days)
    return body.replace('"@@DAYS@@"', "[\n" + rows + "\n    ]") + "\n"


def main(argv) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    if mode not in ("", "--fetch", "--check"):
        print(__doc__)
        return 2
    data = load_data()
    if mode == "--fetch":
        data = refresh(data)
        text_data = dump_data(data)
        with open(DATA, "w", encoding="utf-8") as fh:
            fh.write(text_data)
    if not data:
        raise SystemExit(f"build: {os.path.relpath(DATA, REPO)} is missing - run with --fetch first")
    files = render_all(data)
    if mode == "--check":
        bad = []
        for fname, svg in files.items():
            path = os.path.join(OUT, fname)
            if not os.path.exists(path) or open(path, encoding="utf-8").read() != svg:
                bad.append(fname)
        if dump_data(data) != open(DATA, encoding="utf-8").read():
            bad.append("data.json (not in canonical form)")
        if bad:
            print("check: out of date: " + ", ".join(bad))
            return 1
        print(f"check: {len(files)} SVGs match data.json")
        return 0
    changed = 0
    for fname, svg in files.items():
        path = os.path.join(OUT, fname)
        old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if old != svg:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(svg)
            changed += 1
    total = sum(len(s.encode()) for s in files.values())
    print(f"build: {len(files)} SVGs, {changed} changed, {total / 1024:.0f} KiB total")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
