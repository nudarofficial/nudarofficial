#!/usr/bin/env python3
"""Build the animated profile cards in assets/ from live GitHub data.

Runs daily in GitHub Actions (see .github/workflows/profile-cards.yml).
Standard library only. Local test: python3 scripts/generate.py --data data.json
"""
import argparse
import base64
import datetime as dt
import html
import json
import math
import os
import random
import re
import sys
import urllib.request

# ---------------------------------------------------------------- config ---
LOGIN = os.environ.get("GH_USER", "nudarofficial")
TAGLINE = "AI • Marketing • Design  |  Building Digital Experiences"
STACK = ["Python", "SQL", "AI", "Design"]

# Palette: swap these six values to re-theme every card.
P = {
    "bg0": "#07080B",      # outer frame
    "bg1": "#0D1018",      # card panel
    "bg2": "#141A28",      # tiles, pills
    "line": "#232B3E",     # borders
    "primary": "#1F4FFF",  # main blue
    "secondary": "#7B97FF",  # light blue
    "text": "#F7F5F0",     # off-white
    "muted": "#8D95A8",
    "dim": "#545C70",
}

BRANDS = [
    {
        "name": "Nudar Official",
        "kind": "BRAND",
        "desc": "Independent personal brand sharing tools, ideas and lessons on AI, marketing and design.",
        "tags": ["AI", "Marketing", "Design"],
        "channels": ["Instagram", "TikTok"],
    },
    {
        "name": "Astrovenx",
        "kind": "BRAND",
        "desc": "Astronomy content in English: discoveries, space exploration and celestial events.",
        "tags": ["Astronomy", "Space", "Science"],
        "channels": ["Instagram", "TikTok", "YouTube"],
    },
]

SANS = "'Segoe UI', Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'SFMono-Regular', Menlo, Consolas, 'Liberation Mono', monospace"

BASE_CSS = f"""
.s{{font-family:{SANS}}} .m{{font-family:{MONO}}}
.up{{animation:up .9s cubic-bezier(.2,.7,.2,1) backwards}}
@keyframes up{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:none}}}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}
"""


# ----------------------------------------------------------------- fetch ---
def _get(url, token=None, data=None, accept="application/vnd.github+json"):
    headers = {"User-Agent": "profile-cards", "Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(), r.headers.get("Content-Type", "")


def _json(url, token=None, data=None):
    return json.loads(_get(url, token, data)[0])


def fetch_calendar(token):
    """Contribution calendar via GraphQL, falling back to the public HTML page."""
    if token:
        try:
            q = """query($l:String!){user(login:$l){contributionsCollection{
              contributionCalendar{weeks{contributionDays{date contributionCount}}}}}}"""
            res = _json("https://api.github.com/graphql", token, {"query": q, "variables": {"l": LOGIN}})
            weeks = res["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
            days = {d["date"]: d["contributionCount"] for w in weeks for d in w["contributionDays"]}
            return days
        except Exception as e:  # noqa: BLE001
            print("GraphQL calendar failed, scraping instead:", e, file=sys.stderr)
    page = _get(f"https://github.com/users/{LOGIN}/contributions", accept="text/html")[0].decode()
    ids = dict(re.findall(r'data-date="(\d{4}-\d\d-\d\d)"[^>]*?id="([^"]+)"', page))
    ids.update({d: i for i, d in re.findall(r'id="([^"]+)"[^>]*?data-date="(\d{4}-\d\d-\d\d)"', page)})
    tips = {}
    for tid, txt in re.findall(r'<tool-tip[^>]*for="([^"]+)"[^>]*>([^<]*)<', page):
        m = re.match(r"\s*(\d+|No) contribution", txt)
        tips[tid] = 0 if not m or m.group(1) == "No" else int(m.group(1))
    if not ids:
        raise RuntimeError("could not read contribution calendar")
    return {d: tips.get(i, 0) for d, i in ids.items()}


def fetch(token):
    user = _json(f"https://api.github.com/users/{LOGIN}", token)
    raw = _json(f"https://api.github.com/users/{LOGIN}/repos?per_page=100&sort=pushed", token)
    repos = []
    for r in raw:
        if r.get("fork"):
            continue
        langs = _json(r["languages_url"], token)
        repos.append({
            "name": r["name"], "description": r.get("description") or "",
            "stars": r["stargazers_count"], "fork": False, "pushed_at": r["pushed_at"],
            "topics": r.get("topics") or [], "languages": langs,
        })
    days = fetch_calendar(token)
    dates = sorted(days)
    avatar = None
    try:
        body, ctype = _get(user["avatar_url"] + "&s=160", accept="image/*")
        avatar = f"data:{ctype or 'image/png'};base64," + base64.b64encode(body).decode()
    except Exception as e:  # noqa: BLE001
        print("avatar fetch failed:", e, file=sys.stderr)
    return {
        "user": {k: user.get(k) for k in ("login", "name", "bio", "location", "followers", "public_repos")},
        "avatar": avatar,
        "repos": repos,
        "calendar": {"start": dates[0], "end": dates[-1], "days": {d: c for d, c in days.items() if c}},
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# --------------------------------------------------------------- helpers ---
def esc(s):
    return html.escape(str(s), quote=True)


def compact(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return str(n)


def milestone(v):
    for s in (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000):
        if s > v:
            return s
    return v * 2 or 1


def ago(iso, now):
    t = dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    days = (now - t).days
    if days < 1:
        return "today"
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def text_w(s, size, mono=False):
    return len(s) * size * (0.61 if mono else 0.55)


def wrap(s, chars, lines):
    words, out, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= chars:
            cur = f"{cur} {w}".strip()
        else:
            out.append(cur)
            cur = w
            if len(out) == lines:
                break
    if len(out) < lines and cur:
        out.append(cur)
    used = sum(len(x.split()) for x in out)
    if used < len(words):
        out[-1] = out[-1].rstrip(".,;:") + "…"
    return out[:lines]


def svg(w, h, body, css="", label=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-label="{esc(label)}" fill="none">\n<style>{BASE_CSS}{css}</style>\n{body}\n</svg>\n'
    )


def frame(w, h, stamp, glow_dur=6):
    p = P
    return f"""<defs>
<linearGradient id="panel" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{p['bg1']}"/><stop offset="1" stop-color="#0F1530"/></linearGradient>
<linearGradient id="edge" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{p['primary']}"/><stop offset=".5" stop-color="{p['secondary']}" stop-opacity=".4"/><stop offset="1" stop-color="{p['primary']}"/></linearGradient>
</defs>
<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="22" fill="{p['bg0']}" stroke="{p['line']}"/>
<rect x="1.5" y="1.5" width="{w - 3}" height="{h - 3}" rx="21.5" stroke="url(#edge)" stroke-width="1.5" opacity=".3">
  <animate attributeName="opacity" values=".18;.7;.18" dur="{glow_dur}s" repeatCount="indefinite"/>
</rect>
<rect x="14" y="14" width="{w - 28}" height="{h - 28}" rx="16" fill="url(#panel)" stroke="{p['line']}" stroke-opacity=".7"/>
<text x="{w - 30}" y="{h - 24}" text-anchor="end" class="m" font-size="9" fill="{p['dim']}">{esc(stamp)}</text>"""


def stats(cal):
    start = dt.date.fromisoformat(cal["start"])
    end = dt.date.fromisoformat(cal["end"])
    days = []
    d = start
    while d <= end:
        days.append((d, int(cal["days"].get(d.isoformat(), 0))))
        d += dt.timedelta(days=1)
    total = sum(c for _, c in days)
    active = sum(1 for _, c in days if c)
    longest = run = 0
    for _, c in days:
        run = run + 1 if c else 0
        longest = max(longest, run)
    return days, total, active, longest


# ---------------------------------------------------------------- header ---
def header(d, st, stamp):
    W, H = 840, 236
    p, u = P, d["user"]
    _, total, _, _ = st
    name = u.get("name") or u["login"]
    cx, cy = 104, 118
    if d.get("avatar"):
        face = (f'<clipPath id="av"><circle cx="{cx}" cy="{cy}" r="50"/></clipPath>'
                f'<image href="{d["avatar"]}" x="{cx - 50}" y="{cy - 50}" width="100" height="100" '
                f'clip-path="url(#av)" preserveAspectRatio="xMidYMid slice"/>')
    else:
        initials = "".join(w[0] for w in name.split()[:2]).upper()
        face = (f'<circle cx="{cx}" cy="{cy}" r="50" fill="{p["bg2"]}"/>'
                f'<text x="{cx}" y="{cy + 12}" text-anchor="middle" class="s" font-size="34" '
                f'font-weight="800" fill="{p["text"]}">{esc(initials)}</text>')
    pills, x = [], 184
    for i, s in enumerate(STACK):
        w = text_w(s, 11, True) + 26
        pills.append(
            f'<g class="up" style="animation-delay:{0.75 + i * 0.12:.2f}s">'
            f'<rect x="{x}" y="170" width="{w:.0f}" height="24" rx="12" fill="{p["bg2"]}" stroke="{p["line"]}"/>'
            f'<text x="{x + w / 2:.0f}" y="186" text-anchor="middle" class="m" font-size="11" fill="{p["text"]}">{esc(s)}</text></g>')
        x += w + 8
    loc = f' · {u["location"]}' if u.get("location") else ""
    body = f"""{frame(W, H, stamp)}
<defs>
<linearGradient id="ring" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{p['primary']}"/><stop offset="1" stop-color="{p['secondary']}"/></linearGradient>
<linearGradient id="num" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{p['secondary']}"/><stop offset="1" stop-color="{p['primary']}"/></linearGradient>
<radialGradient id="halo"><stop offset="0" stop-color="{p['primary']}" stop-opacity=".35"/><stop offset="1" stop-color="{p['primary']}" stop-opacity="0"/></radialGradient>
</defs>
<g>
  <animateTransform attributeName="transform" type="translate" values="0 0;0 -5;0 0" dur="6s" repeatCount="indefinite"/>
  <circle cx="{cx}" cy="{cy}" r="78" fill="url(#halo)"/>
  {face}
  <circle cx="{cx}" cy="{cy}" r="56" stroke="url(#ring)" stroke-width="3"/>
  <circle cx="{cx}" cy="{cy}" r="63" stroke="{p['primary']}" stroke-opacity=".35" stroke-dasharray="3 7">
    <animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" to="360 {cx} {cy}" dur="40s" repeatCount="indefinite"/>
  </circle>
</g>
<text x="186" y="78" class="m up" font-size="13" fill="{p['secondary']}" style="animation-delay:.1s">@{esc(u['login'])}{esc(loc)}</text>
<text x="184" y="124" class="s up" font-size="44" font-weight="800" letter-spacing="-1" fill="{p['text']}" style="animation-delay:.25s">{esc(name)}<tspan fill="{p['primary']}">.</tspan></text>
<text x="186" y="152" class="s up" font-size="15" fill="{p['muted']}" style="animation-delay:.45s">{esc(TAGLINE)}</text>
{''.join(pills)}
<g class="up" style="animation-delay:.6s">
  <text x="{W - 46}" y="112" text-anchor="end" class="s" font-size="46" font-weight="800" fill="url(#num)">{compact(total)}</text>
  <text x="{W - 46}" y="134" text-anchor="end" class="m" font-size="10" letter-spacing="1.5" fill="{p['muted']}">CONTRIBUTIONS · 12 MO</text>
</g>"""
    return svg(W, H, body, label=f"{name}. {TAGLINE}")


# ------------------------------------------------------------------ city ---
def mix(a, b, t):
    a = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


def city(d, st, stamp):
    W, H = 840, 400
    p = P
    days, total, active, longest = st
    peak = max([c for _, c in days] + [1])
    ux, uy = 10.4, -3.2   # one week step
    vx, vy = 7.2, 4.6     # one weekday step
    ox, oy = 200, 312
    first_wd = (days[0][0].weekday() + 1) % 7  # Sunday = 0
    cells = []
    for i, (day, c) in enumerate(days):
        col, row = divmod(i + first_wd, 7)
        cells.append((col, row, c))
    cells.sort(key=lambda t: t[1] * vy + t[0] * uy)  # far to near
    g = 0.09
    parts, k = [], 0
    for col, row, c in cells:
        bx, by = ox + col * ux + row * vx, oy + col * uy + row * vy
        a = (bx + g * (ux + vx), by + g * (uy + vy))
        b = (a[0] + (1 - 2 * g) * ux, a[1] + (1 - 2 * g) * uy)
        cc = (b[0] + (1 - 2 * g) * vx, b[1] + (1 - 2 * g) * vy)
        e = (a[0] + (1 - 2 * g) * vx, a[1] + (1 - 2 * g) * vy)
        if c:
            t = math.sqrt(c / peak)
            h = 12 + 70 * t
            top, front, left = mix("#2C55FF", "#B9C8FF", t), mix("#1534C8", "#4F72FF", t), mix("#0C1E80", "#2A47D6", t)
        else:
            h, top, front, left = 1.6, "#171D2C", "#10141F", "#0C0F18"
        def pts(*q, up=0.0):
            return " ".join(f"{x:.1f},{y - up:.1f}" for x, y in q)
        faces = (f'<polygon points="{pts(a, e)} {pts(e, a, up=h)}" fill="{left}"/>'
                 f'<polygon points="{pts(e, cc)} {pts(cc, e, up=h)}" fill="{front}"/>'
                 f'<polygon points="{pts(a, b, cc, e, up=h)}" fill="{top}"/>')
        if c:
            k += 1
            faces += (f'<polygon class="glint" style="animation-delay:{1.4 + k * 0.6:.1f}s" '
                      f'points="{pts(a, b, cc, e, up=h)}" fill="#FFFFFF"/>')
            parts.append(f'<g class="rise" style="animation-delay:{0.3 + k * 0.15:.2f}s">{faces}</g>')
        else:
            parts.append(faces)
    rnd = random.Random(7)
    sparks = []
    for i in range(16):
        x = rnd.uniform(260, 800)
        y = rnd.uniform(120, 300)
        dur = rnd.uniform(5, 9)
        sparks.append(
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rnd.uniform(.8, 1.8):.1f}" fill="{p["secondary"]}" opacity="0">'
            f'<animate attributeName="opacity" values="0;.85;0" dur="{dur:.1f}s" begin="{i * .45:.1f}s" repeatCount="indefinite"/>'
            f'<animateTransform attributeName="transform" type="translate" values="0 0;0 -34" dur="{dur:.1f}s" begin="{i * .45:.1f}s" repeatCount="indefinite"/></circle>')
    s0 = days[0][0].strftime("%b %Y")
    s1 = days[-1][0].strftime("%b %Y")
    css = """
.rise{transform-box:fill-box;transform-origin:50% 100%;animation:rise 1.4s cubic-bezier(.2,.8,.2,1) backwards}
@keyframes rise{from{transform:scaleY(0)}to{transform:scaleY(1)}}
.glint{opacity:0;animation:glint 5s ease-in-out infinite}
@keyframes glint{0%,100%{opacity:0}45%{opacity:.4}}
"""
    body = f"""{frame(W, H, stamp)}
<defs><radialGradient id="ground"><stop offset="0" stop-color="{p['primary']}" stop-opacity=".45"/><stop offset="1" stop-color="{p['primary']}" stop-opacity="0"/></radialGradient></defs>
<ellipse cx="530" cy="250" rx="330" ry="110" fill="url(#ground)" opacity=".6">
  <animate attributeName="opacity" values=".35;.8;.35" dur="5s" repeatCount="indefinite"/>
</ellipse>
{''.join(parts)}
{''.join(sparks)}
<text x="44" y="62" class="m up" font-size="11" letter-spacing="2" fill="{p['secondary']}">CONTRIBUTION CITY</text>
<text x="42" y="110" class="s up" font-size="44" font-weight="800" fill="{p['text']}" style="animation-delay:.15s">{compact(total)}</text>
<text x="44" y="132" class="s up" font-size="13" fill="{p['muted']}" style="animation-delay:.25s">contributions in the last year</text>
<text x="44" y="166" class="m up" font-size="12" fill="{p['text']}" style="animation-delay:.35s">{active} active day{'s' if active != 1 else ''}</text>
<text x="44" y="186" class="m up" font-size="12" fill="{p['text']}" style="animation-delay:.45s">Longest streak {longest} day{'s' if longest != 1 else ''}</text>
<text x="44" y="{H - 40}" class="m" font-size="10" fill="{p['dim']}">@{esc(d['user']['login'])}</text>
<text x="44" y="{H - 26}" class="m" font-size="10" fill="{p['dim']}">{s0} → {s1}</text>"""
    return svg(W, H, body, css, label=f"Contribution city: {total} contributions in the last year")


# ---------------------------------------------------------------- signal ---
def signal(d, st, stamp):
    W, H = 840, 222
    p = P
    _, total, active, longest = st
    repos = d["user"].get("public_repos") or len(d["repos"])
    tiles = [
        ("CONTRIBUTIONS", total, milestone(total), p["secondary"], ""),
        ("PUBLIC REPOS", repos, milestone(repos), p["text"], ""),
        ("ACTIVE DAYS", active, 365, p["primary"], ""),
        ("LONGEST STREAK", longest, milestone(longest), p["text"], "d"),
    ]
    tw, gap, x0, y0 = 181, 14, 36, 98
    out = []
    for i, (lab, val, goal, col, suf) in enumerate(tiles):
        x = x0 + i * (tw + gap)
        pct = max(0.03, min(1, val / goal))
        bw = tw - 28
        out.append(f"""<g class="up" style="animation-delay:{0.2 + i * 0.12:.2f}s">
<rect x="{x}" y="{y0}" width="{tw}" height="80" rx="12" fill="{p['bg2']}" stroke="{p['line']}"/>
<text x="{x + 14}" y="{y0 + 22}" class="m" font-size="10" letter-spacing="1" fill="{p['muted']}">{lab}</text>
<text x="{x + tw - 14}" y="{y0 + 22}" text-anchor="end" class="m" font-size="9" fill="{p['dim']}">/ {compact(goal)}{suf}</text>
<text x="{x + 14}" y="{y0 + 52}" class="s" font-size="26" font-weight="800" fill="{col}">{compact(val)}{suf}</text>
<rect x="{x + 14}" y="{y0 + 62}" width="{bw}" height="5" rx="2.5" fill="{p['line']}"/>
<rect class="bar" style="animation-delay:{0.6 + i * 0.15:.2f}s" x="{x + 14}" y="{y0 + 62}" width="{bw * pct:.1f}" height="5" rx="2.5" fill="{col}"/>
</g>""")
    css = """
.bar{transform-box:fill-box;transform-origin:0 50%;animation:fill 1.6s cubic-bezier(.2,.8,.2,1) backwards}
@keyframes fill{from{transform:scaleX(0)}to{transform:scaleX(1)}}
"""
    body = f"""{frame(W, H, stamp)}
<text x="36" y="56" class="s up" font-size="20" font-weight="800" fill="{p['text']}">Profile Signal</text>
<text x="36" y="78" class="m up" font-size="11" fill="{p['secondary']}" style="animation-delay:.1s">Live GitHub stats · refreshed daily</text>
<circle cx="{W - 46}" cy="52" r="4" fill="{p['primary']}"/>
<circle cx="{W - 46}" cy="52" r="4" stroke="{p['primary']}" stroke-width="1.5">
  <animate attributeName="r" values="4;12" dur="2s" repeatCount="indefinite"/>
  <animate attributeName="opacity" values=".9;0" dur="2s" repeatCount="indefinite"/>
</circle>
{''.join(out)}"""
    return svg(W, H, body, css, label=f"Profile signal: {total} contributions, {repos} repos, {active} active days")


# ------------------------------------------------------------- landmarks ---
def pick_repos(repos):
    own = [r for r in repos if not r.get("fork")]
    others = [r for r in own if r["name"] != LOGIN]
    others.sort(key=lambda r: (r["stars"], r["pushed_at"]), reverse=True)
    chosen = others[:2]
    if len(chosen) < 2:
        chosen += [r for r in own if r["name"] == LOGIN][: 2 - len(chosen)]
    return chosen


def ring(cx, cy, segs, center, label, delay):
    """segs: list of fractions (0..1) drawn as arcs around a circle."""
    p, r = P, 26
    c = 2 * math.pi * r
    out = [f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="{p["line"]}" stroke-width="6"/>']
    start = 0.0
    gap = 0.03 if len(segs) > 1 else 0
    for i, f in enumerate(segs):
        ln = max(0.0, f - gap) * c
        off = c * start
        out.append(
            f'<circle class="arc" style="--c:{c:.1f};animation-delay:{delay + i * 0.25:.2f}s" cx="{cx}" cy="{cy}" r="{r}" '
            f'stroke="{p["primary"] if i % 2 == 0 else p["secondary"]}" stroke-width="6" stroke-linecap="round" '
            f'stroke-dasharray="{ln:.1f} {c:.1f}" stroke-dashoffset="{-off:.1f}" transform="rotate(-90 {cx} {cy})"/>')
        start += f
    out.append(f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" class="s" font-size="12" font-weight="800" fill="{p["text"]}">{esc(center)}</text>')
    out.append(f'<text x="{cx}" y="{cy + 46}" text-anchor="middle" class="m" font-size="9" fill="{p["muted"]}">{esc(label)}</text>')
    return "".join(out)


def landmarks(d, stamp):
    W, H = 840, 444
    p = P
    now = dt.datetime.strptime(d["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    items = []
    for r in pick_repos(d["repos"]):
        langs = r.get("languages") or {}
        tot = sum(langs.values())
        if tot:
            top, n = max(langs.items(), key=lambda kv: kv[1])
            share = n / tot
            rg = ([share], f"{round(share * 100)}%", top)
        else:
            top, rg = "", ([], "—", "no code yet")
        foot = " · ".join(x for x in (top, f"★ {compact(r['stars'])}" if r["stars"] else "", f"updated {ago(r['pushed_at'], now)}") if x)
        tags = r.get("topics") or ([top] if top else [])
        items.append(("REPO", r["name"], r["description"], tags, foot, rg))
    for b in BRANDS:
        n = len(b["channels"])
        items.append((b["kind"], b["name"], b["desc"], b["tags"], " · ".join(b["channels"]),
                      ([1 / n] * n, str(n), "channels")))
    cw, ch, gx, gy, x0, y0 = 376, 150, 16, 16, 36, 94
    cards = []
    per = 2 * (cw + ch)
    for i, (kind, name, desc, tags, foot, rg) in enumerate(items[:4]):
        x = x0 + (i % 2) * (cw + gx)
        y = y0 + (i // 2) * (ch + gy)
        lines = wrap(desc, 40, 2)
        tag_svg, tx = [], x + 18
        for t in tags:
            w = text_w(t, 10, True) + 16
            if tx + w > x + 270:
                break
            tag_svg.append(f'<rect x="{tx:.0f}" y="{y + 92}" width="{w:.0f}" height="20" rx="10" fill="{p["bg1"]}" stroke="{p["line"]}"/>'
                           f'<text x="{tx + w / 2:.0f}" y="{y + 106}" text-anchor="middle" class="m" font-size="10" fill="{p["muted"]}">{esc(t)}</text>')
            tx += w + 6
        desc_svg = "".join(f'<text x="{x + 18}" y="{y + 58 + j * 16}" class="s" font-size="12" fill="{p["muted"]}">{esc(l)}</text>' for j, l in enumerate(lines))
        cards.append(f"""<g class="up" style="animation-delay:{0.2 + i * 0.15:.2f}s">
<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="12" fill="{p['bg2']}" stroke="{p['line']}"/>
<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="12" stroke="{p['secondary']}" stroke-width="1.2" stroke-dasharray="70 {per - 70}" opacity=".7">
  <animate attributeName="stroke-dashoffset" values="{per};0" dur="9s" begin="{i * 2.2:.1f}s" repeatCount="indefinite"/>
</rect>
<text x="{x + 18}" y="{y + 22}" class="m" font-size="9" letter-spacing="1.5" fill="{p['secondary']}">◆ {kind}</text>
<text x="{x + 18}" y="{y + 40}" class="s" font-size="17" font-weight="800" fill="{p['text']}">{esc(name)}</text>
{desc_svg}
{''.join(tag_svg)}
<text x="{x + 18}" y="{y + 134}" class="m" font-size="10" fill="{p['dim']}">{esc(foot)}</text>
{ring(x + cw - 50, y + 66, rg[0], rg[1], rg[2], 0.8 + i * 0.2)}
</g>""")
    css = """
.arc{animation:arc 1.8s cubic-bezier(.2,.8,.2,1) backwards}
@keyframes arc{from{stroke-dasharray:0 var(--c)}}
"""
    body = f"""{frame(W, H, stamp)}
<text x="36" y="54" class="m" font-size="12" letter-spacing="1.5" fill="{p['secondary']}">PROJECTS.LOG</text>
<text x="160" y="54" class="m" font-size="11" fill="{p['dim']}">@{esc(d['user']['login'])} ~ landmarks</text>
<text x="{W - 36}" y="54" text-anchor="end" class="m" font-size="11" fill="{p['muted']}">{len(items[:4])} projects</text>
<rect x="36" y="68" width="{W - 72}" height="1" fill="{p['line']}"/>
{''.join(cards)}"""
    return svg(W, H, body, css, label="Projects: " + ", ".join(it[1] for it in items[:4]))


# ----------------------------------------------------------------- visit ---
def visit(d, stamp):
    W, H = 840, 132
    p = P
    pw, ph = 300, 54
    px, py = (W - pw) / 2, (H - ph) / 2
    cx, cy = px + 30, py + ph / 2
    if d.get("avatar"):
        face = (f'<clipPath id="mini"><circle cx="{cx}" cy="{cy}" r="16"/></clipPath>'
                f'<image href="{d["avatar"]}" x="{cx - 16}" y="{cy - 16}" width="32" height="32" clip-path="url(#mini)" preserveAspectRatio="xMidYMid slice"/>')
    else:
        face = f'<circle cx="{cx}" cy="{cy}" r="16" fill="{p["primary"]}"/><text x="{cx}" y="{cy + 5}" text-anchor="middle" class="s" font-size="13" font-weight="800" fill="{p["text"]}">N</text>'
    body = f"""{frame(W, H, stamp, glow_dur=4)}
<defs>
<linearGradient id="shine" x1="0" y1="0" x2="1" y2="0" gradientUnits="objectBoundingBox">
  <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".22"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
  <animateTransform attributeName="gradientTransform" type="translate" values="-1 0;1 0" dur="3.2s" repeatCount="indefinite"/>
</linearGradient>
<clipPath id="pill"><rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="{ph / 2}"/></clipPath>
</defs>
<rect x="{px - 6}" y="{py - 6}" width="{pw + 12}" height="{ph + 12}" rx="{ph / 2 + 6}" stroke="{p['primary']}" stroke-width="1.5" opacity=".2">
  <animate attributeName="opacity" values=".1;.55;.1" dur="2.6s" repeatCount="indefinite"/>
</rect>
<rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="{ph / 2}" fill="{p['bg2']}" stroke="{p['primary']}" stroke-width="1.5"/>
<rect x="{px}" y="{py}" width="{pw}" height="{ph}" fill="url(#shine)" clip-path="url(#pill)"/>
{face}
<text x="{px + 58}" y="{cy - 2}" class="s" font-size="15" font-weight="800" fill="{p['text']}">@nudarofficial</text>
<text x="{px + 58}" y="{cy + 14}" class="m" font-size="10" fill="{p['muted']}">follow on instagram</text>
<text x="{px + pw - 26}" y="{cy + 6}" text-anchor="end" class="s" font-size="18" fill="{p['secondary']}">→</text>"""
    return svg(W, H, body, label="Follow @nudarofficial on Instagram")


# ------------------------------------------------------------------ main ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="read data from a JSON file instead of the API")
    ap.add_argument("--out", default="assets")
    a = ap.parse_args()
    if a.data:
        with open(a.data) as f:
            d = json.load(f)
    else:
        d = fetch(os.environ.get("GITHUB_TOKEN"))
    st = stats(d["calendar"])
    when = dt.datetime.strptime(d["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
    stamp = "updated " + when.strftime("%d %b %Y").lstrip("0")
    os.makedirs(a.out, exist_ok=True)
    cards = {
        "header.svg": header(d, st, stamp),
        "city.svg": city(d, st, stamp),
        "signal.svg": signal(d, st, stamp),
        "landmarks.svg": landmarks(d, stamp),
        "visit.svg": visit(d, stamp),
    }
    for name, content in cards.items():
        with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
            f.write(content)
    print(f"wrote {len(cards)} cards · {st[1]} contributions · {st[2]} active days")


if __name__ == "__main__":
    main()
