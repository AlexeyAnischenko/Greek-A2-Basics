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

def is_master_grid(header):
    if not header or plain(header[0]).strip() != 'Type':
        return False
    return any(plain(h).strip() == 'Nominative singular' for h in header)

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

def render_table(header, rows, last_gender):
    ncol = len(header)
    col_g = [gender_of(plain(h)) for h in header]
    any_col = any(col_g)

    row_g = []
    if not any_col:
        for r in rows:
            row_g.append(gender_of(plain(r[0])) if r else None)
    any_row = any(row_g)

    grid = is_master_grid(header)

    out = ['<div class="tw"><table>', '<thead><tr>']
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
    out.append('</tbody></table></div>')
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
tbody tr:nth-child(even) td:not(.m):not(.f):not(.n){background:var(--zebra)}
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
  .wrap{flex-direction:column; gap:14px}
  nav.toc{position:static; width:100%; flex:none; max-height:none}
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
  td.m,th.m,td.f,th.f,td.n,th.n{-webkit-print-color-adjust:exact; print-color-adjust:exact}
  tbody tr:nth-child(even) td:not(.m):not(.f):not(.n){background:transparent}
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
@media print{ td.hasex::after{display:none} .extip{display:none} }
/* master-grid cells: the articles stack down the left, the ending is pinned
   right, so prefix and suffix each read as one vertical column */
td .cell2{display:flex;align-items:center;justify-content:space-between;gap:10px}
td .cell2 .arts{display:flex;flex-direction:column;align-items:flex-start;line-height:1.3}
td .cell2 .end{white-space:nowrap;text-align:right}
"""

# ------------------------------------------------------- theme switch pieces
# Runs before first paint so a pinned dark choice does not flash white.
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
           '<title>Greek A2 — Grammar Drill Sheets</title><style>%s</style>%s</head><body>'
           '%s'
           '<header class="top"><h1>Greek A2 — Grammar Drill Sheets</h1>'
           '<p>%d sheets · A2 scope · cover the right column and recite</p>%s</header>'
           '<div class="wrap"><nav class="toc"><h2>Contents</h2><ol>%s</ol></nav>'
           '<main>%s</main></div>%s</body></html>'
           % (CSS, THEME_HEAD, THEME_BTN, len(sheets), legend, toc, body,
              THEME_JS + EX_JS + COPY_JS))

    out_html = os.path.join(DIST, 'index.html')
    io.open(out_html, 'w', encoding='utf-8', newline='\n').write(doc)

    for s in sheets:
        page = ('<!doctype html><html lang="el"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<meta name="color-scheme" content="light dark">'
                '<title>%s</title><style>%s</style>%s</head><body>'
                '%s<div class="wrap"><main><section class="sheet">%s</section></main></div>'
                '%s</body></html>' % (html.escape(s['title']), CSS, THEME_HEAD,
                                      THEME_BTN, s['body'], THEME_JS + EX_JS + COPY_JS))
        stem = os.path.splitext(s['file'])[0]
        if stem == 'index':
            stem = 'index-sheet'      # avoid creating pages/index.html
        io.open(os.path.join(PAGES, stem + '.html'),
                'w', encoding='utf-8', newline='\n').write(page)

    print('html   : %s  (%.1f KB)' % (out_html, os.path.getsize(out_html) / 1024.0))
    print('pages  : %d files in %s' % (len(sheets), PAGES))

    make_pdf(out_html)
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

if __name__ == '__main__':
    main()
