#!/usr/bin/env python3
"""Build the animated profile cards in assets/ from live GitHub data.

Every card is a 1200-wide SVG. All motion uses native SVG <animate> /
<animateTransform> loops (repeatCount="indefinite"), so it plays inside
GitHub's <img> rendering. Runs daily in GitHub Actions.
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

# Palette sampled from the logo (cobalt mark #0432B8 on #E8E8E8 paper).
P = {
    "bg0": "#04060D",       # outer frame
    "bg1": "#080D1C",       # card panel (dark)
    "bg1b": "#0E1A44",      # card panel (cobalt tint)
    "bg2": "#0F1630",       # tiles, pills
    "line": "#1E2A52",      # borders
    "primary": "#0432B8",   # logo cobalt
    "bright": "#2F5BFF",    # glow blue
    "light": "#8FA8FF",     # highlight blue
    "text": "#E8E8E8",      # logo paper
    "muted": "#9AA3BC",
    "dim": "#5D6788",
}
W = 1200

BRANDS = [
    {"name": "Nudar Official", "kind": "BRAND",
     "desc": "Independent personal brand sharing tools, ideas and lessons on AI, marketing and design.",
     "tags": ["AI", "Marketing", "Design"], "channels": ["Instagram", "TikTok"]},
    {"name": "Astrovenx", "kind": "BRAND",
     "desc": "Astronomy content in English: discoveries, space exploration and celestial events.",
     "tags": ["Astronomy", "Space", "Science"], "channels": ["Instagram", "TikTok", "YouTube"]},
]

SANS = "'Segoe UI', Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'SFMono-Regular', Menlo, Consolas, 'Liberation Mono', monospace"
LOOP = 'repeatCount="indefinite"'


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
            return {d["date"]: d["contributionCount"] for w in weeks for d in w["contributionDays"]}
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
        repos.append({
            "name": r["name"], "description": r.get("description") or "",
            "stars": r["stargazers_count"], "fork": False, "pushed_at": r["pushed_at"],
            "topics": r.get("topics") or [], "languages": _json(r["languages_url"], token),
        })
    days = fetch_calendar(token)
    dates = sorted(days)
    avatar = None
    try:
        body, ctype = _get(user["avatar_url"] + "&s=200", accept="image/*")
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
    if sum(len(x.split()) for x in out) < len(words):
        out[-1] = out[-1].rstrip(".,;:") + "…"
    return out[:lines]


def mix(a, b, t):
    a = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


def svg(h, body, label=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" '
        f'role="img" aria-label="{esc(label)}" fill="none">\n'
        f'<style>.s{{font-family:{SANS}}}.m{{font-family:{MONO}}}</style>\n{body}\n</svg>\n'
    )


def frame(h, stamp, glow_dur=4):
    """Outer frame, pulsing glow border, glass inner panel, shared filters."""
    p = P
    return f"""<defs>
<linearGradient id="panel" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{p['bg1']}"/><stop offset=".55" stop-color="{p['bg1']}"/><stop offset="1" stop-color="{p['bg1b']}"/></linearGradient>
<radialGradient id="corner" cx="1" cy="0" r="1"><stop offset="0" stop-color="{p['bright']}" stop-opacity=".22"/><stop offset="1" stop-color="{p['bright']}" stop-opacity="0"/></radialGradient>
<linearGradient id="glass" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".22"/><stop offset=".4" stop-color="#FFFFFF" stop-opacity=".05"/><stop offset="1" stop-color="#FFFFFF" stop-opacity=".12"/></linearGradient>
<linearGradient id="edge" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{p['bright']}"/><stop offset=".5" stop-color="{p['light']}"/><stop offset="1" stop-color="{p['primary']}"/></linearGradient>
<filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="10"/></filter>
<clipPath id="inner"><rect x="18" y="18" width="{W - 36}" height="{h - 36}" rx="22"/></clipPath>
</defs>
<rect x="1" y="1" width="{W - 2}" height="{h - 2}" rx="28" fill="{p['bg0']}"/>
<rect x="4" y="4" width="{W - 8}" height="{h - 8}" rx="26" stroke="url(#edge)" stroke-width="4" filter="url(#soft)" opacity=".5">
  <animate attributeName="opacity" values=".15;.85;.15" dur="{glow_dur}s" {LOOP}/>
</rect>
<rect x="1.5" y="1.5" width="{W - 3}" height="{h - 3}" rx="28" stroke="url(#edge)" stroke-width="2" opacity=".6">
  <animate attributeName="stroke-opacity" values=".35;1;.35" dur="{glow_dur}s" {LOOP}/>
</rect>
<rect x="18" y="18" width="{W - 36}" height="{h - 36}" rx="22" fill="url(#panel)"/>
<rect x="18" y="18" width="{W - 36}" height="{h - 36}" rx="22" fill="url(#corner)"/>
<rect x="18.75" y="18.75" width="{W - 37.5}" height="{h - 37.5}" rx="21.5" stroke="url(#glass)" stroke-width="1.5"/>
<text x="{W - 44}" y="{h - 36}" text-anchor="end" class="m" font-size="13" fill="{p['dim']}">{esc(stamp)}</text>"""


def stats(cal):
    start = dt.date.fromisoformat(cal["start"])
    end = dt.date.fromisoformat(cal["end"])
    days, d = [], start
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


def avatar_img(d, cx, cy, r, cid):
    p = P
    if d.get("avatar"):
        return (f'<clipPath id="{cid}"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath>'
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{p["text"]}"/>'
                f'<image href="{d["avatar"]}" x="{cx - r}" y="{cy - r}" width="{2 * r}" height="{2 * r}" '
                f'clip-path="url(#{cid})" preserveAspectRatio="xMidYMid slice"/>')
    name = d["user"].get("name") or d["user"]["login"]
    initials = "".join(w[0] for w in name.split()[:2]).upper()
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{p["bg2"]}"/>'
            f'<text x="{cx}" y="{cy + r * 0.32:.0f}" text-anchor="middle" class="s" font-size="{r * 0.85:.0f}" '
            f'font-weight="800" fill="{p["text"]}">{esc(initials)}</text>')


# ---------------------------------------------------------------- header ---
def header(d, st, stamp):
    H = 340
    p, u = P, d["user"]
    total = st[1]
    name = u.get("name") or u["login"]
    cx, cy, r = 168, 170, 80
    pills, x = [], 302
    for i, s in enumerate(STACK):
        w = text_w(s, 18, True) + 40
        pills.append(
            f'<rect x="{x:.0f}" y="262" width="{w:.0f}" height="40" rx="20" fill="{p["bg2"]}" stroke="{p["line"]}" stroke-width="1.5">'
            f'<animate attributeName="stroke" values="{p["line"]};{p["bright"]};{p["line"]}" dur="4s" begin="{i * 0.6:.1f}s" {LOOP}/></rect>'
            f'<text x="{x + w / 2:.0f}" y="288" text-anchor="middle" class="m" font-size="18" fill="{p["text"]}">{esc(s)}</text>')
        x += w + 12
    loc = f' · {u["location"]}' if u.get("location") else ""
    body = f"""{frame(H, stamp)}
<defs>
<linearGradient id="ring" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{p['bright']}"/><stop offset="1" stop-color="{p['light']}"/></linearGradient>
<linearGradient id="num" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{p['light']}"/><stop offset="1" stop-color="{p['bright']}"/></linearGradient>
<radialGradient id="halo"><stop offset="0" stop-color="{p['bright']}" stop-opacity=".55"/><stop offset="1" stop-color="{p['bright']}" stop-opacity="0"/></radialGradient>
<linearGradient id="sweep" x1="0" y1="0" x2="1" y2="0">
  <stop offset="0" stop-color="{p['light']}" stop-opacity="0"/><stop offset=".5" stop-color="{p['light']}" stop-opacity=".16"/><stop offset="1" stop-color="{p['light']}" stop-opacity="0"/>
</linearGradient>
</defs>
<g clip-path="url(#inner)">
  <rect x="-400" y="0" width="400" height="{H}" fill="url(#sweep)" transform="skewX(-20)">
    <animateTransform attributeName="transform" type="translate" values="-200 0;1700 0" dur="5s" {LOOP} additive="sum"/>
  </rect>
</g>
<g>
  <animateTransform attributeName="transform" type="translate" values="0 0;0 -12;0 0" dur="4s" {LOOP}/>
  <circle cx="{cx}" cy="{cy}" r="{r + 40}" fill="url(#halo)">
    <animate attributeName="r" values="{r + 28};{r + 48};{r + 28}" dur="4s" {LOOP}/>
  </circle>
  {avatar_img(d, cx, cy, r, "av")}
  <circle cx="{cx}" cy="{cy}" r="{r + 8}" stroke="url(#ring)" stroke-width="5" filter="url(#glow)"/>
  <circle cx="{cx}" cy="{cy}" r="{r + 22}" stroke="{p['light']}" stroke-opacity=".6" stroke-width="2" stroke-dasharray="6 12">
    <animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" to="360 {cx} {cy}" dur="18s" {LOOP}/>
  </circle>
  <circle cx="{cx + r + 22}" cy="{cy}" r="6" fill="{p['light']}" filter="url(#glow)">
    <animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" to="-360 {cx} {cy}" dur="9s" {LOOP}/>
  </circle>
</g>
<text x="304" y="104" class="m" font-size="20" fill="{p['light']}">@{esc(u['login'])}{esc(loc)}</text>
<text x="300" y="188" class="s" font-size="76" font-weight="800" letter-spacing="-2" fill="{p['text']}">{esc(name)}<tspan fill="{p['bright']}">.</tspan></text>
<text x="304" y="234" class="s" font-size="24" fill="{p['muted']}">{esc(TAGLINE)}</text>
{''.join(pills)}
<text x="{W - 70}" y="160" text-anchor="end" class="s" font-size="84" font-weight="800" fill="url(#num)" filter="url(#glow)">{compact(total)}
  <animate attributeName="opacity" values="1;.75;1" dur="3s" {LOOP}/></text>
<text x="{W - 70}" y="196" text-anchor="end" class="m" font-size="15" letter-spacing="2" fill="{p['muted']}">CONTRIBUTIONS · 12 MO</text>"""
    return svg(H, body, f"{name}. {TAGLINE}")


# ------------------------------------------------------------------ city ---
def city(d, st, stamp):
    H = 580
    p = P
    days, total, active, longest = st
    peak = max([c for _, c in days] + [1])
    ux, uy = 15.0, -4.6     # one week
    vx, vy = 10.0, 6.4      # one weekday
    ox, oy = 300, 438
    first_wd = (days[0][0].weekday() + 1) % 7  # Sunday = 0
    cells = []
    for i, (_, c) in enumerate(days):
        col, row = divmod(i + first_wd, 7)
        cells.append((col, row, c))
    ncols = cells[-1][0] + 1
    cells.sort(key=lambda t: t[1] * vy + t[0] * uy)  # far to near
    g = 0.08

    def pts(*q, up=0.0):
        return " ".join(f"{x:.1f},{y - up:.1f}" for x, y in q)

    parts, tops = [], []
    for col, row, c in cells:
        bx, by = ox + col * ux + row * vx, oy + col * uy + row * vy
        a = (bx + g * (ux + vx), by + g * (uy + vy))
        b = (a[0] + (1 - 2 * g) * ux, a[1] + (1 - 2 * g) * uy)
        cc = (b[0] + (1 - 2 * g) * vx, b[1] + (1 - 2 * g) * vy)
        e = (a[0] + (1 - 2 * g) * vx, a[1] + (1 - 2 * g) * vy)
        if c:
            t = math.sqrt(c / peak)
            h = 18 + 112 * t
            top = mix("#3A66FF", "#C9D5FF", t)
            front, left = mix("#0432B8", "#3D63E6", t), mix("#021A66", "#1D3FB0", t)
        else:
            h, top, front, left = 2.2, "#141C38", "#0C1228", "#080D1E"
        face = (f'<polygon points="{pts(a, e)} {pts(e, a, up=h)}" fill="{left}"/>'
                f'<polygon points="{pts(e, cc)} {pts(cc, e, up=h)}" fill="{front}"/>'
                f'<polygon points="{pts(a, b, cc, e, up=h)}" fill="{top}"/>')
        if c:
            face += (f'<polygon points="{pts(a, b, cc, e, up=h)}" fill="#FFFFFF" opacity="0">'
                     f'<animate attributeName="opacity" values="0;.45;0" dur="3.5s" begin="{(col % 7) * 0.5:.1f}s" {LOOP}/></polygon>')
            mx = (a[0] + cc[0]) / 2
            my = (a[1] + cc[1]) / 2 - h
            tops.append((c, mx, my))
        parts.append(face)

    # light beam sweeping along the weeks
    q0 = (ox, oy - 3)
    beam = pts(q0, (q0[0] + ux * 1.6, q0[1] + uy * 1.6),
               (q0[0] + ux * 1.6 + vx * 7, q0[1] + uy * 1.6 + vy * 7), (q0[0] + vx * 7, q0[1] + vy * 7))
    tx, ty = ux * (ncols - 1.6), uy * (ncols - 1.6)
    beam_svg = f"""<polygon points="{beam}" fill="url(#beamfill)" filter="url(#glow)">
  <animateTransform attributeName="transform" type="translate" values="0 0;{tx:.1f} {ty:.1f}" dur="6s" {LOOP}/>
  <animate attributeName="opacity" values="0;.9;.9;0" keyTimes="0;.1;.85;1" dur="6s" {LOOP}/>
</polygon>"""

    beacons = []
    for i, (c, mx, my) in enumerate(sorted(tops, reverse=True)[:3]):
        beacons.append(f"""<line x1="{mx:.1f}" y1="{my:.1f}" x2="{mx:.1f}" y2="{my - 70:.1f}" stroke="{p['light']}" stroke-width="2" stroke-linecap="round" opacity=".5">
  <animate attributeName="opacity" values=".1;.7;.1" dur="2.4s" begin="{i * 0.5:.1f}s" {LOOP}/></line>
<circle cx="{mx:.1f}" cy="{my:.1f}" r="5" fill="{p['light']}" filter="url(#glow)">
  <animate attributeName="opacity" values="1;.4;1" dur="1.2s" begin="{i * 0.3:.1f}s" {LOOP}/></circle>
<circle cx="{mx:.1f}" cy="{my:.1f}" r="5" stroke="{p['light']}" stroke-width="2.5">
  <animate attributeName="r" values="5;30" dur="2s" begin="{i * 0.5:.1f}s" {LOOP}/>
  <animate attributeName="opacity" values="1;0" dur="2s" begin="{i * 0.5:.1f}s" {LOOP}/></circle>""")

    rnd = random.Random(7)
    sparks = []
    for i in range(30):
        x = rnd.uniform(380, 1150)
        y = rnd.uniform(140, 430)
        dur = rnd.uniform(4, 8)
        sparks.append(
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rnd.uniform(1.6, 3.4):.1f}" fill="{p["light"]}" filter="url(#glow)" opacity="0">'
            f'<animate attributeName="opacity" values="0;1;0" dur="{dur:.1f}s" begin="{i * 0.27:.2f}s" {LOOP}/>'
            f'<animateTransform attributeName="transform" type="translate" values="0 20;0 -70" dur="{dur:.1f}s" begin="{i * 0.27:.2f}s" {LOOP}/></circle>')

    s0, s1 = days[0][0].strftime("%b %Y"), days[-1][0].strftime("%b %Y")
    body = f"""{frame(H, stamp)}
<defs>
<radialGradient id="ground"><stop offset="0" stop-color="{p['bright']}" stop-opacity=".5"/><stop offset="1" stop-color="{p['bright']}" stop-opacity="0"/></radialGradient>
<linearGradient id="beamfill" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{p['light']}" stop-opacity="0"/><stop offset=".5" stop-color="{p['light']}" stop-opacity=".8"/><stop offset="1" stop-color="{p['light']}" stop-opacity="0"/></linearGradient>
</defs>
<ellipse cx="760" cy="350" rx="480" ry="160" fill="url(#ground)">
  <animate attributeName="opacity" values=".35;1;.35" dur="4s" {LOOP}/>
</ellipse>
{''.join(parts)}
{beam_svg}
{''.join(beacons)}
{''.join(sparks)}
<text x="62" y="94" class="m" font-size="17" letter-spacing="3" fill="{p['light']}">CONTRIBUTION CITY</text>
<text x="58" y="176" class="s" font-size="80" font-weight="800" fill="{p['text']}">{compact(total)}</text>
<text x="62" y="212" class="s" font-size="21" fill="{p['muted']}">contributions in the last year</text>
<text x="62" y="264" class="m" font-size="19" fill="{p['text']}">{active} active day{'s' if active != 1 else ''}</text>
<text x="62" y="296" class="m" font-size="19" fill="{p['text']}">Longest streak {longest} day{'s' if longest != 1 else ''}</text>
<text x="62" y="{H - 64}" class="m" font-size="15" fill="{p['dim']}">@{esc(d['user']['login'])}</text>
<text x="62" y="{H - 40}" class="m" font-size="15" fill="{p['dim']}">{s0} → {s1}</text>"""
    return svg(H, body, f"Contribution city: {total} contributions in the last year")


# ---------------------------------------------------------------- signal ---
def signal(d, st, stamp):
    H = 360
    p = P
    _, total, active, longest = st
    repos = d["user"].get("public_repos") or len(d["repos"])
    tiles = [
        ("CONTRIBUTIONS", total, milestone(total), p["light"], ""),
        ("PUBLIC REPOS", repos, milestone(repos), p["text"], ""),
        ("ACTIVE DAYS", active, 365, p["bright"], ""),
        ("LONGEST STREAK", longest, milestone(longest), p["text"], "d"),
    ]
    tw, gap, x0, y0, th = 258, 22, 54, 148, 140
    out = []
    for i, (lab, val, goal, col, suf) in enumerate(tiles):
        x = x0 + i * (tw + gap)
        bw = tw - 44
        fw = bw * max(0.04, min(1, val / goal))
        out.append(f"""<rect x="{x}" y="{y0}" width="{tw}" height="{th}" rx="18" fill="{p['bg2']}" stroke="{p['line']}" stroke-width="1.5"/>
<rect x="{x + .75}" y="{y0 + .75}" width="{tw - 1.5}" height="{th - 1.5}" rx="17.5" stroke="url(#glass)"/>
<text x="{x + 22}" y="{y0 + 38}" class="m" font-size="15" letter-spacing="1.5" fill="{p['muted']}">{lab}</text>
<text x="{x + tw - 22}" y="{y0 + 38}" text-anchor="end" class="m" font-size="14" fill="{p['dim']}">/ {compact(goal)}{suf}</text>
<text x="{x + 22}" y="{y0 + 94}" class="s" font-size="50" font-weight="800" fill="{col}">{compact(val)}{suf}</text>
<rect x="{x + 22}" y="{y0 + 112}" width="{bw}" height="10" rx="5" fill="{p['line']}"/>
<rect x="{x + 22}" y="{y0 + 112}" width="{fw:.1f}" height="10" rx="5" fill="{col}" filter="url(#glow)">
  <animate attributeName="width" values="0;{fw:.1f};{fw:.1f};{fw:.1f}" keyTimes="0;.3;.9;1" dur="6s" begin="{i * 0.3:.1f}s" {LOOP}/>
  <animate attributeName="opacity" values="1;.55;1" dur="1.8s" {LOOP}/>
</rect>""")
    rx, ry = W - 80, 84
    body = f"""{frame(H, stamp)}
<text x="54" y="92" class="s" font-size="36" font-weight="800" fill="{p['text']}">Profile Signal</text>
<text x="56" y="124" class="m" font-size="18" fill="{p['light']}">Live GitHub stats · refreshed daily</text>
<text x="{rx - 30}" y="{ry + 6}" text-anchor="end" class="m" font-size="15" letter-spacing="2" fill="{p['light']}">LIVE
  <animate attributeName="opacity" values="1;.25;1" dur="1.4s" {LOOP}/></text>
<circle cx="{rx}" cy="{ry}" r="8" stroke="{p['bright']}" stroke-width="3">
  <animate attributeName="r" values="8;34" dur="2s" {LOOP}/><animate attributeName="opacity" values="1;0" dur="2s" {LOOP}/></circle>
<circle cx="{rx}" cy="{ry}" r="8" stroke="{p['light']}" stroke-width="2">
  <animate attributeName="r" values="8;34" dur="2s" begin="1s" {LOOP}/><animate attributeName="opacity" values="1;0" dur="2s" begin="1s" {LOOP}/></circle>
<circle cx="{rx}" cy="{ry}" r="9" fill="{p['bright']}" filter="url(#glow)">
  <animate attributeName="r" values="8;11;8" dur="1.4s" {LOOP}/><animate attributeName="opacity" values="1;.5;1" dur="1.4s" {LOOP}/></circle>
{''.join(out)}"""
    return svg(H, body, f"Profile signal: {total} contributions, {repos} repos, {active} active days")


# ------------------------------------------------------------- landmarks ---
def pick_repos(repos):
    own = [r for r in repos if not r.get("fork")]
    others = sorted((r for r in own if r["name"] != LOGIN), key=lambda r: (r["stars"], r["pushed_at"]), reverse=True)
    chosen = others[:2]
    if len(chosen) < 2:
        chosen += [r for r in own if r["name"] == LOGIN][: 2 - len(chosen)]
    return chosen


def ring(cx, cy, segs, center, label, i):
    p, r = P, 44
    c = 2 * math.pi * r
    out = [f'<circle cx="{cx}" cy="{cy}" r="{r + 16}" stroke="{p["light"]}" stroke-opacity=".55" stroke-width="2" stroke-dasharray="4 10">'
           f'<animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" to="360 {cx} {cy}" dur="{14 + i * 2}s" {LOOP}/></circle>',
           f'<circle cx="{cx}" cy="{cy}" r="{r + 16}" stroke="{p["bright"]}" stroke-width="3" stroke-linecap="round" stroke-dasharray="40 {2 * math.pi * (r + 16) - 40:.1f}" filter="url(#glow)">'
           f'<animateTransform attributeName="transform" type="rotate" from="360 {cx} {cy}" to="0 {cx} {cy}" dur="6s" {LOOP}/></circle>',
           f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="{p["line"]}" stroke-width="10"/>']
    start, gap = 0.0, (0.03 if len(segs) > 1 else 0)
    for k, f in enumerate(segs):
        ln = max(0.0, f - gap) * c
        out.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="{p["bright"] if k % 2 == 0 else p["light"]}" stroke-width="10" stroke-linecap="round" '
            f'stroke-dasharray="{ln:.1f} {c:.1f}" stroke-dashoffset="{-c * start:.1f}" transform="rotate(-90 {cx} {cy})" filter="url(#glow)">'
            f'<animate attributeName="stroke-opacity" values="1;.55;1" dur="2.6s" begin="{k * 0.4:.1f}s" {LOOP}/></circle>')
        start += f
    out.append(f'<text x="{cx}" y="{cy + 8}" text-anchor="middle" class="s" font-size="24" font-weight="800" fill="{p["text"]}">{esc(center)}</text>')
    out.append(f'<text x="{cx}" y="{cy + 88}" text-anchor="middle" class="m" font-size="14" fill="{p["muted"]}">{esc(label)}</text>')
    return "".join(out)


def landmarks(d, stamp):
    H = 704
    p = P
    now = dt.datetime.strptime(d["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    items = []
    for r in pick_repos(d["repos"]):
        langs = r.get("languages") or {}
        tot = sum(langs.values())
        if tot:
            top, n = max(langs.items(), key=lambda kv: kv[1])
            rg = ([n / tot], f"{round(n / tot * 100)}%", top)
        else:
            top, rg = "", ([], "n/a", "no code yet")
        foot = " · ".join(x for x in (top, f"★ {compact(r['stars'])}" if r["stars"] else "", f"updated {ago(r['pushed_at'], now)}") if x)
        items.append(("REPO", r["name"], r["description"], r.get("topics") or ([top] if top else []), foot, rg))
    for b in BRANDS:
        n = len(b["channels"])
        items.append((b["kind"], b["name"], b["desc"], b["tags"], " · ".join(b["channels"]), ([1 / n] * n, str(n), "channels")))
    cw, ch, gx, gy, x0, y0 = 534, 240, 24, 24, 54, 136
    per = 2 * (cw + ch)
    cards = []
    for i, (kind, name, desc, tags, foot, rg) in enumerate(items[:4]):
        x = x0 + (i % 2) * (cw + gx)
        y = y0 + (i // 2) * (ch + gy)
        tag_svg, tx = [], x + 28
        for t in tags:
            w = text_w(t, 14, True) + 26
            if tx + w > x + 380:
                break
            tag_svg.append(f'<rect x="{tx:.0f}" y="{y + 156}" width="{w:.0f}" height="30" rx="15" fill="{p["bg1"]}" stroke="{p["line"]}" stroke-width="1.5"/>'
                           f'<text x="{tx + w / 2:.0f}" y="{y + 176}" text-anchor="middle" class="m" font-size="14" fill="{p["muted"]}">{esc(t)}</text>')
            tx += w + 8
        desc_svg = "".join(f'<text x="{x + 28}" y="{y + 112 + j * 26}" class="s" font-size="18" fill="{p["muted"]}">{esc(l)}</text>'
                           for j, l in enumerate(wrap(desc, 38, 2)))
        cards.append(f"""<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="20" fill="{p['bg2']}" stroke="{p['line']}" stroke-width="1.5"/>
<rect x="{x + .75}" y="{y + .75}" width="{cw - 1.5}" height="{ch - 1.5}" rx="19.5" stroke="url(#glass)"/>
<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="20" stroke="{p['light']}" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="120 {per - 120}" filter="url(#glow)">
  <animate attributeName="stroke-dashoffset" values="{per};0" dur="6s" begin="{i * 1.5:.1f}s" {LOOP}/>
</rect>
<text x="{x + 28}" y="{y + 42}" class="m" font-size="14" letter-spacing="2" fill="{p['light']}">◆ {kind}</text>
<text x="{x + 28}" y="{y + 80}" class="s" font-size="30" font-weight="800" fill="{p['text']}">{esc(name)}</text>
{desc_svg}
{''.join(tag_svg)}
<text x="{x + 28}" y="{y + 218}" class="m" font-size="15" fill="{p['dim']}">{esc(foot)}</text>
{ring(x + cw - 92, y + 104, rg[0], rg[1], rg[2], i)}""")
    body = f"""{frame(H, stamp)}
<text x="54" y="82" class="m" font-size="19" letter-spacing="2" fill="{p['light']}">PROJECTS.LOG</text>
<text x="252" y="82" class="m" font-size="17" fill="{p['dim']}">@{esc(d['user']['login'])} ~ landmarks</text>
<text x="{W - 54}" y="82" text-anchor="end" class="m" font-size="17" fill="{p['muted']}">{len(items[:4])} projects</text>
<rect x="54" y="104" width="{W - 108}" height="1.5" fill="{p['line']}"/>
<rect x="54" y="104" width="160" height="1.5" fill="{p['light']}" filter="url(#glow)">
  <animate attributeName="x" values="54;{W - 214};54" dur="8s" {LOOP}/>
</rect>
{''.join(cards)}"""
    return svg(H, body, "Projects: " + ", ".join(it[1] for it in items[:4]))


# ----------------------------------------------------------------- visit ---
def visit(d, stamp):
    H = 220
    p = P
    pw, ph = 480, 88
    px, py = (W - pw) / 2, (H - ph) / 2
    cx, cy = px + 48, py + ph / 2
    body = f"""{frame(H, stamp, glow_dur=3)}
<defs>
<linearGradient id="shine" x1="0" y1="0" x2="1" y2="0">
  <stop offset="0" stop-color="#FFFFFF" stop-opacity="0"/><stop offset=".5" stop-color="#FFFFFF" stop-opacity=".45"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>
</linearGradient>
<linearGradient id="pillfill" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{p['bg2']}"/><stop offset="1" stop-color="{p['bg1b']}"/></linearGradient>
<clipPath id="pill"><rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="{ph / 2}"/></clipPath>
</defs>
<rect x="{px - 10}" y="{py - 10}" width="{pw + 20}" height="{ph + 20}" rx="{ph / 2 + 10}" stroke="{p['bright']}" stroke-width="3" filter="url(#glow)">
  <animate attributeName="opacity" values=".15;.9;.15" dur="3s" {LOOP}/>
</rect>
<rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="{ph / 2}" fill="url(#pillfill)" stroke="{p['bright']}" stroke-width="2.5"/>
<g clip-path="url(#pill)">
  <rect x="{px - 160}" y="{py}" width="140" height="{ph}" fill="url(#shine)" transform="skewX(-20)">
    <animateTransform attributeName="transform" type="translate" values="0 0;{pw + 340} 0;{pw + 340} 0" keyTimes="0;.6;1" dur="3s" {LOOP} additive="sum"/>
  </rect>
</g>
{avatar_img(d, cx, cy, 28, "mini")}
<circle cx="{cx}" cy="{cy}" r="32" stroke="{p['light']}" stroke-width="2"/>
<text x="{px + 96}" y="{cy - 4}" class="s" font-size="26" font-weight="800" fill="{p['text']}">@nudarofficial</text>
<text x="{px + 96}" y="{cy + 22}" class="m" font-size="16" fill="{p['muted']}">follow on instagram</text>
<text x="{px + pw - 40}" y="{cy + 10}" text-anchor="end" class="s" font-size="32" fill="{p['light']}">→
  <animateTransform attributeName="transform" type="translate" values="0 0;8 0;0 0" dur="1.5s" {LOOP}/></text>"""
    return svg(H, body, "Follow @nudarofficial on Instagram")


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
