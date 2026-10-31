# -*- coding: utf-8 -*-
"""Lead logo for a deck: checked and fixed instead of taken as found. ONE shared tool, identical copy in every deck repo
(_src/tools/logo.py of Vistamails, Symonds Productions, Craze & Friends, Flytxt, 3DforScience, ConvertPolo).
Edit it in one place and copy it to the others (Presentations/README.md "Lead logos").

Usage: py logo.py <slug> "<Company>" <url> --bg <#hex> --out <dir> [--name <file.png>] [--preview <dir>]
                  [--spec <file> --key logo --value <v> --badge-key logo_badge --on-none remove|text] [--keep] [--json]

Why: every earlier deck pipeline took the first header image that loaded. That gave black wordmarks that vanish on a dark
slide, white ones that vanish on a white slide, square favicons stretched into the wordmark slot, logos inside an opaque
box, product photos, and tiny blurred PNGs. This tool loads the site in a real browser, collects every visible header
candidate (img, inline svg incl. sprite <use>, css background, touch icon) plus the logo already in the repo, renders each
one alone on a transparent page (rasters never upscaled, CDN thumbnails asked for at full size), strips boxes, trims,
drops icons / photos / tiny rasters, picks the best wordmark and makes it read on the deck background:
  dark deck   one-colour logo -> pure white; dark multi-colour -> white badge (logo_badge); bright multi-colour -> kept
  light deck  one-colour logo -> ink #131410; light multi-colour -> ink; dark/colourful -> kept
Writes <out>/<name> (png, height <= 400), a preview on the deck background in <preview>/<slug>.png and, with --spec, sets
<key> = <value> (default the file name) and <badge-key> (dark decks only). Nothing usable: --on-none remove drops the key
(the template shows the company name in text), --on-none text writes a wordmark png of the company name instead.
Prints "RESULT ..." and, with --json, a final JSON line {"file","badge","ok","text"} for pipelines.
--keep: only the existing <out>/<slug>.(png|svg) (or --name) is normalised, nothing is fetched.
"""
import sys, os, re, json, io, math

from PIL import Image, ImageDraw, ImageFont

try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
H = 400
INK = (19, 20, 16)
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
FONTS = [r'C:\Windows\Fonts\arialbd.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
         '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']

COLLECT = r"""(company)=>{const o={imgs:[],svgs:[],bgs:[],icons:[]};
const Q='header, nav, [role=banner], a[href="/"], [class*=logo i], [id*=logo i], [class*=brand i], [class*=navbar i], [class*=header i]';
const seen=new Set(); const home=location.origin+'/'; const co=(company||'').toLowerCase().split(' ')[0];
const vis=el=>{const r=el.getBoundingClientRect();if(r.width<20||r.height<6||r.top>260||r.bottom<0)return null;const s=getComputedStyle(el);if(s.visibility==='hidden'||s.display==='none'||+s.opacity===0)return null;for(let p=el;p;p=p.parentElement){const ps=getComputedStyle(p);if(ps.display==='none'||ps.visibility==='hidden')return null;}return r;};
const prio=(el,txt)=>{let p=0;if(el.closest('a[href="/"],a[href="'+home+'"],a[href="'+location.origin+'"]'))p+=3;if(/logo|brand|wordmark/i.test(txt))p+=2;if(co&&txt.toLowerCase().includes(co))p+=1;if(el.closest('header,[role=banner]'))p+=1;return p;};
for(const root of document.querySelectorAll(Q)){
  for(const i of root.querySelectorAll('img')){const u=i.currentSrc||i.src;if(!u||seen.has(u))continue;const r=vis(i);if(!r)continue;seen.add(u);o.imgs.push({src:u,w:r.width,h:r.height,nw:i.naturalWidth,nh:i.naturalHeight,alt:i.alt||'',top:r.top,prio:prio(i,(i.alt||'')+' '+i.className+' '+i.id+' '+u)});}
  for(const s of root.querySelectorAll('svg')){const r=vis(s);if(!r)continue;let h=s.outerHTML;if(seen.has(h))continue;seen.add(h);const defs=[];const ext=[];for(const u of s.querySelectorAll('use')){const id=(u.getAttribute('href')||u.getAttribute('xlink:href')||'');if(id.startsWith('#')){const d=document.getElementById(id.slice(1));if(d)defs.push(d.outerHTML);}else if(id.includes('#')){ext.push(new URL(id,location.href).href);}}if(defs.length)h+='<svg style="display:none">'+defs.join('')+'</svg>';const cs=getComputedStyle(s);o.svgs.push({ext:ext,html:h.slice(0,120000),w:r.width,h:r.height,color:cs.color,fill:cs.fill,top:r.top,alt:s.getAttribute('aria-label')||(s.querySelector('title')||{}).textContent||'',prio:prio(s,(s.getAttribute('class')||'')+' '+s.id+' '+(s.getAttribute('aria-label')||'')+' '+((s.querySelector('title')||{}).textContent||''))});}
  for(const el of [root,...root.querySelectorAll('*')]){try{const r=vis(el);if(!r||r.width>900)continue;const bg=getComputedStyle(el).backgroundImage||'';const m=bg.match(/url\(["']?([^"')]+)["']?\)/);if(m&&!seen.has(m[1])){seen.add(m[1]);o.bgs.push({src:m[1],w:r.width,h:r.height,top:r.top,alt:'',prio:prio(el,el.className+' '+el.id+' '+m[1])});}}catch(e){}}
}
for(const l of document.querySelectorAll('link[rel*="icon" i]')){if(l.href)o.icons.push(l.href);}
return o;}"""
ACCEPT = ["#onetrust-accept-btn-handler", "#CybotCybotBotDialogBodyLevelButtonLevelOptinAllowAll", "#CybotCookiebotDialogBodyButtonAccept",
          r"text=/^\s*(accept|accept all|accept all cookies|allow all|i agree|got it|alle akzeptieren|akzeptieren|aceptar|accepter|tout accepter)\s*$/i"]


def fetch_candidates(url, company, local_files):
    """-> [(kind, image, src, alt, prio)] from the live site plus the local files already in the repo (kind 'local')"""
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--disable-blink-features=AutomationControlled'])
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, user_agent=UA)
        rp = ctx.new_page()
        for f in local_files:
            im = load_local(rp, f)
            if im is not None: out.append(('local', im, os.path.basename(f), company, 0))
        if not url:
            b.close(); return out
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until='networkidle', timeout=45000)
        except Exception:
            try: pg.goto(url, wait_until='domcontentloaded', timeout=45000)
            except Exception as e: print('page failed', str(e)[:80]); b.close(); return out
        pg.wait_for_timeout(2500)
        for n in range(8):                           # cloudflare "Just a moment" challenge: give it time to pass
            if not re.search(r'just a moment|attention required|checking your browser|verify you are human', pg.title(), re.I): break
            pg.wait_for_timeout(2000)
        for s in ACCEPT:
            try: pg.locator(s).first.click(timeout=800); pg.wait_for_timeout(500); break
            except Exception: pass
        c = {'imgs': [], 'svgs': [], 'bgs': [], 'icons': []}
        for n in range(4):                           # a site that redirects to its locale kills the first context
            try: c = pg.evaluate(COLLECT, company); break
            except Exception as e:
                print('collect retry', n, str(e)[:60])
                try: pg.wait_for_load_state('networkidle', timeout=15000)
                except Exception: pass
                pg.wait_for_timeout(1500)
        srcs = [('img', i['src'], i) for i in c['imgs']] + [('svg', s['html'], s) for s in c['svgs']] + [('img', g['src'], g) for g in c['bgs']]
        srcs.sort(key=lambda x: (-x[2].get('prio', 0), x[2].get('top', 0)))
        srcs = srcs[:10] + [('icon', u, {'prio': 0}) for u in c['icons'][:2]]
        print(f"candidates: {len(c['imgs'])} img, {len(c['svgs'])} svg, {len(c['bgs'])} css, {len(c['icons'])} icon")
        sprites = {}
        for kind, src, meta in srcs:
            if kind != 'svg' or not meta.get('ext'): continue
            for ref in meta['ext']:
                u, _, sid = ref.partition('#')
                if u not in sprites:
                    try: sprites[u] = ctx.request.get(u, timeout=15000).text()
                    except Exception: sprites[u] = ''
                m = re.search(r'<symbol[^>]*[\s]id="' + re.escape(sid) + r'"[\s\S]*?</symbol>', sprites[u]) or re.search(r'<svg[\s\S]*', sprites[u]) if sprites[u] else None
                if m:
                    sym = m.group(0)
                    if sym.startswith('<svg'):           # a whole file, not a sprite: make it the symbol
                        sym = re.sub(r'^<svg', f'<symbol id="{sid}"', sym).replace('</svg>', '</symbol>')
                    src = src.replace(ref, '#' + sid).replace(ref.split('/')[-1] if ref.startswith('http') else ref, '#' + sid)
                    src = re.sub(r'(href=")[^"#]*#' + re.escape(sid) + '"', lambda mm: mm.group(1) + '#' + sid + '"', src)
                    src += '<svg style="display:none">' + sym + '</svg>'
            meta['html'] = src
        srcs = [(k, m.get('html', s) if k == 'svg' else s, m) for k, s, m in srcs]
        for kind, src, meta in srcs:
            if kind != 'svg':
                if re.search(r'\.(jpe?g)(\?|$)', src, re.I) and 'logo' not in src.lower() and meta.get('prio', 0) < 3: print('  skip photo', src[:70]); continue
                big = fullsize(src)
                if big != src:
                    nh0 = meta.get('nh', 0); meta['nh'] = 9999; png = render(rp, kind, big, meta)
                    if png is not None: meta['nh'] = png.height; src = big
                    else: meta['nh'] = nh0
            png = render(rp, kind, src, meta)
            if png is None: print('  render failed', kind, (meta.get('alt') or src)[:70]); continue
            if meta.get('w', 999) < 60 or meta.get('h', 999) < 14: meta['prio'] = meta.get('prio', 0) - 6   # a 32px flag or dot on the page
            out.append((kind, png, src if kind != 'svg' else 'inline svg ' + meta.get('alt', ''), meta.get('alt', ''), meta.get('prio', 0)))
        b.close()
    return out


def load_local(pg, path):
    try:
        if path.lower().endswith('.svg'):
            return render(pg, 'svg', open(path, encoding='utf-8', errors='replace').read(), {'color': '#000'})
        return Image.open(path).convert('RGBA')
    except Exception as e:
        print('  local unreadable', os.path.basename(path), str(e)[:60]); return None


def fullsize(u):
    """the header serves a thumbnail; ask the CDN for the big one (Shopify width=, _WxH suffix, imgix/cloudinary w=)"""
    u = re.sub(r'([?&])width=\d+', r'\g<1>width=1600', u)
    u = re.sub(r'([?&])w=\d+', r'\g<1>w=1600', u)
    u = re.sub(r'_(\d{2,4})x(\d{2,4})?(_crop_\w+)?(\.(png|webp|gif|svg|jpe?g))', r'\4', u) if '/cdn/shop/' in u else u
    return u


def render(pg, kind, src, meta):
    """draw one candidate alone on a transparent page at a fixed height and screenshot it (works for svg, webp, data uris, currentColor)"""
    try:
        if kind == 'svg':
            col = meta.get('color') or '#000'
            fill = meta.get('fill') or ''
            style = f'color:{col};' + (f'fill:{fill};' if fill and fill not in ('none', 'rgb(0, 0, 0)') else '')
            body = f'<div id="t" style="display:inline-block;{style}">{src}</div>'
            css = '#t svg{height:400px;width:auto;display:block}'
        else:
            body = f'<base href="{meta.get("base", "")}"><img id="t" src="{src}" style="width:auto;display:block">'
            css = ''
        pg.set_content(f'<html><body style="margin:0;background:transparent"><style>{css}</style>{body}</body></html>', wait_until='load')
        pg.wait_for_timeout(600)
        if kind != 'svg':
            nat = pg.evaluate("()=>{const i=document.getElementById('t');return i.complete&&i.naturalWidth>0?i.naturalHeight:0}")
            if not nat: return None
            hh = 400 if (src.lower().split('?')[0].endswith('.svg') or nat >= 400) else nat     # never upscale a raster
            pg.evaluate(f"()=>{{document.getElementById('t').style.height='{hh}px'}}")
            pg.wait_for_timeout(100)
        buf = pg.locator('#t').screenshot(omit_background=True, timeout=8000)
        return Image.open(io.BytesIO(buf)).convert('RGBA')
    except Exception:
        return None


def strip_box(im):
    """an opaque image (no alpha at all) usually sits in a white or coloured box: make the box colour transparent"""
    a = im.getchannel('A'); hist = a.histogram()
    if sum(hist[250:]) / (im.width * im.height) < 0.97: return im     # real transparency (a subpixel edge from the screenshot does not count)
    px = im.load(); w, h = im.size
    border = [px[x, y][:3] for x in range(0, w, max(1, w // 40)) for y in (0, h - 1)] + [px[x, y][:3] for y in range(0, h, max(1, h // 40)) for x in (0, w - 1)]
    mean = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))          # median: the logo may touch an edge
    near = sum(1 for c in border if max(abs(c[i] - mean[i]) for i in range(3)) < 30) / len(border)
    if near < 0.6: return im                        # photo or gradient, not a flat box
    out = im.copy(); po = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, _ = po[x, y]
            if max(abs(r - mean[0]), abs(g - mean[1]), abs(b - mean[2])) < 40: po[x, y] = (r, g, b, 0)
    return out


def trim(im):
    bb = im.getchannel('A').point(lambda v: 255 if v > 24 else 0).getbbox()
    return im.crop(bb) if bb else None


def analyse(im):
    """opaque pixels: coverage, luminance stats, number of distinct significant colours"""
    im = im.convert('RGBA'); px = list(im.get_flattened_data()) if hasattr(im, 'get_flattened_data') else list(im.getdata()); n = len(px)
    op = [p for p in px if p[3] > 128]
    if not op: return None
    lum = [(0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]) / 255 for p in op]
    buckets = {}
    for p in op:
        k = (p[0] // 48, p[1] // 48, p[2] // 48); buckets[k] = buckets.get(k, 0) + 1
    sig = sorted(((c / len(op), k) for k, c in buckets.items()), reverse=True)
    fine = sum(1 for s, k in sig if s > 0.015)
    sig = [(s, k) for s, k in sig if s > 0.06]
    sat = [max(p[:3]) - min(p[:3]) for p in op]
    return {'cover': len(op) / n, 'lum_mean': sum(lum) / len(lum), 'dark_share': sum(1 for l in lum if l < 0.35) / len(lum),
            'light_share': sum(1 for l in lum if l > 0.85) / len(lum), 'colours': len(sig), 'fine': fine, 'sat_mean': sum(sat) / len(sat) / 255}


def score(kind, im, alt, company):
    w, h = im.size; asp = w / h
    st = analyse(im)
    if st is None or w < 60 or h < 16 or st['cover'] < 0.02: return -99, st
    s = math.log(w * h) / 2
    if 1.6 <= asp <= 12: s += 3                       # a wordmark
    elif asp < 1.15: s -= 3                          # an icon
    if asp > 14: s -= 2                              # a whole header strip, not a logo
    if kind == 'icon': s -= 4
    if h < 90: s -= 8                                # a raster this small is pixel mush at deck size
    if company.lower().split()[0] in (alt or '').lower(): s += 1.5
    if st['cover'] < 0.06: s -= 1.5                  # mostly empty: text with huge padding or a thin rule
    if st['colours'] >= 5 or st['fine'] >= 9: s -= 8  # a photo or a product shot, not a logo
    return s, st


def paint(im, rgb):
    px = im.load(); w, h = im.size
    for y in range(h):
        for x in range(w):
            a = px[x, y][3]
            if a: px[x, y] = rgb + (a,)
    return im


def fix_for_dark(im, st):
    """returns (image, badge). one colour: paint white. bright colours: keep. dark parts in a multi-colour logo: white badge."""
    mono = st['colours'] <= 2 and (st['sat_mean'] < 0.12 or st['colours'] == 1)
    if mono or (st['colours'] <= 2 and st['dark_share'] > 0.5):
        return paint(im, (255, 255, 255)), False
    if st['dark_share'] > 0.12:
        if st['light_share'] > 0.12:                 # dark and white parts: a badge would eat the white parts, paint all white
            return paint(im, (255, 255, 255)), False
        return im, True
    return im, False


def fix_for_light(im, st):
    """returns (image, False). one colour: paint ink. light parts that would vanish on white: paint ink. dark or colourful: keep."""
    mono = st['colours'] <= 2 and (st['sat_mean'] < 0.12 or st['colours'] == 1)
    if mono or st['light_share'] > 0.3 or (st['lum_mean'] > 0.6 and st['sat_mean'] < 0.2):
        return paint(im, INK), False
    return im, False


def font(size):
    for fp in FONTS:
        if os.path.exists(fp): return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def wordmark(company, rgb):
    """the company name as a bold wordmark png: the fallback that always reads"""
    fnt = font(300)
    im = Image.new('RGBA', (6000, 420), (0, 0, 0, 0)); ImageDraw.Draw(im).text((20, 20), company, font=fnt, fill=rgb + (255,))
    im = im.crop(im.getbbox())
    if im.height > H: im = im.resize((max(1, round(im.width * H / im.height)), H), Image.LANCZOS)
    return im


def preview(path, bg, company, im, badge):
    W, Hh = 1600, 500
    pv = Image.new('RGBA', (W, Hh), bg + (255,)); d = ImageDraw.Draw(pv)
    y = 80
    if im is not None:
        lg = im.copy(); lg.thumbnail((700, 160), Image.LANCZOS)
        if badge:
            pad = 28; tile = Image.new('RGBA', (lg.width + 2 * pad, lg.height + 2 * pad), (255, 255, 255, 255))
            tile.alpha_composite(lg, (pad, pad)); lg = tile
        pv.alpha_composite(lg, (80, y)); y += lg.height + 40
    grey = (159, 176, 170, 255) if sum(bg) < 384 else (110, 110, 105, 255)
    d.text((80, y), ('logo as it ships' if im is not None else 'no logo: deck shows the name in text') + f'  ·  {company}', font=font(54), fill=grey)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pv.convert('RGB').save(path)


def guard(path, bg, badge=False):
    """build-time check of a logo file -> None when fine, else what is wrong (the build must refuse it). Same rules for every deck."""
    bg = hexrgb(bg) if isinstance(bg, str) else tuple(bg)
    light = (0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]) / 255 > 0.5
    if isinstance(path, Image.Image): im = path
    else:
        if not os.path.exists(path): return 'missing'
        if not path.lower().endswith('.png'): return 'not a png from logo.py'
        im = Image.open(path).convert('RGBA')
    st = analyse(im)
    if st is None: return 'empty'
    if im.height < 90: return f'too small ({im.width}x{im.height}), pixel mush at deck size'
    if im.width / im.height < 1.15: return 'an icon, not a wordmark'
    if light and st['lum_mean'] > 0.75: return 'light on a white slide'
    if not light and st['lum_mean'] < 0.45 and not badge: return 'dark on a dark slide and no badge'
    return None


def hexrgb(s):
    s = s.strip().lstrip('#')
    if len(s) == 3: s = ''.join(c * 2 for c in s)
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def run(slug, company, url, bg, out_dir, name=None, preview_dir=None, keep=False, on_none='remove'):
    """-> {'file': name or None, 'badge': bool, 'ok': bool, 'text': bool}; writes <out_dir>/<name> and the preview"""
    bg = hexrgb(bg) if isinstance(bg, str) else tuple(bg)
    light = (0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]) / 255 > 0.5
    name = name or slug + '.png'
    preview_dir = preview_dir or os.path.join(out_dir, '_preview')
    os.makedirs(out_dir, exist_ok=True)
    if url and not url.startswith('http'): url = 'https://' + url
    stem = os.path.splitext(name)[0]
    locals_ = [os.path.join(out_dir, f) for f in (name, stem + '.svg', stem + '.png', slug + '.png', slug + '.svg')
                                                if os.path.exists(os.path.join(out_dir, f))]
    locals_ = list(dict.fromkeys(locals_))
    cands = fetch_candidates('' if keep else url, company, locals_)
    scored = []
    for kind, im, src, alt, prio in cands:
        im = strip_box(im); im = trim(im)
        if im is None: print(f'  empty  {kind:5} {src[:90]}'); continue
        s, st = score(kind, im, alt, company)
        if s > -99: s += prio
        print(f'  {s:6.2f}  {kind:5} {im.width}x{im.height}  {src[:90]}')
        scored.append((s, im, st, src))
    for f in locals_:
        if os.path.exists(f): os.remove(f)
    res = {'file': None, 'badge': False, 'ok': False, 'text': False}
    best = None
    for s, im, st, src in sorted(scored, key=lambda x: -x[0]):   # best first; the first one the build guard accepts ships
        if s < 3: break
        im, badge = (fix_for_light if light else fix_for_dark)(im.copy(), st)
        if im.height > H: im = im.resize((max(1, round(im.width * H / im.height)), H), Image.LANCZOS)
        bad = guard(im, bg, badge)
        if bad: print(f'  rejected ({bad}): {src[:70]}'); continue
        best = (im, badge, st, src); break
    if best is None:
        if on_none == 'text':
            im = wordmark(company, INK if light else (255, 255, 255)); im.save(os.path.join(out_dir, name))
            res.update(file=name, text=True)
            print(f'RESULT no usable logo, wordmark of the company name written to {name}')
            preview(os.path.join(preview_dir, slug + '.png'), bg, company, im, False)
        else:
            print('RESULT no usable logo, deck shows the company name in text')
            preview(os.path.join(preview_dir, slug + '.png'), bg, company, None, False)
    else:
        im, badge, st, src = best
        im.save(os.path.join(out_dir, name))
        st2 = analyse(im)
        res.update(file=name, badge=badge, ok=True)
        print(f'RESULT {name}  badge={badge}  lum={st2["lum_mean"]:.2f} colours={st["colours"]} from {src[:80]}')
        preview(os.path.join(preview_dir, slug + '.png'), bg, company, im, badge)
    print('preview', os.path.join(preview_dir, slug + '.png'))
    return res


def opt(k, default=None):
    return sys.argv[sys.argv.index(k) + 1] if k in sys.argv else default


def main():
    args = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith('--') and not sys.argv[i - 1].startswith('--')]
    if len(args) < 3 or '--bg' not in sys.argv or '--out' not in sys.argv: print(__doc__); sys.exit(1)
    slug, company, url = args[0], args[1], args[2]
    res = run(slug, company, url, opt('--bg'), opt('--out'), opt('--name'), opt('--preview'), '--keep' in sys.argv, opt('--on-none', 'remove'))
    spec = opt('--spec')
    if spec:
        key, bkey = opt('--key', 'logo'), opt('--badge-key')
        sp = json.load(open(spec, encoding='utf-8'))
        sp.pop(key, None)
        if bkey: sp.pop(bkey, None)
        if res['file']:
            sp[key] = opt('--value', res['file'])
            if bkey and res['badge']: sp[bkey] = True
        json.dump(sp, open(spec, 'w', encoding='utf-8'), indent=1, ensure_ascii=False); print('spec updated', spec)
    if '--json' in sys.argv: print('JSON ' + json.dumps(res))


if __name__ == '__main__':
    main()
