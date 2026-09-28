# -*- coding: utf-8 -*-
"""Build a static HTML (and, via Chrome, a PDF) from the Greek-A2 markdown.

Sources: index.md (the page-1 sheet) + grammar/*.md
Usage:   python build.py
Output:  index.html            single self-contained file, all 20 sheets
         pages/NN-name.html    one file per sheet
         greek-a2.pdf          printed via headless Chrome (if found)

Everything is written in place at the repo root so GitHub Pages can serve it
directly from main. README.md is the repo landing page and is NOT a sheet.
"""
import io, os, re, sys, glob, html, subprocess, shutil

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = BASE                      # build in place: Pages serves the repo root
PAGES = os.path.join(DIST, 'pages')

# ---------------------------------------------------------------- inline
TOKEN = re.compile(
    r'(\*\*.+?\*\*)'              # bold
    r'|(~~.+?~~)'                 # strike
    r'|(`[^`]+`)'                 # code
    r'|(\[[^\]]+\]\([^)]+\))'     # link
    r'|(\*[^*\s][^*]*?\*)'        # italic
)

def inline(text):
    out, pos = [], 0
    for m in TOKEN.finditer(text):
        if m.start() > pos:
            out.append(html.escape(text[pos:m.start()]))
        tok = m.group(0)
        # inner text is re-parsed, so **[a](b)** and [**a**](b) both work
        if m.group(1):
            out.append('<strong>%s</strong>' % inline(tok[2:-2]))
        elif m.group(2):
            out.append('<s>%s</s>' % inline(tok[2:-2]))
        elif m.group(3):
            out.append('<code>%s</code>' % html.escape(tok[1:-1]))
        elif m.group(4):
            lm = re.match(r'\[([^\]]+)\]\(([^)]+)\)', tok)
            label, href = lm.group(1), lm.group(2)
            # real links only: absolute, in-page anchors, or a sibling .html page.
            # anything else (e.g. a path to a .md source) degrades to plain text.
            if href.startswith(('http://', 'https://', '#')) or href.endswith('.html'):
                out.append('<a href="%s">%s</a>' % (html.escape(href), inline(label)))
            else:
                out.append(inline(label))
        elif m.group(5):
            out.append('<em>%s</em>' % inline(tok[1:-1]))
        pos = m.end()
    if pos < len(text):
        out.append(html.escape(text[pos:]))
    return ''.join(out)

def plain(text):
    """Markdown stripped to bare text (no HTML escaping) - for detection & titles."""
    t = text
    t = re.sub(r'\*\*(.+?)\*\*', r'\1', t)
    t = re.sub(r'~~(.+?)~~', r'\1', t)
    t = re.sub(r'`([^`]+)`', r'\1', t)
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)
    t = re.sub(r'\*([^*\s][^*]*?)\*', r'\1', t)
    return t.strip()

# ---------------------------------------------------------------- gender
def tense_of(t):
    """'pr' / 'pa' / 'fu' from a verb row's label. Past is tested first so
    'Perfect' does not read as present, and future before present so
    'Future continuous - θα + present' lands in the future band."""
    if not t:
        return None
    if re.search(r'\b(aorist|imperfect|perfect|past)\b', t, re.I):
        return 'pa'
    if re.search(r'\b(future|subjunctive)\b', t, re.I):
        return 'fu'
    if re.search(r'\bpresent\b', t, re.I):
        return 'pr'
    return None


def band_of(kind, text):
    """Which colour band a row carries: gender for nouns and adjectives, tense
    family for verbs."""
    return tense_of(text) if kind == 'verb' else gender_of(text)


def gender_of(t):
    if not t:
        return None
    t = t.strip()
    if not t:
        return None
    if len(re.findall(r'\b[MFN]\b', t)) > 1:
        return None
    if len(re.findall(r'\b(?:Masculine|Feminine|Neuter)\b', t, re.I)) > 1:
        return None
    if re.match(r'^masculine\b', t, re.I): return 'm'
    if re.match(r'^feminine\b', t, re.I):  return 'f'
    if re.match(r'^neuter\b', t, re.I):    return 'n'
    if re.match(r'^m\b', t, re.I) or re.match(r'^M\d', t): return 'm'
    if re.match(r'^f\b', t, re.I) or re.match(r'^F\d', t): return 'f'
    if re.match(r'^n\b', t, re.I) or re.match(r'^N\d', t): return 'n'
    if re.search(r'\bMasculine$', t, re.I): return 'm'
    if re.search(r'\bFeminine$', t, re.I):  return 'f'
    if re.search(r'\bNeuter$', t, re.I):    return 'n'
    if re.search(r'\bM$', t): return 'm'
    if re.search(r'\bF$', t): return 'f'
    if re.search(r'\bN$', t): return 'n'
    return None

# ---------------------------------------------------------------- examples
# grammar/data/examples.tsv carries one example sentence per grid cell, keyed by
# the row's label and the 1-based column index. Cells that match get a hover
# balloon in the HTML. The file is optional: without it the tables render plain.
def load_examples():
    path = os.path.join(BASE, 'grammar', 'data', 'examples.tsv')
    out = {}
    if not os.path.isfile(path):
        return out
    for raw in io.open(path, encoding='utf-8'):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        parts = line.split('	')
        if len(parts) < 4:
            continue
        label, col, el, en = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
        if not col.isdigit():
            continue
        out[(label, int(col))] = (el, en)
    return out

EXAMPLES = load_examples()

# ---------------------------------------------------------------- blocks
SEP = re.compile(r'^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$')

def split_row(line):
    s = line.strip()
    if s.startswith('|'): s = s[1:]
    if s.endswith('|'):   s = s[:-1]
    return [c.strip() for c in s.split('|')]

def is_row(l):
    s = l.strip()
    return s.startswith('|') and s.endswith('|') and s.count('|') >= 2

# ---------------------------------------------------------------- grid cells
# The master grid reads better when the articles line up down the left edge and
# the ending sits at the right: what goes in front of the word and what goes on
# the end are then each in one vertical line, which is what you are memorising.
# Only that one table is reshaped - identified by its header - so the per-type
# tables further down keep their ordinary cells.
SPLIT_CELL = re.compile(r'^(.*?)\s*(\*\*-[^*]+\*\*)$')

def grid_kind(header):
    """'noun', 'adj' or None. Both are case x number grids; they differ in
    whether the row-label column survives (see the module note above)."""
    if not header:
        return None
    kind = {'Type': 'noun', 'Type & gender': 'adj',
            'Tense & group': 'verb'}.get(plain(header[0]).strip())
    # every data column must read '<group> <number>' for the band/toggle to work
    if not kind or len(header) < 5:
        return None
    if not all(' ' in plain(h).strip() for h in header[1:]):
        return None
    return kind

def split_cell(cell):
    """'ο / ένας **-ας**' -> articles stacked left, ending right. None if it does
    not have that shape, so an odd cell just renders normally."""
    m = SPLIT_CELL.match(cell.strip())
    if not m:
        return None
    arts = [a.strip() for a in m.group(1).split('/') if a.strip()]
    if not arts:
        return None
    return ('<span class="cell2"><span class="arts">%s</span>'
            '<span class="end">%s</span></span>'
            % (''.join('<span>%s</span>' % inline(a) for a in arts), inline(m.group(2))))

def by_case_order(cases):
    """Column indices regrouped so each case's numbers sit together:
    Nom-sg Nom-pl Acc-sg Acc-pl Gen-sg Gen-pl."""
    seen = []
    for c in cases:
        if c not in seen:
            seen.append(c)
    return [i for c in seen for i, cc in enumerate(cases) if cc == c]

PRONOUNS = {
    ('1st', 'singular'): u'\u03b5\u03b3\u03ce',
    ('2nd', 'singular'): u'\u03b5\u03c3\u03cd',
    ('3rd', 'singular'): u'\u03b1\u03c5\u03c4\u03cc\u03c2 / -\u03ae / -\u03cc',
    ('1st', 'plural'): u'\u03b5\u03bc\u03b5\u03af\u03c2',
    ('2nd', 'plural'): u'\u03b5\u03c3\u03b5\u03af\u03c2',
    ('3rd', 'plural'): u'\u03b1\u03c5\u03c4\u03bf\u03af / -\u03ad\u03c2 / -\u03ac',
}


def column_notes(header):
    """One pronoun per data column, or None if this is not a person grid. Keyed
    by the whole '<person> <number>' cell, because neither half alone decides
    it: 1st singular is εγώ, 1st plural is εμείς."""
    out = []
    for h in header[1:]:
        p = plain(h).strip().lower()
        a, b = p.rsplit(' ', 1) if ' ' in p else (p, '')
        out.append(PRONOUNS.get((a, b)))
    return out if any(out) else None


def grid_header(header, label=None, ann=None):
    """Both heads for the master grid, two rows each: grouped by number
    (Singular / Plural over the cases) and grouped by case (Nominative /
    Accusative / Genitive over the numbers). The inactive pair ships hidden and
    the toggle button swaps them, so neither layout costs a second table."""
    cap = lambda t: t[:1].upper() + t[1:]
    cols = [plain(h).strip() for h in header[1:]]
    cases, nums = [], []
    for c in cols:
        case, num = c.rsplit(' ', 1) if ' ' in c else (c, '')
        cases.append(case)
        nums.append(num)

    def band(labels):
        groups = []
        for l in labels:
            if groups and groups[-1][0] == l:
                groups[-1][1] += 1
            else:
                groups.append([l, 1])
        return ''.join('<th colspan="%d" class="grp">%s</th>'
                       % (n, html.escape(cap(l))) for l, n in groups)

    def names(labels, idx):
        out = []
        for l, i in zip(labels, idx):
            note = ann[i] if ann and i < len(ann) and ann[i] else ''
            out.append('<th>%s%s</th>'
                       % (html.escape(cap(l)),
                          '<span class="pron">%s</span>' % html.escape(note) if note else ''))
        return ''.join(out)

    order = by_case_order(cases)
    # A kept label column is cell 0 of every row, so the toggle's column order
    # has to name it first and shift the case columns up by one.
    lead = '<th rowspan="2" class="rowlab">%s</th>' % inline(label) if label else ''
    cells = [0] + [i + 1 for i in order] if label else order
    return (('<tr class="h-number">%s%s</tr><tr class="h-number">%s</tr>'
             '<tr class="h-case" hidden>%s%s</tr><tr class="h-case" hidden>%s</tr>')
            % (lead, band(nums), names(cases, range(len(cases))),
               lead, band([cases[i] for i in order]),
               names([nums[i] for i in order], order)),
            ','.join(str(i) for i in cells))

def render_table(header, rows, last_gender):
    ncol = len(header)
    col_g = [gender_of(plain(h)) for h in header]
    any_col = any(col_g)

    grid = grid_kind(header)

    row_g = []
    if not any_col:
        for r in rows:
            row_g.append(band_of(grid, plain(r[0])) if r else None)
    any_row = any(row_g)

    if grid:
        head, order = grid_header(
            header, plain(header[0]).strip() if grid != 'noun' else None,
            ann=column_notes(header))
        out = ['<div class="gridwrap">',
               '<button class="gridtog" type="button">Group by case</button>',
               '<div class="tw"><table class="grid grid-%s" data-grp="%s" '
               'data-order="%s">'
               % (grid, 'person' if grid == 'verb' else 'case', order),
               '<thead>%s</thead><tbody>' % head]
    else:
        out = ['<div class="tw"><table>']
    if not grid:
        out.append('<thead><tr>')
        for i, h in enumerate(header):
            cls = ' class="%s"' % col_g[i] if any_col and col_g[i] else ''
            out.append('<th%s>%s</th>' % (cls, inline(h)))
        out.append('</tr></thead><tbody>')
    for ri, r in enumerate(rows):
        r = (r + [''] * ncol)[:ncol]
        if any_col:
            g_for = lambda ci: col_g[ci]
        elif any_row:
            g_for = lambda ci, g=row_g[ri]: g
        elif last_gender:
            g_for = lambda ci: last_gender
        else:
            g_for = lambda ci: None
        out.append('<tr>')
        label = plain(r[0]).split(' — ')[0].strip()
        for ci, c in enumerate(r):
            if grid == 'noun' and ci == 0:
                continue
            g = g_for(ci)
            ex = EXAMPLES.get((label, ci))
            classes = ([g] if g else []) + (['hasex'] if ex else [])
            cls = ' class="%s"' % ' '.join(classes) if classes else ''
            extra = ''
            if ex:
                extra = ' data-el="%s" data-en="%s"' % (
                    html.escape(ex[0], True), html.escape(ex[1], True))
            body = None
            if grid and ci > 0:
                body = split_cell(c)
            out.append('<td%s%s>%s</td>' % (cls, extra, body or inline(c)))
        out.append('</tr>')
    out.append('</tbody></table></div>' + ('</div>' if grid else ''))
    return ''.join(out)

def md_to_html(md):
    lines = md.replace('\r\n', '\n').split('\n')
    out, i, n = [], 0, len(lines)
    last_gender = None
    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1; continue

        if s.startswith('```'):
            i += 1; buf = []
            while i < n and not lines[i].strip().startswith('```'):
                buf.append(lines[i]); i += 1
            i += 1
            out.append('<pre>%s</pre>' % html.escape('\n'.join(buf)))
            continue

        if re.match(r'^(---+|\*\*\*+|___+)$', s):
            out.append('<hr>'); i += 1; continue

        hm = re.match(r'^(#{1,6})\s+(.*)$', s)
        if hm:
            lvl = min(len(hm.group(1)), 4)
            txt = hm.group(2)
            last_gender = gender_of(plain(txt))
            out.append('<h%d>%s</h%d>' % (lvl, inline(txt), lvl))
            i += 1; continue

        if is_row(line) and i + 1 < n and SEP.match(lines[i + 1]):
            header = split_row(line); i += 2
            rows = []
            while i < n and is_row(lines[i]):
                rows.append(split_row(lines[i])); i += 1
            out.append(render_table(header, rows, last_gender))
            continue

        if re.match(r'^[-*+]\s+', s):
            items = []
            while i < n and re.match(r'^\s*[-*+]\s+', lines[i]):
                items.append(inline(re.sub(r'^\s*[-*+]\s+', '', lines[i]))); i += 1
            out.append('<ul>%s</ul>' % ''.join('<li>%s</li>' % x for x in items))
            continue

        if re.match(r'^\d+[.)]\s+', s):
            items = []
            while i < n and re.match(r'^\s*\d+[.)]\s+', lines[i]):
                items.append(inline(re.sub(r'^\s*\d+[.)]\s+', '', lines[i]))); i += 1
            out.append('<ol>%s</ol>' % ''.join('<li>%s</li>' % x for x in items))
            continue

        if s.startswith('>'):
            buf = []
            while i < n and lines[i].strip().startswith('>'):
                buf.append(re.sub(r'^\s*>\s?', '', lines[i])); i += 1
            out.append('<blockquote>%s</blockquote>' % inline(' '.join(buf)))
            continue

        buf = [s]; i += 1
        while i < n:
            nx = lines[i]; ns = nx.strip()
            if (not ns or ns.startswith(('#', '```', '>')) or is_row(nx)
                    or re.match(r'^(---+|\*\*\*+|___+)$', ns)
                    or re.match(r'^[-*+]\s+', ns) or re.match(r'^\d+[.)]\s+', ns)):
                break
            buf.append(ns); i += 1
        out.append('<p>%s</p>' % inline(' '.join(buf)))
    return '\n'.join(out)

# ---------------------------------------------------------------- css
CSS = """
:root{
  /* must advertise dark support at all times: Chrome's force-dark feature
     inverts any page whose root resolves to light-only, which black-holed
     the Light setting. The pinned themes below use the `only` keyword,
     which is the explicit opt-out. */
  color-scheme:light dark;
  --bg:#ffffff; --fg:#1a1d21; --h3:#243040; --muted:#5b6470; --line:#dfe3e8;
  --head:#f4f6f8; --accent:#0b6ea8;
  --m-bg:#dbeafe; --m-fg:#12243d;
  --f-bg:#ede0ff; --f-fg:#2b1741;
  --n-bg:#dcfce7; --n-fg:#12301f;
  --warn:#b54708;
  --pr-bg:#fef3c7; --pr-fg:#3d2c06;
  --pa-bg:#ffe4e6; --pa-fg:#4a1020;
  --fu-bg:#cffafe; --fu-fg:#0a3340;
  --toc-bg:#fbfcfd; --zebra:#fafbfc; --code-bg:#f2f4f7;
  --pre-bg:#f7f9fb; --quote-bg:#f7fbfd; --btn-bg:#f4f6f8;
}

/* dark palette: applied when the system asks for it and the reader has not
   pinned light, or when the toggle pins dark */
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme:only dark;
    --bg:#14171a; --fg:#e6e8ea; --h3:#cdd6de; --muted:#9aa6b2; --line:#2b3238;
    --head:#1d2329; --accent:#7cbcea;
    --m-bg:#17314f; --m-fg:#d3e4ff;
    --f-bg:#2f2450; --f-fg:#e8dcff;
    --n-bg:#16351f; --n-fg:#cfeeda;
    --warn:#f0a066;
    --pr-bg:#3d3308; --pr-fg:#fbeec2;
    --pa-bg:#40202b; --pa-fg:#ffdbe3;
    --fu-bg:#0c3440; --fu-fg:#c7f1fa;
    --toc-bg:#181c20; --zebra:#181c20; --code-bg:#22282e;
    --pre-bg:#1a1f24; --quote-bg:#191f25; --btn-bg:#1f252b;
  }
}
:root[data-theme="dark"]{
  color-scheme:only dark;
  --bg:#14171a; --fg:#e6e8ea; --h3:#cdd6de; --muted:#9aa6b2; --line:#2b3238;
  --head:#1d2329; --accent:#7cbcea;
  --m-bg:#17314f; --m-fg:#d3e4ff;
  --f-bg:#2f2450; --f-fg:#e8dcff;
  --n-bg:#16351f; --n-fg:#cfeeda;
  --warn:#f0a066;
  --pr-bg:#3d3308; --pr-fg:#fbeec2;
  --pa-bg:#40202b; --pa-fg:#ffdbe3;
  --fu-bg:#0c3440; --fu-fg:#c7f1fa;
  --toc-bg:#181c20; --zebra:#181c20; --code-bg:#22282e;
  --pre-bg:#1a1f24; --quote-bg:#191f25; --btn-bg:#1f252b;
}

:root[data-theme="light"]{ color-scheme:only light; }

.theme-toggle{
  position:fixed; top:12px; right:14px; z-index:60;
  display:inline-flex; align-items:center; gap:7px;
  font:inherit; font-size:13px; line-height:1; padding:8px 12px;
  border-radius:999px; cursor:pointer;
  background:var(--btn-bg); color:var(--fg); border:1px solid var(--line);
  box-shadow:0 1px 3px rgba(0,0,0,.10);
}
.theme-toggle:hover{border-color:var(--accent)}
.theme-toggle:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.theme-toggle .ico{font-size:14px}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--fg);
  font:16px/1.55 "Segoe UI","Helvetica Neue",Arial,"Noto Sans",sans-serif;
}
.wrap{display:flex; align-items:flex-start; gap:28px; max-width:1280px; margin:0 auto; padding:24px 20px 80px}
/* the sheet column must be allowed to be narrower than its widest table,
   or a wide table stretches the page instead of scrolling inside .tw */
.wrap > main{flex:1 1 auto; min-width:0; width:100%}
nav.toc{
  position:sticky; top:16px; flex:0 0 250px; max-height:calc(100vh - 40px);
  overflow:auto; border:1px solid var(--line); border-radius:10px; padding:14px 16px; background:var(--toc-bg);
}
nav.toc h2{margin:0 0 10px; font-size:13px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted)}
nav.toc ol{margin:0; padding-left:22px}
nav.toc li{margin:3px 0; font-size:14px}
nav.toc a{color:var(--fg); text-decoration:none}
nav.toc a:hover{color:var(--accent); text-decoration:underline}
main{flex:1 1 auto; min-width:0}
section.sheet{border-bottom:1px solid var(--line); padding-bottom:26px; margin-bottom:34px}
section.sheet:last-child{border-bottom:0}
h1{font-size:27px; line-height:1.2; margin:6px 0 16px; letter-spacing:-.01em}
h2{font-size:20px; margin:28px 0 10px; padding-top:4px}
h3{font-size:16.5px; margin:22px 0 8px; color:var(--h3)}
h4{font-size:15px; margin:18px 0 6px; color:var(--muted)}
p{margin:9px 0}
ul,ol{margin:9px 0 9px 22px; padding:0}
li{margin:3px 0}
hr{border:0; border-top:1px solid var(--line); margin:26px 0}
code{background:var(--code-bg); padding:1px 5px; border-radius:4px; font-size:.9em;
     font-family:"Cascadia Mono",Consolas,monospace}
pre{background:var(--pre-bg); border:1px solid var(--line); border-left:3px solid var(--accent);
    padding:11px 13px; border-radius:6px; overflow-x:auto; font-size:13.5px;
    font-family:"Cascadia Mono",Consolas,monospace; line-height:1.5}
blockquote{margin:12px 0; padding:8px 14px; border-left:3px solid var(--accent);
           background:var(--quote-bg); color:var(--muted)}
.tw{overflow-x:auto; margin:12px 0 16px}
table{border-collapse:collapse; width:100%; font-size:14.5px}
th,td{border:1px solid var(--line); padding:7px 10px; text-align:left; vertical-align:top}
thead th{background:var(--head); font-weight:600; white-space:nowrap}
tbody tr:nth-child(even) td:not(.m):not(.f):not(.n):not(.pr):not(.pa):not(.fu){background:var(--zebra)}
td.pr,th.pr{background:var(--pr-bg); color:var(--pr-fg)}
td.pa,th.pa{background:var(--pa-bg); color:var(--pa-fg)}
td.fu,th.fu{background:var(--fu-bg); color:var(--fu-fg)}
.legend .pr{background:var(--pr-bg); color:var(--pr-fg)}
.legend .pa{background:var(--pa-bg); color:var(--pa-fg)}
.legend .fu{background:var(--fu-bg); color:var(--fu-fg)}
td.m,th.m{background:var(--m-bg); color:var(--m-fg)}
td.f,th.f{background:var(--f-bg); color:var(--f-fg)}
td.n,th.n{background:var(--n-bg); color:var(--n-fg)}
th.m,th.f,th.n{font-weight:700}
.legend{display:flex; flex-wrap:wrap; gap:8px; margin:10px 0 0; font-size:13px}
.legend span{padding:3px 9px; border-radius:5px; border:1px solid var(--line)}
.legend .m{background:var(--m-bg); color:var(--m-fg)}
.legend .f{background:var(--f-bg); color:var(--f-fg)}
.legend .n{background:var(--n-bg); color:var(--n-fg)}
header.top{max-width:1280px; margin:0 auto; padding:26px 20px 0}
header.top h1{font-size:31px; margin:0 0 4px}
header.top p{color:var(--muted); margin:0}

@media (max-width:900px){
  /* stacked: align-items must stretch, otherwise flex-start sizes the column
     to its content and the page itself scrolls sideways */
  .wrap{flex-direction:column; gap:14px; align-items:stretch}
  nav.toc{position:static; width:100%; flex:none; max-height:none}
}

/* ---- phones ------------------------------------------------------------- */
/* Wide tables are the whole problem on a small screen: they cannot shrink past
   their content, so instead of squeezing the page they get their own scroller
   that runs edge to edge. Everything else just steps down a size. */
@media (max-width:560px){
  body{font-size:15px}
  .wrap{padding:14px 12px 56px; gap:12px}
  header.top{padding:18px 12px 0}
  header.top h1{font-size:22px; line-height:1.25}
  header.top p{font-size:13px}
  h1{font-size:20px; margin:4px 0 12px}
  h2{font-size:17px; margin:22px 0 8px}
  h3{font-size:15px; margin:16px 0 6px}
  h4{font-size:14px}
  nav.toc{padding:11px 13px}
  nav.toc li{font-size:13.5px}
  /* full-bleed scroller: the negative margin exactly cancels .wrap's padding */
  .tw{margin-left:-12px; margin-right:-12px; padding-left:12px; padding-right:12px;
      -webkit-overflow-scrolling:touch}
  table{font-size:13px}
  th,td{padding:5px 7px}
  table.grid{font-size:12.5px}
  table.grid th,table.grid td{padding:3px 6px}
  table.grid .cell2{gap:7px}
  pre{font-size:12.5px; padding:9px 11px}
  .theme-toggle{top:8px; right:8px; padding:6px 9px; font-size:12px}
  .theme-toggle .lbl{display:none}
  .legend{font-size:12px}
  /* the balloon must never be wider than the screen */
  .extip{max-width:calc(100vw - 20px); font-size:13px}
}

@media print{
  /* the PDF must not inherit a dark choice */
  :root,:root[data-theme="dark"],:root[data-theme="light"]{
    color-scheme:only light;
    --bg:#ffffff; --fg:#1a1d21; --h3:#243040; --muted:#5b6470; --line:#dfe3e8;
    --head:#f4f6f8; --accent:#0b6ea8;
    --m-bg:#dbeafe; --m-fg:#12243d;
    --f-bg:#ede0ff; --f-fg:#2b1741;
    --n-bg:#dcfce7; --n-fg:#12301f;
    --pr-bg:#fef3c7; --pr-fg:#3d2c06;
    --pa-bg:#ffe4e6; --pa-fg:#4a1020;
    --fu-bg:#cffafe; --fu-fg:#0a3340;
    --toc-bg:#fbfcfd; --zebra:#fafbfc; --code-bg:#f2f4f7;
    --pre-bg:#f7f9fb; --quote-bg:#f7fbfd; --btn-bg:#f4f6f8;
  }
  .theme-toggle{display:none !important}
  @page{size:A4; margin:13mm 11mm}
  body{font-size:10.5pt; background:#fff}
  .wrap{display:block; padding:0; max-width:none}
  nav.toc{display:none}
  header.top{padding:0 0 8pt}
  section.sheet{break-before:page; page-break-before:always;
                border-bottom:0; margin:0; padding:0}
  section.sheet:first-of-type{break-before:auto; page-break-before:auto}
  h1{font-size:17pt; margin:0 0 8pt}
  h2{font-size:12.5pt; margin:12pt 0 5pt; break-after:avoid; page-break-after:avoid}
  h3{font-size:11pt; margin:9pt 0 4pt; break-after:avoid; page-break-after:avoid}
  table{font-size:8.6pt; width:100%}
  th,td{padding:2.6pt 4pt}
  thead{display:table-header-group}
  tr,img{break-inside:avoid; page-break-inside:avoid}
  .tw{overflow:visible}
  a{color:inherit; text-decoration:none}
  td.m,th.m,td.f,th.f,td.n,th.n,td.pr,td.pa,td.fu{-webkit-print-color-adjust:exact;
    print-color-adjust:exact}
  tbody tr:nth-child(even) td:not(.m):not(.f):not(.n):not(.pr):not(.pa):not(.fu){background:transparent}
}
/* ---- example balloons on the master grid -------------------------------- */
/* a cell with an example gets a small corner dot; the balloon itself is one
   element reused for every cell, positioned by script. */
td.hasex{position:relative;cursor:help}
td.hasex::after{
  content:"";position:absolute;top:4px;right:4px;width:5px;height:5px;
  border-radius:50%;background:currentColor;opacity:.32;
}
td.hasex:hover::after{opacity:.75}
.extip{
  position:absolute;z-index:80;max-width:300px;padding:9px 12px;
  border:1px solid var(--line);border-radius:9px;background:var(--head);
  color:var(--fg);box-shadow:0 8px 22px rgba(0,0,0,.28);
  font-size:13.5px;line-height:1.45;pointer-events:none;
}
.extip .el{font-weight:600}
.extip .en{margin-top:3px;color:var(--muted);font-size:12.5px}
.extip::after{
  content:"";position:absolute;left:50%;margin-left:-6px;bottom:-6px;
  width:11px;height:11px;background:var(--head);
  border-right:1px solid var(--line);border-bottom:1px solid var(--line);
  transform:rotate(45deg);
}
.extip.below::after{bottom:auto;top:-6px;transform:rotate(225deg)}
/* paper has no hover: drop the marker so the grid prints clean */
@media print{ td.hasex::after{display:none} .extip{display:none} .gridtog{display:none} }
/* master-grid cells: the articles stack down the left, the ending is pinned
   right, so prefix and suffix each read as one vertical column */
td .cell2{display:flex;align-items:center;justify-content:space-between;gap:10px}
td .cell2 .arts{display:flex;flex-direction:column;align-items:flex-start;line-height:1.3}
td .cell2 .end{white-space:nowrap;text-align:right}
/* master grid: no type column, a Singular/Plural band over the case names, and
   cells sized to their content instead of stretched across the page */
table.grid{width:auto; font-size:13.5px}
table.grid th,table.grid td{padding:4px 8px}
table.grid thead th.grp{text-align:center; letter-spacing:.04em}
/* the pronoun under a person heading: which εγώ / εμείς that column means */
table.grid thead th .pron{display:block; font-weight:400; font-size:11.5px; opacity:.72;
  letter-spacing:0; white-space:nowrap}
table.grid .cell2{gap:9px}
/* the adjective grid keeps its row label: type A masculine and type B masculine
   have the same six endings, so the cells alone would not say which row is which */
table.grid-adj th.rowlab,table.grid-verb th.rowlab{text-align:left}
table.grid-adj tbody td:first-child,table.grid-verb tbody td:first-child{
  font-size:12.5px; line-height:1.34; max-width:15em}
.gridwrap{margin:12px 0 16px}
.gridwrap .tw{margin:6px 0 0}
.gridtog{font:inherit; font-size:12.5px; line-height:1; padding:6px 11px; border-radius:999px;
  background:var(--btn-bg); color:var(--fg); border:1px solid var(--line); cursor:pointer}
.gridtog:hover{border-color:var(--accent)}
.gridtog:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
table.grid tr[hidden]{display:none}
"""

# ------------------------------------------------------- theme switch pieces
# Runs before first paint so a pinned dark choice does not flash white.
# ------------------------------------------------------------ favicon
# Inline SVG so the pages stay self-contained and no extra file has to be
# served. The grammar sheets get a Greek alpha on blue; the keyboard page
# (hand-written, not generated here) carries its own purple keyboard mark, so
# the two are told apart by both shape and colour in a row of tabs.
FAVICON = (
    '<link rel="icon" href="data:image/svg+xml,'
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
    "<rect width='64' height='64' rx='13' fill='%230b6ea8'/>"
    "<text x='32' y='48' text-anchor='middle' font-family='Georgia,serif'"
    " font-size='46' fill='%23ffffff'>&#945;</text>"
    '</svg>">'
)

THEME_HEAD = (
    '<script>(function(){try{var t=localStorage.getItem("greek-a2-theme");'
    'if(t==="dark"||t==="light")document.documentElement.setAttribute("data-theme",t);}'
    'catch(e){}})();</script>'
)

THEME_BTN = ('<button class="theme-toggle" id="themeToggle" type="button">'
             '<span class="ico" aria-hidden="true">◐</span>'
             '<span class="lbl">Auto</span></button>')

# Cycles Auto -> Light -> Dark. "Auto" removes the attribute so the
# prefers-color-scheme media query takes over again.
THEME_JS = (
    '<script>(function(){'
    'var KEY="greek-a2-theme",r=document.documentElement,'
    'b=document.getElementById("themeToggle");if(!b)return;'
    'var ico=b.querySelector(".ico"),lbl=b.querySelector(".lbl");'
    'function read(){try{return localStorage.getItem(KEY)||"auto";}catch(e){return "auto";}}'
    'function paint(m){'
    'if(m==="auto"){r.removeAttribute("data-theme");}else{r.setAttribute("data-theme",m);}'
    'ico.textContent=(m==="dark")?"☾":((m==="light")?"☀":"◐");'
    'lbl.textContent=(m==="dark")?"Dark":((m==="light")?"Light":"Auto");'
    'b.setAttribute("aria-label","Colour theme: "+lbl.textContent+". Click to change.");'
    'b.setAttribute("title","Colour theme: "+lbl.textContent+" (click to change)");}'
    'var m=read();paint(m);'
    'b.addEventListener("click",function(){'
    'm=(m==="auto")?"light":((m==="light")?"dark":"auto");'
    'try{if(m==="auto"){localStorage.removeItem(KEY);}else{localStorage.setItem(KEY,m);}}catch(e){}'
    'paint(m);});'
    '})();</script>'
)


# ----------------------------------------------------- example balloons
# One reused balloon element. Hover (after a short delay) on the desktop,
# tap to toggle on touch, and it never lingers over something it no longer
# describes: scroll, resize, blur and Escape all dismiss it.
EX_JS = (
    '<script>(function(){'
    'var cells=document.querySelectorAll("td.hasex");if(!cells.length)return;'
    'var tip=document.createElement("div");tip.className="extip";tip.hidden=true;'
    'document.body.appendChild(tip);'
    'function mk(c){var d=document.createElement("div");d.className=c;tip.appendChild(d);return d;}'
    'var el=mk("el"),en=mk("en"),timer=null,cur=null;'
    'function hide(){if(timer){clearTimeout(timer);timer=null;}tip.hidden=true;cur=null;}'
    'function show(td){'
    'cur=td;el.textContent=td.getAttribute("data-el")||"";'
    'en.textContent=td.getAttribute("data-en")||"";'
    'tip.hidden=false;tip.classList.remove("below");'
    'var r=td.getBoundingClientRect(),w=tip.offsetWidth,h=tip.offsetHeight;'
    'var vw=document.documentElement.clientWidth;'
    'var left=window.pageXOffset+r.left+r.width/2-w/2;'
    'left=Math.max(window.pageXOffset+8,Math.min(left,window.pageXOffset+vw-w-8));'
    'var top=window.pageYOffset+r.top-h-10;'
    'if(top<window.pageYOffset+4){top=window.pageYOffset+r.bottom+10;tip.classList.add("below");}'
    'tip.style.left=left+"px";tip.style.top=top+"px";}'
    'function near(e){return e.target&&e.target.closest?e.target.closest("td.hasex"):null;}'
    'document.addEventListener("mouseover",function(e){'
    'var td=near(e);if(!td||td===cur)return;'
    'if(timer)clearTimeout(timer);timer=setTimeout(function(){show(td);},250);});'
    'document.addEventListener("mouseout",function(e){if(near(e))hide();});'
    'document.addEventListener("click",function(e){'
    'var td=near(e);'
    'if(!td){hide();return;}'
    'if(cur===td){hide();return;}'
    'if(timer)clearTimeout(timer);show(td);});'
    'window.addEventListener("scroll",hide,true);'
    'window.addEventListener("resize",hide);'
    'window.addEventListener("blur",hide);'
    'document.addEventListener("keydown",function(e){if(e.key==="Escape")hide();});'
    '})();</script>'
)

# ----------------------------------------------------- plain-text copy
# Ctrl+C anywhere yields plain text only: cancelling the event means the
# clipboard is filled solely from what we set, so the text/html flavour is
# never written and paste targets cannot pick up the table markup.
#
# Selections inside a table are rebuilt cell by cell rather than handed to the
# browser's serialiser. The master grid stacks its articles, and the serialiser
# turns every stacked line into a newline, which would leave a copied row as a
# column of fragments. Rebuilding keeps one row per line and one tab per cell,
# so a copied table still pastes into a spreadsheet as a grid.
COPY_JS = (
    '<script>(function(){'
    'function cellText(td){'
    'var c=td.querySelector(".cell2");'
    'if(c){var a=[].map.call(c.querySelectorAll(".arts span"),function(s){'
    'return s.textContent.trim();});'
    'var e=c.querySelector(".end");'
    'return a.join(" / ")+(e?" "+e.textContent.trim():"");}'
    r'return td.textContent.replace(/\s+/g," ").trim();}'
    'document.addEventListener("copy",function(ev){'
    'var s=window.getSelection();if(!s||s.isCollapsed||!s.rangeCount)return;'
    'var cd=ev.clipboardData||window.clipboardData;if(!cd)return;'
    'var r=s.getRangeAt(0);'
    'var el=r.commonAncestorContainer;'
    'if(el.nodeType!==1)el=el.parentElement;'
    'var table=el&&el.closest?el.closest("table"):null;'
    'var t;'
    'if(table){'
    'var cell=el.closest("td,th");'
    'if(cell&&cell.contains(r.startContainer)&&cell.contains(r.endContainer)){'
    r't=s.toString().replace(/\s*\n\s*/g," ").trim();}'
    'else{var out=[];'
    '[].forEach.call(table.querySelectorAll("tr"),function(tr){'
    'if(!s.containsNode(tr,true))return;'
    'var cells=[].filter.call(tr.children,function(c){return s.containsNode(c,true);});'
    r'out.push(cells.map(cellText).join("\t"));});'
    r't=out.join("\n");}}'
    'else{t=s.toString();}'
    'if(!t)return;'
    'try{cd.setData("text/plain",t);}catch(err){return;}'
    'ev.preventDefault();});'
    '})();</script>'
)

# ----------------------------------------------------- grid grouping toggle
# The same six columns read two ways: by number (Singular | Plural over the
# cases) or by case (Nominative | Accusative | Genitive over the numbers).
# Both heads are already in the table; the body cells are moved with
# appendChild, which reorders without re-rendering, so the balloons and their
# data attributes travel with their own cells. The choice is remembered.
GRID_JS = (
    '<script>(function(){'
    '[].forEach.call(document.querySelectorAll(".gridwrap"),function(wrap){'
    'var t=wrap.querySelector("table.grid");if(!t||!t.tBodies.length)return;'
    'var btn=wrap.querySelector(".gridtog");if(!btn)return;'
    'var grp=t.getAttribute("data-grp")||"case";'
    'var order=(t.getAttribute("data-order")||"").split(",").map(Number);'
    'if(!order.length||order.some(isNaN))return;'
    'var rows=[].slice.call(t.tBodies[0].rows);'
    'var orig=rows.map(function(r){return [].slice.call(r.cells);});'
    'var flat=orig.length?orig[0].map(function(_,i){return i;}):[];'
    'var mode="number";'
    'function apply(m){'
    'mode=m;'
    'var ord=(m==="case")?order:flat;'
    'rows.forEach(function(r,i){ord.forEach(function(ci){'
    'if(orig[i][ci])r.appendChild(orig[i][ci]);});});'
    '[].forEach.call(t.querySelectorAll("tr.h-number"),function(tr){tr.hidden=(m!=="number");});'
    '[].forEach.call(t.querySelectorAll("tr.h-case"),function(tr){tr.hidden=(m!=="case");});'
    'btn.textContent=(m==="number")?("Group by "+grp):"Group by number";'
    'btn.setAttribute("aria-label",(m==="number")'
    '?("Columns grouped by number. Switch to grouping by "+grp+".")'
    ':("Columns grouped by "+grp+". Switch to grouping by number."));'
    'try{localStorage.setItem("greek-a2-grid",m);}catch(e){}}'
    'var saved=null;try{saved=localStorage.getItem("greek-a2-grid");}catch(e){}'
    'apply(saved==="case"?"case":"number");'
    'btn.addEventListener("click",function(){apply(mode==="number"?"case":"number");});'
    '});'
    '})();</script>'
)

def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

def first_h1(md, fallback):
    m = re.search(r'^#\s+(.*)$', md, re.M)
    return plain(m.group(1)) if m else fallback

def main():
    files = [os.path.join(BASE, 'index.md')] + sorted(
        glob.glob(os.path.join(BASE, 'grammar', '*.md')))
    files = [f for f in files if os.path.isfile(f)]

    os.makedirs(PAGES, exist_ok=True)

    sheets = []
    for f in files:
        md = io.open(f, encoding='utf-8').read()
        name = os.path.basename(f)
        title = first_h1(md, name)
        sheets.append({'file': name, 'title': title,
                       'id': slug(os.path.splitext(name)[0]),
                       'body': md_to_html(md)})

    legend = ('<div class="legend"><span class="m">masculine</span>'
              '<span class="f">feminine</span><span class="n">neuter</span></div>')

    toc = ''.join('<li><a href="#%s">%s</a></li>' % (s['id'], html.escape(s['title']))
                  for s in sheets)
    body = ''.join('<section class="sheet" id="%s">%s</section>' % (s['id'], s['body'])
                   for s in sheets)

    doc = ('<!doctype html><html lang="el"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">'
           '<meta name="color-scheme" content="light dark">'
           '<title>Greek A2 — Grammar Drill Sheets</title><style>%s</style>%s%s</head><body>'
           '%s'
           '<header class="top"><h1>Greek A2 — Grammar Drill Sheets</h1>'
           '<p>%d sheets · A2 scope · cover the right column and recite</p>%s</header>'
           '<div class="wrap"><nav class="toc"><h2>Contents</h2><ol>%s</ol></nav>'
           '<main>%s</main></div>%s</body></html>'
           % (CSS, FAVICON, THEME_HEAD, THEME_BTN, len(sheets), legend, toc, body,
              THEME_JS + EX_JS + COPY_JS + GRID_JS))

    out_html = os.path.join(DIST, 'index.html')
    io.open(out_html, 'w', encoding='utf-8', newline='\n').write(doc)

    for s in sheets:
        page = ('<!doctype html><html lang="el"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<meta name="color-scheme" content="light dark">'
                '<title>%s</title><style>%s</style>%s%s</head><body>'
                '%s<div class="wrap"><main><section class="sheet">%s</section></main></div>'
                '%s</body></html>' % (html.escape(s['title']), CSS, FAVICON, THEME_HEAD,
                                      THEME_BTN, s['body'], THEME_JS + EX_JS + COPY_JS + GRID_JS))
        stem = os.path.splitext(s['file'])[0]
        if stem == 'index':
            stem = 'index-sheet'      # avoid creating pages/index.html
        io.open(os.path.join(PAGES, stem + '.html'),
                'w', encoding='utf-8', newline='\n').write(page)

    print('html   : %s  (%.1f KB)' % (out_html, os.path.getsize(out_html) / 1024.0))
    print('pages  : %d files in %s' % (len(sheets), PAGES))

    if '--no-pdf' in sys.argv:
        print('pdf    : skipped (--no-pdf)')
    else:
        make_pdf(out_html)
    make_grid_sheet()
    make_adjective_grid()
    make_verb_grid()
    make_mega_grid()
    return out_html


CHROME_CANDIDATES = [
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
]


def make_pdf(out_html):
    """Print the combined HTML to PDF with headless Chrome.

    Background colours (the gender bands) survive because the print CSS sets
    print-color-adjust: exact.
    """
    exe = next((p for p in CHROME_CANDIDATES if os.path.isfile(p)), None)
    if not exe:
        print('pdf    : skipped - no Chrome/Edge found')
        return None
    out_pdf = os.path.join(DIST, 'greek-a2.pdf')
    cmd = [exe, '--headless=new', '--disable-gpu', '--no-first-run',
           '--no-default-browser-check', '--no-pdf-header-footer',
           '--print-to-pdf=' + out_pdf,
           'file:///' + out_html.replace(os.sep, '/')]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=180, check=False)
    except Exception as e:
        print('pdf    : failed (%s)' % e)
        return None
    if os.path.isfile(out_pdf):
        print('pdf    : %s  (%.2f MB)' % (out_pdf, os.path.getsize(out_pdf) / 1048576.0))
        return out_pdf
    print('pdf    : not produced')
    return None


# ------------------------------------------------- printable one-page grid
# master-grid.pdf: the master grid alone, grouped by case, sized to one A4
# page so it can be printed and pinned up. The toggle cannot come to paper,
# so the printed sheet commits to the case grouping.
GRID_SHEET_CSS = """
@page{size:A4 portrait; margin:11mm 10mm}
/* The band colours are the sheets’ own, as custom properties so the page can
   follow the theme. Pinned light they left masculine (#12243d) and feminine
   (#2b1741) reading as plain black next to a visibly green neuter. */
:root{
  color-scheme:light dark;
  --pg:#fff; --ink:#12161a; --sub:#5b6470; --rule:#b9c1c9; --band:#eef1f4; --note:#3d4650;
  --m-bg:#dbeafe; --m-fg:#12243d;
  --f-bg:#ede0ff; --f-fg:#2b1741;
  --n-bg:#dcfce7; --n-fg:#12301f;
  --pr-bg:#fef3c7; --pr-fg:#3d2c06;
  --pa-bg:#ffe4e6; --pa-fg:#4a1020;
  --fu-bg:#cffafe; --fu-fg:#0a3340;
}
@media screen and (prefers-color-scheme:dark){
  :root{
    --pg:#14171a; --ink:#e6e8ea; --sub:#9aa6b2; --rule:#2b3238; --band:#1d2329;
    --note:#9aa6b2;
    --m-bg:#17314f; --m-fg:#d3e4ff;
    --f-bg:#2f2450; --f-fg:#e8dcff;
    --n-bg:#16351f; --n-fg:#cfeeda;
    --pr-bg:#3d3308; --pr-fg:#fbeec2;
    --pa-bg:#40202b; --pa-fg:#ffdbe3;
    --fu-bg:#0c3440; --fu-fg:#c7f1fa;
  }
}
*{box-sizing:border-box}
body{margin:0; background:var(--pg); color:var(--ink);
  font:11.5pt/1.42 "Segoe UI","Helvetica Neue",Arial,"Noto Sans",sans-serif;
  -webkit-print-color-adjust:exact; print-color-adjust:exact}
h1{font-size:18pt; margin:0 0 1.5mm; letter-spacing:-.01em}
.sub{font-size:10pt; color:var(--sub); margin:0 0 4mm}
table{border-collapse:collapse; width:100%; font-size:12.6pt; table-layout:fixed}
th,td{border:.5pt solid var(--rule); padding:4.2pt 6pt; text-align:left; vertical-align:middle}
thead th{background:var(--band); font-weight:700}
thead th.grp{text-align:center; letter-spacing:.05em; font-size:12pt}
thead th .pron{display:block; font-weight:400; font-size:8.6pt; opacity:.72; white-space:nowrap}
td.m{background:var(--m-bg); color:var(--m-fg)}
td.f{background:var(--f-bg); color:var(--f-fg)}
td.n{background:var(--n-bg); color:var(--n-fg)}
td.pr{background:var(--pr-bg); color:var(--pr-fg)}
td.pa{background:var(--pa-bg); color:var(--pa-fg)}
td.fu{background:var(--fu-bg); color:var(--fu-fg)}
.cell2{display:flex; align-items:center; justify-content:space-between; gap:7pt}
.arts{display:flex; flex-direction:column; align-items:flex-start; line-height:1.2}
.end{white-space:nowrap; font-weight:700}
.notes{margin:4mm 0 0; font-size:9.2pt; color:var(--note); line-height:1.45}
.notes b{color:var(--ink)}
.legend{display:flex; gap:5mm; font-size:9.2pt; margin:0 0 3mm}
.legend span{padding:1pt 5pt; border:.4pt solid var(--rule); border-radius:2pt}
.legend .m{background:var(--m-bg); color:var(--m-fg)}
.legend .f{background:var(--f-bg); color:var(--f-fg)}
.legend .n{background:var(--n-bg); color:var(--n-fg)}
.legend .pr{background:var(--pr-bg); color:var(--pr-fg)}
.legend .pa{background:var(--pa-bg); color:var(--pa-fg)}
.legend .fu{background:var(--fu-bg); color:var(--fu-fg)}
.legend.people{display:block; font-size:9pt; color:var(--note); margin:0 0 3mm}
/* Paper is always light. Headless Chrome reports prefers-color-scheme: dark, so
   without this master-grid.pdf would print on a near-black page. */
@media print{
  :root{
    color-scheme:only light;
    --pg:#fff; --ink:#12161a; --sub:#5b6470; --rule:#b9c1c9; --band:#eef1f4; --note:#3d4650;
    --m-bg:#dbeafe; --m-fg:#12243d;
    --f-bg:#ede0ff; --f-fg:#2b1741;
    --n-bg:#dcfce7; --n-fg:#12301f;
    --pr-bg:#fef3c7; --pr-fg:#3d2c06;
    --pa-bg:#ffe4e6; --pa-fg:#4a1020;
    --fu-bg:#cffafe; --fu-fg:#0a3340;
  }
}
"""


def find_master_grid(md, kind='noun'):
    """Pull a master grid out of a sheet's markdown: (header, rows)."""
    lines = md.replace('\r\n', '\n').split('\n')
    for i, line in enumerate(lines):
        if not (is_row(line) and i + 1 < len(lines) and SEP.match(lines[i + 1])):
            continue
        header = split_row(line)
        if grid_kind(header) != kind:
            continue
        rows, j = [], i + 2
        while j < len(lines) and is_row(lines[j]):
            rows.append(split_row(lines[j]))
            j += 1
        return header, rows
    return None, None


def render_print_grid(header, rows, order, outer, inner, label=None, balloons=False,
                      kind='noun', keys=None, bands=None, ann=None):
    """One grid with the columns in `order`, banded by `outer` over `inner`.
    `label` keeps the row-label column (the noun grid drops it); `balloons` adds
    the example-sentence markers, which only make sense on a screen."""
    cap = lambda t: t[:1].upper() + t[1:]
    groups = []
    for l in outer:
        if groups and groups[-1][0] == l:
            groups[-1][1] += 1
        else:
            groups.append([l, 1])
    out = ['<table><thead><tr>']
    if label:
        out.append('<th rowspan="2" class="rowlab">%s</th>' % inline(label))
    out.append(''.join('<th colspan="%d" class="grp">%s</th>'
                       % (n, html.escape(cap(l))) for l, n in groups))
    out.append('</tr><tr>')
    out.append(''.join(
        '<th>%s%s</th>'
        % (html.escape(cap(l)),
           '<span class="pron">%s</span>' % html.escape(ann[i]) if ann and ann[i] else '')
        for i, l in enumerate(inner)))
    out.append('</tr></thead><tbody>')
    for ri, r in enumerate(rows):
        g = bands[ri] if bands else band_of(kind, plain(r[0]))
        cls = ' class="%s"' % g if g else ''
        out.append('<tr>')
        if label:
            out.append('<td class="rowlab%s">%s</td>' % (' ' + g if g else '', inline(r[0])))
        key = keys[ri] if keys else plain(r[0]).split(' \u2014 ')[0].strip()
        for i in order:
            cell = r[i + 1] if i + 1 < len(r) else ''
            ex = EXAMPLES.get((key, i + 1)) if balloons else None
            attrs = cls
            if ex:
                attrs = ' class="%s"' % ' '.join(filter(None, [g, 'hasex']))
                attrs += ' data-el="%s" data-en="%s"' % (html.escape(ex[0], True),
                                                         html.escape(ex[1], True))
            out.append('<td%s>%s</td>' % (attrs, split_cell(cell) or inline(cell)))
        out.append('</tr>')
    out.append('</tbody></table>')
    return ''.join(out)


def make_grid_sheet():
    src = os.path.join(BASE, 'grammar', '02-nouns.md')
    if not os.path.isfile(src):
        print('grid   : skipped - no 02-nouns.md')
        return None
    header, rows = find_master_grid(io.open(src, encoding='utf-8').read())
    if not header:
        print('grid   : skipped - master grid not found')
        return None

    cols = [plain(h).strip() for h in header[1:]]
    cases, nums = [], []
    for c in cols:
        case, num = c.rsplit(' ', 1) if ' ' in c else (c, '')
        cases.append(case)
        nums.append(num)
    order = by_case_order(cases)

    legend = ('<div class="legend"><span class="m">masculine</span>'
              '<span class="f">feminine</span><span class="n">neuter</span></div>')
    notes = (
        '<div class="notes">'
        '<b>Each cell:</b> the definite article, the indefinite one under it, '
        'and the ending on the right. &nbsp; '
        '<b>No indefinite article in the plural</b> &mdash; Greek drops it: '
        '<i>&#914;&#955;&#941;&#960;&#969; &#960;&#945;&#953;&#948;&#953;&#940;.</i> &nbsp; '
        '<b>&#964;&#959;&#957; / &#964;&#951;&#957;</b> lose the <b>-&#957;</b> before some '
        'consonants, but masculine <b>&#964;&#959;&#957;</b> is kept in writing: it is what '
        'separates <i>&#964;&#959;&#957; &#948;&#961;&#972;&#956;&#959;</i> from '
        '<i>&#964;&#959; &#948;&#961;&#972;&#956;&#959;</i>. &nbsp; '
        '<b>Vocative</b> is not here &mdash; it is only for calling someone.'
        '</div>')

    doc = ('<!doctype html><html lang="el"><head><meta charset="utf-8">'
           '<title>Greek A2 - noun endings, master grid</title>%s'
           '<style>%s</style></head><body>'
           '<h1>Greek A2 &middot; Noun endings &mdash; master grid</h1>'
           '<p class="sub">Article and ending for every A2 declension, grouped by case.</p>'
           '%s%s%s</body></html>'
           % (FAVICON, GRID_SHEET_CSS, legend,
              render_print_grid(header, rows, order,
                                [cases[i] for i in order], [nums[i] for i in order]),
              notes))
    out_html = os.path.join(DIST, 'master-grid.html')
    io.open(out_html, 'w', encoding='utf-8', newline='\n').write(doc)

    if '--no-pdf' in sys.argv:
        print('grid   : %s  (pdf skipped - --no-pdf)' % out_html)
        return out_html
    exe = next((p for p in CHROME_CANDIDATES if os.path.isfile(p)), None)
    if not exe:
        print('grid   : %s  (pdf skipped - no Chrome)' % out_html)
        return out_html
    out_pdf = os.path.join(DIST, 'master-grid.pdf')
    cmd = [exe, '--headless=new', '--disable-gpu', '--no-first-run',
           '--no-default-browser-check', '--no-pdf-header-footer',
           '--print-to-pdf=' + out_pdf,
           'file:///' + out_html.replace(os.sep, '/')]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=120, check=False)
    except Exception as e:
        print('grid   : pdf failed (%s)' % e)
        return out_html
    if os.path.isfile(out_pdf):
        print('grid   : %s  (%.0f KB)' % (out_pdf, os.path.getsize(out_pdf) / 1024.0))
    return out_pdf

# ------------------------------------------------- the other two master grids
# adjective-grid.html and verb-grid.html: the same treatment the noun grid gets,
# for the two paradigm sets that are just as big. HTML only - these are wider
# and longer than one A4 page, so there is no print sibling to keep on one page.
EXTRA_GRID_CSS = """
h2{font-size:12.5pt; margin:6mm 0 2mm; letter-spacing:-.01em}
h2:first-of-type{margin-top:0}
table{font-size:10.8pt; margin:0 0 2mm}
th,td{padding:3.4pt 5pt}
td:first-child,th:first-child{width:19%; font-size:10pt}
thead th{font-size:10.5pt}
thead th.m{background:var(--m-bg); color:var(--m-fg)}
thead th.f{background:var(--f-bg); color:var(--f-fg)}
thead th.n{background:var(--n-bg); color:var(--n-fg)}
.glance td:first-child{width:38%}
/* the row label the noun grid does without */
th.rowlab{text-align:left}
td.rowlab{font-size:9.8pt; line-height:1.3}
/* hover balloons: same markup as the sheets, with the palette spelled out
   because this page does not load the main stylesheet's custom properties */
:root{--line:var(--rule); --head:var(--band); --fg:var(--ink); --muted:var(--sub)}
td.hasex{position:relative; cursor:help}
td.hasex::after{content:""; position:absolute; top:3px; right:3px; width:4px; height:4px;
  border-radius:50%; background:currentColor; opacity:.32}
td.hasex:hover::after{opacity:.75}
.extip{position:absolute; z-index:80; max-width:300px; padding:9px 12px;
  border:1px solid var(--line); border-radius:9px; background:var(--head); color:var(--fg);
  box-shadow:0 8px 22px rgba(0,0,0,.28); font-size:12px; line-height:1.45; pointer-events:none}
.extip .el{font-weight:600}
.extip .en{margin-top:3px; color:var(--muted); font-size:11px}
.extip::after{content:""; position:absolute; left:50%; margin-left:-6px; bottom:-6px;
  width:11px; height:11px; background:var(--head);
  border-right:1px solid var(--line); border-bottom:1px solid var(--line);
  transform:rotate(45deg)}
.extip.below::after{bottom:auto; top:-6px; transform:rotate(225deg)}
@media print{td.hasex::after{display:none} .extip{display:none}}
"""


def find_table_after(md, marker, skip=0):
    """The (skip+1)-th markdown table starting after the line holding `marker`."""
    lines = md.replace('\r\n', '\n').split('\n')
    start = next((i for i, l in enumerate(lines) if marker in l), None)
    if start is None:
        return None, None
    found, i = 0, start + 1
    while i < len(lines):
        if is_row(lines[i]) and i + 1 < len(lines) and SEP.match(lines[i + 1]):
            header = split_row(lines[i])
            rows, j = [], i + 2
            while j < len(lines) and is_row(lines[j]):
                rows.append(split_row(lines[j]))
                j += 1
            if found == skip:
                return header, rows
            found, i = found + 1, j
            continue
        i += 1
    return None, None


def render_band_grid(inner, rows, band=None, col_g=None, cls=''):
    """One table: `inner` are the column labels (column 0 labels the row), `band`
    an optional row of outer labels above them (equal neighbours merge), `col_g`
    the gender colour per column."""
    out = ['<table%s><thead>' % (' class="%s"' % cls if cls else '')]
    if band:
        groups = []
        for l in band:
            if groups and groups[-1][0] == l:
                groups[-1][1] += 1
            else:
                groups.append([l, 1])
        out.append('<tr>%s</tr>' % ''.join(
            '<th colspan="%d" class="grp">%s</th>' % (n, html.escape(l))
            for l, n in groups))
    out.append('<tr>%s</tr>' % ''.join(
        '<th%s>%s</th>' % (' class="%s"' % col_g[i] if col_g and col_g[i] else '', inline(l))
        for i, l in enumerate(inner)))
    out.append('</thead><tbody>')
    for r in rows:
        out.append('<tr>')
        for i in range(len(inner)):
            g = col_g[i] if col_g else None
            out.append('<td%s>%s</td>'
                       % (' class="%s"' % g if g else '', inline(r[i] if i < len(r) else '')))
        out.append('</tr>')
    out.append('</tbody></table>')
    return ''.join(out)


def split_number_header(header):
    """'Masculine singular' -> label 'Masculine' under a 'Singular' band."""
    inner, band, col_g = [], [], []
    for h in header:
        p = plain(h).strip()
        g = gender_of(p)
        if g and ' ' in p:
            base, num = p.rsplit(' ', 1)
            inner.append(base)
            band.append(num[:1].upper() + num[1:])
        else:
            inner.append(p)
            band.append('')
        col_g.append(g)
    return inner, band, col_g


def grid_page(title, sub, blocks, legend='', notes='', scripts=''):
    return ('<!doctype html><html lang="el"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title>%s<style>%s%s</style></head><body>'
            '<h1>%s</h1><p class="sub">%s</p>%s%s%s%s</body></html>'
            % (html.escape(re.sub(r'&\w+;|&#\d+;', '', title)), FAVICON,
               GRID_SHEET_CSS, EXTRA_GRID_CSS, title, sub, legend, blocks, notes, scripts))


LEGEND = ('<div class="legend"><span class="m">masculine</span>'
          '<span class="f">feminine</span><span class="n">neuter</span></div>')


def make_adjective_grid():
    """adjective-grid.html: the same grid as the noun one, grouped by case, with
    the row-label column kept and an example balloon on every cell."""
    src = os.path.join(BASE, 'grammar', '05-adjectives.md')
    if not os.path.isfile(src):
        print('adj    : skipped - no 05-adjectives.md')
        return None
    md = io.open(src, encoding='utf-8').read()
    header, rows = find_master_grid(md, 'adj')
    if not header:
        print('adj    : skipped - master grid not found')
        return None
    glance_h, glance_r = find_table_after(md, 'What the grid shows at a glance')

    cols = [plain(h).strip() for h in header[1:]]
    cases, nums = [], []
    for c in cols:
        case, num = c.rsplit(' ', 1) if ' ' in c else (c, '')
        cases.append(case)
        nums.append(num)
    order = by_case_order(cases)

    blocks = render_print_grid(header, rows, order,
                               [cases[i] for i in order], [nums[i] for i in order],
                               label=plain(header[0]).strip(), balloons=True)
    if glance_h:
        blocks += ('<h2>What the grid shows at a glance</h2>'
                   + render_band_grid([plain(h) for h in glance_h], glance_r, cls='glance'))
    notes = ('<div class="notes">'
             '<b>Hover or tap any cell</b> for a sentence that uses that exact form. &nbsp; '
             '<b>The accent shown is the row word\u2019s</b>, not the type\u2019s: '
             '&#954;&#945;&#955;&#972;&#962; is end-stressed, '
             '&#972;&#956;&#959;&#961;&#966;&#959;&#962; is not, and adjective stress '
             'never moves. &nbsp; '
             '<b>The two top rows are identical, and so are the two top neuter '
             'rows</b> &mdash; A and B differ only in the feminine. &nbsp; '
             '<b>Genitive plural is -&#969;&#957; / -&#974;&#957;</b> in all three genders, '
             'every type. &nbsp; '
             '<b>&#956;&#960;&#955;&#949;, &#947;&#954;&#961;&#953;, &#954;&#945;&#966;&#941;, '
             '&#961;&#959;&#950;, &#960;&#959;&#961;&#964;&#959;&#954;&#945;&#955;&#943;, '
             '&#956;&#969;&#946;</b> never agree with anything.'
             '</div>')
    doc = grid_page('Greek A2 &middot; Adjective endings &mdash; master grid',
                    'Every A2 adjective type and gender, all three cases, both numbers.',
                    blocks, LEGEND, notes, EX_JS)
    out = os.path.join(DIST, 'adjective-grid.html')
    io.open(out, 'w', encoding='utf-8', newline='\n').write(doc)
    print('adj    : %s  (%.1f KB)' % (out, os.path.getsize(out) / 1024.0))
    return out


PERSON_LEGEND = (
    '<div class="legend people"><b>\u03b5\u03b3\u03ce</b> 1 sg &middot; '
    '<b>\u03b5\u03c3\u03cd</b> 2 sg &middot; '
    '<b>\u03b1\u03c5\u03c4\u03cc\u03c2 / \u03b1\u03c5\u03c4\u03ae / '
    '\u03b1\u03c5\u03c4\u03cc</b> 3 sg &middot; '
    '<b>\u03b5\u03bc\u03b5\u03af\u03c2</b> 1 pl &middot; '
    '<b>\u03b5\u03c3\u03b5\u03af\u03c2</b> 2 pl &middot; '
    '<b>\u03b1\u03c5\u03c4\u03bf\u03af / \u03b1\u03c5\u03c4\u03ad\u03c2 / '
    '\u03b1\u03c5\u03c4\u03ac</b> 3 pl</div>')

TENSE_LEGEND = ('<div class="legend"><span class="pr">present</span>'
                '<span class="pa">past</span><span class="fu">future &amp; \u03bd\u03b1</span>'
                '</div>')


def case_order_of(header):
    """(order, outer labels, inner labels) for a '<group> <number>' header."""
    cols = [plain(h).strip() for h in header[1:]]
    outer, inner = [], []
    for c in cols:
        a, b = c.rsplit(' ', 1) if ' ' in c else (c, '')
        outer.append(a)
        inner.append(b)
    order = by_case_order(outer)
    return order, [outer[i] for i in order], [inner[i] for i in order]


def make_verb_grid():
    """verb-grid.html: tense x group down the side, person x number across."""
    src = os.path.join(BASE, 'grammar', '08-verbs-present.md')
    if not os.path.isfile(src):
        print('verb   : skipped - no 08-verbs-present.md')
        return None
    md = io.open(src, encoding='utf-8').read()
    sections = [('Active voice', '### Active voice'),
                ('Passive / mediopassive voice', '### Passive / mediopassive voice'),
                ('\u03b5\u03af\u03bc\u03b1\u03b9 and \u03ad\u03c7\u03c9 '
                 '&mdash; the two with no dependent stem',
                 '### \u03b5\u03af\u03bc\u03b1\u03b9 and \u03ad\u03c7\u03c9')]
    blocks = []
    for heading, marker in sections:
        header, rows = find_table_after(md, marker)
        if not header or grid_kind(header) != 'verb':
            print('verb   : skipped - %s is not a verb grid' % marker)
            return None
        order, outer, inner = case_order_of(header)
        notes = column_notes(header)
        blocks.append('<h2>%s</h2>%s'
                      % (heading,
                         render_print_grid(header, rows, order, outer, inner,
                                           label=plain(header[0]).strip(),
                                           balloons=True, kind='verb',
                                           ann=[notes[i] for i in order]
                                           if notes else None)))
    glance_h, glance_r = find_table_after(md, 'What the grid shows at a glance')
    if glance_h:
        blocks.append('<h2>What the grid shows at a glance</h2>'
                      + render_band_grid([plain(h) for h in glance_h], glance_r, cls='glance'))
    notes = ('<div class="notes">'
             '<b>Hover or tap any cell</b> for a sentence that uses that exact form. &nbsp; '
             '<b>The stem is in the row label</b>, the ending is in the cell, and '
             '<b>\u03b8\u03b1 / \u03bd\u03b1 / \u03ad\u03c7\u03c9</b> are printed because '
             'they are separate words. &nbsp; '
             '<b>The whole rose band shares one set of endings</b> and so does the whole cyan '
             'band &mdash; two sets to learn, and everything else is stems. &nbsp; '
             '<b>Never an \u03ad- augment after \u03b8\u03b1 or \u03bd\u03b1.</b>'
             '</div>')
    doc = grid_page('Greek A2 &middot; Verb endings &mdash; master grid',
                    'Present, past and future &mdash; every A2 group, '
                    'all six persons, both voices.',
                    ''.join(blocks), TENSE_LEGEND, notes, EX_JS)
    out = os.path.join(DIST, 'verb-grid.html')
    io.open(out, 'w', encoding='utf-8', newline='\n').write(doc)
    print('verb   : %s  (%.1f KB)' % (out, os.path.getsize(out) / 1024.0))
    return out


def make_mega_grid():
    """mega-grid.html: the noun rows and the adjective rows in one table, both
    ordered by gender, so a whole phrase can be read off one colour band - the
    article and the noun ending from a NOUN row, the adjective ending from an
    ADJ row of the same colour."""
    nsrc = os.path.join(BASE, 'grammar', '02-nouns.md')
    asrc = os.path.join(BASE, 'grammar', '05-adjectives.md')
    if not (os.path.isfile(nsrc) and os.path.isfile(asrc)):
        print('mega   : skipped - sources missing')
        return None
    nh, nrows = find_master_grid(io.open(nsrc, encoding='utf-8').read(), 'noun')
    ah, arows = find_master_grid(io.open(asrc, encoding='utf-8').read(), 'adj')
    if not nh or not ah:
        print('mega   : skipped - a master grid is missing')
        return None

    # relabelling the rows would break the band and the example lookup, both of
    # which read the label, so collect all three explicitly
    merged, keys, bands = [], [], []

    def take(rows, tag, want):
        for r in rows:
            g = gender_of(plain(r[0]))
            if g != want:
                continue
            merged.append(['**%s** %s' % (tag, r[0])] + list(r[1:]))
            keys.append(plain(r[0]).split(' \u2014 ')[0].strip())
            bands.append(g)

    for g in ('m', 'f', 'n'):
        take(nrows, 'NOUN', g)
        take(arows, 'ADJ', g)
    take(arows, 'ADJ', None)                    # the invariable colours

    order, outer, inner = case_order_of(nh)
    grid = render_print_grid(nh, merged, order, outer, inner,
                             label='Noun type / adjective type', balloons=True,
                             keys=keys, bands=bands)
    notes = (
        '<div class="notes">'
        '<b>How to read it:</b> pick the gender band, take the article and the noun ending '
        'from a <b>NOUN</b> row and the adjective ending from an <b>ADJ</b> row of the same '
        'colour &mdash; '
        '<i>\u03c4\u03bf\u03c5 \u03ba\u03b1\u03bb\u03bf\u03cd '
        '\u03c6\u03af\u03bb\u03bf\u03c5</i>, '
        '<i>\u03c4\u03b9\u03c2 \u03ba\u03b1\u03bb\u03ad\u03c2 '
        '\u03ce\u03c1\u03b5\u03c2</i>, '
        '<i>\u03c4\u03c9\u03bd \u03ba\u03b1\u03bb\u03ce\u03bd '
        '\u03c0\u03b1\u03b9\u03b4\u03b9\u03ce\u03bd</i>. &nbsp; '
        '<b>Only the noun rows carry an article</b> &mdash; the adjective borrows the '
        'noun\u2019s. &nbsp; '
        '<b>Hover or tap any cell</b> for a sentence using that exact form. &nbsp; '
        '<b>The two endings rarely match.</b> \u03c4\u03bf\u03c5 \u03ba\u03b1\u03bb'
        '\u03bf\u03cd \u03c6\u03af\u03bb\u03bf\u03c5 happens to rhyme; '
        '\u03c4\u03b7\u03c2 \u03ba\u03b1\u03bb\u03ae\u03c2 '
        '\u03ce\u03c1\u03b1\u03c2 does not. What has to agree is gender, case and '
        'number &mdash; never the letters.'
        '</div>')
    doc = grid_page('Greek A2 &middot; Nouns and adjectives &mdash; one grid',
                    'Every declension and every adjective type, side by side, '
                    'banded by gender.',
                    grid, LEGEND, notes, EX_JS)
    out = os.path.join(DIST, 'mega-grid.html')
    io.open(out, 'w', encoding='utf-8', newline='\n').write(doc)
    print('mega   : %s  (%.1f KB, %d rows)'
          % (out, os.path.getsize(out) / 1024.0, len(merged)))
    return out


if __name__ == '__main__':
    main()
