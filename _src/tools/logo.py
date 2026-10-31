# -*- coding: utf-8 -*-
"""Lead logo for the dark VistaMails deck, checked and fixed instead of taken as found.

Usage: py logo.py <slug> "<Company>" <url> [--spec specs/<slug>.json] [--keep]

Why: every earlier deck pipeline took the first header image that loaded. On a near-black slide that gave
black wordmarks that vanish, square favicons stretched into the wordmark slot, logos inside an opaque white box,
and tiny blurred PNGs. This tool renders every candidate (img, inline svg, css background, touch icon) in an
isolated transparent page, trims it, drops icons and junk, picks the best wordmark and then makes sure it reads
on #041010: a one-colour logo is painted pure white, a multi-colour logo with dark parts goes on a white badge,
a bright multi-colour logo stays. Writes assets/leadlogos/<slug>.png, a preview on the deck background in
assets/leadlogos/_preview/<slug>.png, and with --spec sets "logo" / "logo_badge" in the spec (or removes "logo"
when nothing usable was found: the deck then shows the company name in text, which is always readable).
--keep: an existing assets/leadlogos/<slug>.(png|svg) is only normalised, nothing is fetched.
"""
import sys, os, re, json, io, math, base64
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.dirname(HERE); ROOT = os.path.dirname(SRC)
LOGOS = os.path.join(ROOT, 'assets', 'leadlogos'); PREV = os.path.join(LOGOS, '_preview')
os.makedirs(PREV, exist_ok=True)
BG = (4, 16, 16); H = 400                      # deck --paper and the output height
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'

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


def fetch_candidates(url, company):
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--disable-blink-features=AutomationControlled'])
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, user_agent=UA)
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until='networkidle', timeout=45000)
        except Exception:
            try: pg.goto(url, wait_until='domcontentloaded', timeout=45000)
            except Exception as e: print('page failed', e); b.close(); return []
        pg.wait_for_timeout(2500)
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
        # sources, ordered: header imgs and svgs by position on the page (top left first), css backgrounds, touch icons last
        srcs = [('img', i['src'], i) for i in c['imgs']] + [('svg', s['html'], s) for s in c['svgs']] + [('img', g['src'], g) for g in c['bgs']]
        srcs.sort(key=lambda x: (-x[2].get('prio', 0), x[2].get('top', 0)))
        srcs = srcs[:10] + [('icon', u, {'prio': 0}) for u in c['icons'][:2]]
        print(f"candidates: {len(c['imgs'])} img, {len(c['svgs'])} svg, {len(c['bgs'])} css, {len(c['icons'])} icon")
        rp = ctx.new_page(); sprites = {}
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
                    meta['nh'] = 9999; png = render(rp, kind, big, meta)
                    if png is not None: meta['nh'] = png.height; src = big
                    else: meta['nh'] = meta.get('nh', 0) if meta.get('nh', 0) != 9999 else 0
            png = render(rp, kind, src, meta)
            if png is None: print('  render failed', kind, (meta.get('alt') or src)[:70]); continue
            if meta.get('w', 999) < 60 or meta.get('h', 999) < 14: meta['prio'] = meta.get('prio', 0) - 6   # a 32px flag or dot on the page
            if png is not None: out.append((kind, png, src if kind != 'svg' else 'inline svg ' + meta.get('alt', ''), meta.get('alt', ''), meta.get('prio', 0)))
        b.close()
    return out


def fullsize(u):
    """the header serves a thumbnail; ask the CDN for the big one (Shopify width=, _WxH suffix, imgix/cloudinary w=)"""
    u = re.sub(r'([?&])width=\d+', r'\g<1>width=1600', u)
    u = re.sub(r'([?&])w=\d+', r'\g<1>w=1600', u)
    u = re.sub(r'_(\d{2,4})x(\d{2,4})?(_crop_\w+)?(\.(png|webp|gif|svg))', r'', u) if '/cdn/shop/' in u else u
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
            hh = 400 if (src.lower().split('?')[0].endswith('.svg') or meta.get('nh', 0) >= 400) else max(meta.get('nh', 0), 1)   # never upscale a raster
            body = f'<base href="{meta.get("base", "")}"><img id="t" src="{src}" style="height:{hh}px;width:auto;display:block">'
            css = ''
        pg.set_content(f'<html><body style="margin:0;background:transparent"><style>{css}</style>{body}</body></html>', wait_until='load')
        pg.wait_for_timeout(600)
        if kind != 'svg':
            ok = pg.evaluate("()=>{const i=document.getElementById('t');return i.complete&&i.naturalWidth>0}")
            if not ok: return None
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
    im = im.convert('RGBA'); px = list(im.getdata()); n = len(px)
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


def fix_for_dark(im, st):
    """returns (image, badge). one colour: paint white. bright colours: keep. dark parts in a multi-colour logo: white badge."""
    mono = st['colours'] <= 2 and (st['sat_mean'] < 0.12 or st['colours'] == 1)
    if mono or (st['colours'] <= 2 and st['dark_share'] > 0.5):
        px = im.load(); w, h = im.size
        for y in range(h):
            for x in range(w):
                a = px[x, y][3]
                if a: px[x, y] = (255, 255, 255, a)
        return im, False
    if st['dark_share'] > 0.12:
        if st['light_share'] > 0.12:                 # dark and white parts: a badge would eat the white parts, paint all white
            px = im.load(); w, h = im.size
            for y in range(h):
                for x in range(w):
                    a = px[x, y][3]
                    if a: px[x, y] = (255, 255, 255, a)
            return im, False
        return im, True
    return im, False


def preview(slug, company, im, badge):
    W, Hh = 1600, 500
    bg = Image.new('RGBA', (W, Hh), BG + (255,)); d = ImageDraw.Draw(bg)
    y = 80
    if im is not None:
        lg = im.copy(); lg.thumbnail((700, 160), Image.LANCZOS)
        if badge:
            pad = 28; tile = Image.new('RGBA', (lg.width + 2 * pad, lg.height + 2 * pad), (255, 255, 255, 255))
            tile.alpha_composite(lg, (pad, pad)); lg = tile
        bg.alpha_composite(lg, (80, y)); y += lg.height + 40
    fnt = None
    for fp in (r'C:\Windows\Fonts\arialbd.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf'):
        if os.path.exists(fp): fnt = ImageFont.truetype(fp, 54); break
    d.text((80, y), ('logo as it ships' if im is not None else 'no logo: deck shows the name in text') + f'  ·  {company}', font=fnt, fill=(159, 176, 170, 255))
    bg.convert('RGB').save(os.path.join(PREV, slug + '.png'))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) < 3: print(__doc__); sys.exit(1)
    slug, company, url = args[0], args[1], args[2]
    spec = sys.argv[sys.argv.index('--spec') + 1] if '--spec' in sys.argv else None
    if not url.startswith('http'): url = 'https://' + url
    cands = []
    local = [f for f in (f'{slug}.png', f'{slug}.svg') if os.path.exists(os.path.join(LOGOS, f))]
    if '--keep' in sys.argv and local:
        f = local[0]; p = os.path.join(LOGOS, f)
        if f.endswith('.svg'):
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                b = pw.chromium.launch(); pg = b.new_page()
                im = render(pg, 'svg', open(p, encoding='utf-8').read(), {'color': '#fff'}); b.close()
        else: im = Image.open(p).convert('RGBA')
        if im is not None: cands = [('local', im, f, company, 5)]
    else:
        cands = fetch_candidates(url, company)
    best = None
    for kind, im, src, alt, prio in cands:
        im = strip_box(im); im = trim(im)
        if im is None: print(f'  empty  {kind:5} {src[:90]}'); continue
        s, st = score(kind, im, alt, company)
        if s > -99: s += prio
        print(f'  {s:6.2f}  {kind:5} {im.width}x{im.height}  {src[:90]}')
        if best is None or s > best[0]: best = (s, im, st, src)
    if best is None or best[0] < 3:
        print('RESULT no usable logo, deck shows the company name in text')
        for f in local: os.remove(os.path.join(LOGOS, f))
        preview(slug, company, None, False); out = None; badge = False
    else:
        im, st = best[1], best[2]
        im, badge = fix_for_dark(im, st)
        if im.height > H: im = im.resize((max(1, round(im.width * H / im.height)), H), Image.LANCZOS)
        for f in local: os.remove(os.path.join(LOGOS, f))
        out = slug + '.png'; im.save(os.path.join(LOGOS, out))
        st2 = analyse(im)
        print(f'RESULT {out}  badge={badge}  lum={st2["lum_mean"]:.2f} colours={st["colours"]} from {best[3][:80]}')
        preview(slug, company, im, badge)
    print('preview', os.path.join(PREV, slug + '.png'))
    if spec:
        sp = json.load(open(spec, encoding='utf-8'))
        sp.pop('logo', None); sp.pop('logo_badge', None)
        if out:
            sp['logo'] = out
            if badge: sp['logo_badge'] = True
        json.dump(sp, open(spec, 'w', encoding='utf-8'), indent=1, ensure_ascii=False); print('spec updated', spec)


if __name__ == '__main__':
    main()
