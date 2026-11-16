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
Prints "RESULT ..." and, with --json, a final JSON line {"file","badge","ok","text","judge","why"} for pipelines.
--keep: only the existing <out>/<slug>.(png|svg) (or --name) is normalised, nothing is fetched.

IDENTITY CHECK (2026-11-16, Thomas: a wrong logo must never ship again). Size, shape and contrast say nothing about WHOSE logo
it is: the tool shipped Forbes, partner, payment and award logos, menu glyphs and recoloured black boxes. So every candidate that
passes the guard goes on one numbered sheet and one Claude vision call (judge) answers which one is this company's own logo, or
none. None, unsure, or no Claude account reachable = the company name as text. Fail closed, never a guess.
Every file this tool writes carries a stamp inside the png (text chunk "logo-check": verdict logo|text, company, what the judge
read, source, hash of the pixels). build.py refuses any logo without a valid stamp (checked()), so a copied header image, an old
file, an svg or a file edited afterwards cannot reach a deck by any path. Text fallbacks are written with write_text() only.
SELF REPAIR (2026-11-16): when the first round confirms nothing, the tool searches on by itself before any text fallback: the
live header logo captured from the page at 4x (fixes vector logos that lose their styling when rendered alone), the logo named in
the page data (json-ld, meta, itemprop), every image on the page that is named logo or carries the company name (footer too), and
the logo on Wikidata when the entry's official website is the lead's domain. Same guard, same judge. Only then the name as text.
--approved "<who, why>" with --keep: stamps the existing file without the judge. ONLY when Thomas looked at that logo himself
and said it is right (e.g. an emblem the judge cannot know). Never to get a build through.
"""
import sys, os, re, json, io, math, time, hashlib, subprocess, tempfile

from PIL import Image, ImageDraw, ImageFont, ImageChops, PngImagePlugin

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


def open_site(ctx, url):
    """load the lead's site: challenge wait, cookie banner away -> page or None"""
    pg = ctx.new_page()
    try:
        pg.goto(url, wait_until='networkidle', timeout=45000)
    except Exception:
        try: pg.goto(url, wait_until='domcontentloaded', timeout=45000)
        except Exception as e: print('page failed', str(e)[:80]); return None
    pg.wait_for_timeout(2500)
    for n in range(8):                           # cloudflare "Just a moment" challenge: give it time to pass
        try:
            if not re.search(r'just a moment|attention required|checking your browser|verify you are human', pg.title(), re.I): break
        except Exception: pass
        pg.wait_for_timeout(2000)
    for s in ACCEPT:
        try: pg.locator(s).first.click(timeout=800); pg.wait_for_timeout(500); break
        except Exception: pass
    return pg


def evaluate(pg, js, arg):
    for n in range(4):                           # a site that redirects to its locale kills the first context
        try: return pg.evaluate(js, arg)
        except Exception as e:
            print('collect retry', n, str(e)[:60])
            try: pg.wait_for_load_state('networkidle', timeout=15000)
            except Exception: pass
            pg.wait_for_timeout(1500)
    return None


def fetch_candidates(url, company, local_files):
    """-> [(kind, image, src, alt, prio)] from the live site plus the local files already in the repo (kind 'local')"""
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--disable-blink-features=AutomationControlled'])
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, user_agent=UA, device_scale_factor=3)   # 3x: srcset serves its biggest file
        rp = b.new_context(viewport={'width': 1440, 'height': 900}, user_agent=UA).new_page()
        for f in local_files:
            im = load_local(rp, f)
            if im is not None: out.append(('local', im, os.path.basename(f), company, 0))
        if not url:
            b.close(); return out
        pg = open_site(ctx, url)
        if pg is None: b.close(); return out
        c = evaluate(pg, COLLECT, company) or {'imgs': [], 'svgs': [], 'bgs': [], 'icons': []}
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


MORE = r"""(company)=>{const o={urls:[],shots:[]};const co=(company||'').toLowerCase().split(' ')[0];
const add=(u,why,p)=>{if(!u||typeof u!=='string')return;try{u=new URL(u,location.href).href}catch(e){return}if(!o.urls.some(x=>x.src===u))o.urls.push({src:u,alt:why,prio:p})};
for(const s of document.querySelectorAll('script[type="application/ld+json"]')){try{const walk=(j,d)=>{if(!j||typeof j!=='object'||d>6)return;if(Array.isArray(j)){j.forEach(x=>walk(x,d+1));return}const l=j.logo;if(l)add(typeof l==='string'?l:(l.url||l.contentUrl||''),'json-ld logo',4);for(const k in j)if(j[k]&&typeof j[k]==='object')walk(j[k],d+1)};walk(JSON.parse(s.textContent),0)}catch(e){}}
for(const m of document.querySelectorAll('meta[property="og:logo"],meta[itemprop="logo"]')){add(m.content,'meta logo',3)}
for(const i of document.querySelectorAll('[itemprop="logo"]')){add(i.currentSrc||i.src||i.getAttribute('content')||i.getAttribute('href'),'itemprop logo',3)}
for(const i of document.querySelectorAll('img')){const u=i.currentSrc||i.src||i.getAttribute('data-src')||'';if(!u||u.startsWith('data:image/gif'))continue;const t=(u.split('?')[0].split('/').pop()+' '+(i.alt||'')+' '+i.className+' '+i.id).toLowerCase();const own=co.length>2&&t.includes(co);if(!/logo|brand|wordmark/.test(t)&&!own)continue;if(!own&&i.closest('[class*=partner i],[class*=client i],[class*=payment i],[class*=press i],[class*=trust i],[class*=award i],[class*=carousel i],[class*=slider i],[class*=review i]'))continue;add(u,i.alt||t.slice(0,60),(own?2:0)+(i.closest('header,[role=banner],footer')?1:0))}
const home=location.origin+'/';const vec=[];
for(const el of document.querySelectorAll('header svg, nav svg, [role=banner] svg, a[href="/"] svg, [class*=logo i] svg, svg[class*=logo i], [id*=logo i] svg, header img, a[href="/"] img, [class*=logo i] img, img[class*=logo i], [class*=brand i] svg, [class*=brand i] img')){
 if(el.tagName==='IMG'){const u=(el.currentSrc||el.src||'');if(!/\.svg$/i.test(u.split('?')[0])&&!/^data:image\/svg/.test(u))continue}
 else if(el.parentElement&&el.parentElement.closest('svg'))continue;
 const r=el.getBoundingClientRect();if(r.width<40||r.height<10||r.top>300||r.bottom<0||r.width>700)continue;const s=getComputedStyle(el);if(s.visibility==='hidden'||s.display==='none'||+s.opacity===0)continue;
 let p=0;if(el.closest('a[href="/"],a[href="'+home+'"],a[href="'+location.origin+'"]'))p+=3;const t=((el.getAttribute('class')||'')+' '+el.id+' '+(el.getAttribute('aria-label')||'')+' '+(el.alt||'')).toLowerCase();if(/logo|brand/.test(t)||el.closest('[class*=logo i],[id*=logo i]'))p+=2;if(co.length>2&&t.includes(co))p+=1;if(r.width/r.height<1.3)p-=3;vec.push([p,el,r])}
vec.sort((a,b)=>b[0]-a[0]);let n=0;for(const [p,el,r] of vec.slice(0,4)){el.setAttribute('data-lgshot',String(n));o.shots.push({n:n,prio:p,w:r.width,h:r.height,alt:el.getAttribute('aria-label')||el.alt||''});n++}
o.urls.sort((a,b)=>b.prio-a.prio);o.urls=o.urls.slice(0,10);return o}"""


def domain(u):
    return re.sub(r'^https?://', '', (u or '').strip().lower()).split('/')[0].split('?')[0].split(':')[0].removeprefix('www.')


def wikidata_logo(company, url):
    """the logo file on Wikidata, ONLY when the entry's official website is the lead's own domain -> image url or None"""
    import urllib.request, urllib.parse
    dom = domain(url)
    if not dom or not company: return None

    def get(q):
        r = urllib.request.Request('https://www.wikidata.org/w/api.php?' + urllib.parse.urlencode(dict(q, format='json')), headers={'User-Agent': 'deck-logo-tool/1.0'})
        return json.loads(urllib.request.urlopen(r, timeout=12).read().decode('utf-8'))
    try:
        ids = [x['id'] for x in get({'action': 'wbsearchentities', 'search': company, 'language': 'en', 'limit': 5}).get('search', [])]
        if not ids: return None
        ents = get({'action': 'wbgetentities', 'ids': '|'.join(ids), 'props': 'claims'}).get('entities', {})
        for i in ids:
            cl = ents.get(i, {}).get('claims', {})
            val = lambda p: [c['mainsnak']['datavalue']['value'] for c in cl.get(p, []) if c.get('mainsnak', {}).get('datavalue')]
            sites = [domain(v) for v in val('P856') if isinstance(v, str)]
            if not any(d == dom or d.endswith('.' + dom) or dom.endswith('.' + d) for d in sites if d): continue
            files = [v for v in val('P154') if isinstance(v, str)]
            if files: return 'https://commons.wikimedia.org/wiki/Special:FilePath/' + urllib.parse.quote(files[0].replace(' ', '_'))
    except Exception as e:
        print('  wikidata failed', str(e)[:60])
    return None


def fetch_more(url, company):
    """SELF REPAIR round, only when round one confirmed nothing -> [(kind, image, src, alt, prio)]"""
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--disable-blink-features=AutomationControlled'])
        rp = b.new_context(viewport={'width': 1440, 'height': 900}, user_agent=UA).new_page()
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, user_agent=UA, device_scale_factor=4)
        pg = open_site(ctx, url)
        c = (evaluate(pg, MORE, company) if pg is not None else None) or {'urls': [], 'shots': []}
        print(f"second round: {len(c['shots'])} live vector logo(s), {len(c['urls'])} named image(s)")
        for sh in c['shots']:                        # the logo exactly as the site paints it, at 4x
            try:
                buf = pg.locator(f'[data-lgshot="{sh["n"]}"]').first.screenshot(timeout=8000)
                out.append(('shot', Image.open(io.BytesIO(buf)).convert('RGBA'), 'live header logo ' + sh.get('alt', ''), sh.get('alt', ''), sh.get('prio', 0)))
            except Exception as e: print('  shot failed', str(e)[:60])
        urls = [(u['src'], u.get('alt', ''), u.get('prio', 0)) for u in c['urls']]
        wd = wikidata_logo(company, url)
        if wd: urls.append((wd, 'wikidata logo, official website matches', 4)); print('  wikidata', wd[:100])
        for src, alt, prio in urls:
            meta = {'nh': 0}
            big = fullsize(src); png = render(rp, 'img', big, meta) if big != src else None
            if png is None: png = render(rp, 'img', src, meta)
            else: src = big
            if png is None: print('  render failed', src[:80]); continue
            out.append(('more', png, src, alt, prio))
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
    """the header serves a thumbnail; ask the CDN for the original (Shopify width= / height= / _WxH@2x suffix, imgix / sanity / cloudinary w= h=)"""
    if u.startswith('data:'): return u
    m = re.search(r'/_next/image/?\?(?:.*&)?url=([^&]+)', u)                      # next.js image proxy: the original behind it
    if m:
        from urllib.parse import unquote, urljoin
        return fullsize(urljoin(u, unquote(m.group(1))))
    shop = '/cdn/shop/' in u
    u = re.sub(r'([?&])width=\d+', r'\g<1>width=1600', u) if shop else re.sub(r'([?&])width=\d+&?', r'\1', u)   # shopify never upscales, others may
    for _ in range(6): u = re.sub(r'([?&])(height|w|h|dpr|fit|crop)=[\w.,]+&?', r'\1', u)
    u = re.sub(r'[?&]$', '', u)
    if shop: u = re.sub(r'_(\d{2,4})?x(\d{2,4})?(@\dx)?(_crop_\w+)?(\.(png|webp|gif|svg|jpe?g))', r'\5', u)
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
    """build-time check of a logo file -> None when fine, else what is wrong (the build must refuse it). Same rules for every deck.
    A file path must carry the identity stamp of this tool (checked()); an image object is only measured."""
    bg = hexrgb(bg) if isinstance(bg, str) else tuple(bg)
    light = (0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]) / 255 > 0.5
    if isinstance(path, Image.Image): im = path
    else:
        if not os.path.exists(path): return 'missing'
        if not path.lower().endswith('.png'): return 'not a png from logo.py'
        why = checked(path)[1]                       # THE LOCK of every build: no identity stamp, no deck
        if why: return why
        im = Image.open(path).convert('RGBA')
    st = analyse(im)
    if st is None: return 'empty'
    if im.height < 90: return f'too small ({im.width}x{im.height}), pixel mush at deck size'
    if im.width / im.height < 1.15: return 'an icon, not a wordmark'
    if light and st['lum_mean'] > 0.75: return 'light on a white slide'
    if not light and st['lum_mean'] < 0.45 and not badge: return 'dark on a dark slide and no badge'
    return None


# ---------------------------------------------------------------- identity check and stamp
MARK = 'logo-check'
JUDGE_MODEL = os.environ.get('LOGO_JUDGE_MODEL', 'claude-haiku-5-5')
JUDGE_MAX = 6


def slide_trim(im, dark=False):
    """empty margins off, exactly what the deck shows: transparent ones always, white ones only for a white slide (on a dark slide white
    IS the logo, it must never be cut away). Idempotent, the stamp hash is taken after it."""
    im = im.convert('RGBA')
    a = im.getchannel('A').point(lambda v: 255 if v > 8 else 0)
    if dark:
        bb = a.getbbox()
        return im.crop(bb) if bb and bb != (0, 0) + im.size else im
    ink = ImageChops.multiply(a, im.convert('L').point(lambda v: 255 if v < 245 else 0))
    bb = ink.getbbox() or a.getbbox()
    return im.crop(bb) if bb and bb != (0, 0) + im.size else im


def pixhash(im, dark=False):
    im = slide_trim(im, dark)
    return hashlib.sha1(('%dx%d' % im.size).encode() + im.tobytes()).hexdigest()[:20]


def stamp(im, path, verdict, company, dark=False, **info):
    """the ONLY way a logo file is written: trimmed, with the check result inside the png. dark = the file is for a dark slide."""
    im = slide_trim(im, dark)
    meta = dict(v=1, verdict=verdict, company=company, sha=pixhash(im, dark), at=time.strftime('%Y-%m-%d %H:%M'))
    if dark: meta['dark'] = 1
    meta.update({k: str(v)[:200] for k, v in info.items() if v})
    pi = PngImagePlugin.PngInfo(); pi.add_text(MARK, json.dumps(meta, ensure_ascii=True))
    im.save(path, pnginfo=pi)
    return meta


def checked(path):
    """-> (stamp dict, None) when the file was written by this tool after the identity check and not touched since, else (None, why)"""
    if not os.path.exists(path): return None, 'missing'
    if not path.lower().endswith('.png'): return None, 'not a png from logo.py'
    try:
        im = Image.open(path); raw = (im.info or {}).get(MARK); im = im.convert('RGBA')
    except Exception as e: return None, 'unreadable (%s)' % str(e)[:40]
    if not raw: return None, 'not checked: no identity stamp, the file was not written by logo.py'
    try: meta = json.loads(raw)
    except Exception: return None, 'not checked: broken stamp'
    if meta.get('verdict') not in ('logo', 'text'): return None, 'not checked: stamp without verdict'
    if meta.get('sha') != pixhash(im, bool(meta.get('dark'))): return None, 'changed after the identity check'
    return meta, None


def write_text(company, path, rgb=INK, why=''):
    """the company name as text, stamped. The fallback of every pipeline (never wordmark().save() directly)."""
    im = wordmark(company, tuple(rgb)); stamp(im, path, 'text', company, dark=sum(tuple(rgb)[:3]) > 600, why=why or 'no confirmed logo')
    return im


def sheet(images, path, bg=(255, 255, 255), badges=()):
    """numbered contact sheet of the candidates as they would ship, for the judge"""
    W, RH = 1000, 260
    sh = Image.new('RGBA', (W, RH * len(images)), tuple(bg) + (255,)); d = ImageDraw.Draw(sh); fnt = font(40)
    for i, im in enumerate(images):
        lg = im.convert('RGBA'); lg.thumbnail((760, 190), Image.LANCZOS)
        if i < len(badges) and badges[i]:
            t = Image.new('RGBA', (lg.width + 24, lg.height + 24), (255, 255, 255, 255)); t.alpha_composite(lg, (12, 12)); lg = t
        sh.alpha_composite(lg, (170, i * RH + (RH - lg.height) // 2))
        d.text((30, i * RH + 100), str(i + 1), font=fnt, fill=(210, 30, 30, 255)); d.line([0, (i + 1) * RH - 1, W, (i + 1) * RH - 1], fill=(128, 128, 128, 255))
    sh.convert('RGB').save(path)


def claude_tokens():
    """the long lived Claude subscription tokens in AIOS .env, in order (same accounts the deck pipeline uses). No API key, never OpenAI."""
    envf = os.path.expanduser('~/Desktop/AIOS/.env')
    kv = dict(re.findall(r'^([A-Z0-9_]+)=(.*)$', open(envf, encoding='utf-8').read(), re.M)) if os.path.exists(envf) else {}
    names = os.environ.get('LOGO_CLAUDE_TOKENS', 'REPLYOS_CLAUDE_OAUTH_TOKEN_2,REPLYOS_CLAUDE_OAUTH_TOKEN,REPLYOS_CLAUDE_OAUTH_TOKEN_3').split(',')
    return [kv[n].strip().strip('"').strip("'") for n in names if kv.get(n, '').strip()]


_dead = set()   # tokens that failed in this process: not tried again


def judge(company, url, images, bg=(255, 255, 255), badges=()):
    """ONE vision call: which numbered candidate is this company's own logo. -> (pick 1..n, reads, why), (0, reads, why) when none is,
    (None, '', reason) when no Claude account could answer. The caller treats 0 and None the same: company name as text."""
    if not images: return 0, '', 'no candidate'
    work = tempfile.mkdtemp(prefix='logojudge'); sp = os.path.join(work, 'sheet.png'); sheet(images, sp, bg, badges)
    dom = re.sub(r'^https?://(www\.)?', '', url or '').split('/')[0]
    msg = (f'Read the image file {sp}. It shows {len(images)} numbered candidate image(s)' + (f' scraped from the website {dom}' if dom else '') + '. '
           f'The company is "{company}". Which candidate is this company\'s own brand logo (its name, a clear short form of its name, or its own emblem)? '
           'Reject: logos of other brands (press, partners, payment, app stores, review sites, awards, certificates, shop platforms), photos, product shots, '
           'menu icons, arrows, single generic glyphs, solid boxes or blobs, cut off, unreadable or broken graphics. If you are not sure it is this company\'s own logo, answer 0. '
           'Answer with JSON only: {"pick": <number, or 0 if none>, "reads": "<the text you read in the picked candidate, or in the first one>", "why": "<max 12 words>"}')
    txt, err = ask_claude(msg, work)
    for attempt in range(2):
        if txt is None: break
        try:
            a = json.loads(re.search(r'\{[^{}]*"pick"[^{}]*\}', txt).group(0)); pick = int(a.get('pick') or 0)
            if not 0 <= pick <= len(images): raise ValueError('pick out of range')
            return pick, str(a.get('reads') or '')[:80], str(a.get('why') or '')[:120]
        except Exception as ex:
            err = 'judge answer unusable: ' + str(ex)[:80]
            txt = ask_claude(msg, work)[0] if attempt == 0 else None
    print('  judge unavailable:', err)
    return None, '', 'judge unavailable: ' + str(err)


def ask_claude(msg, work):
    """one headless Claude call that may only read files -> (answer text, None) or (None, why). Walks the subscription tokens in order."""
    win = os.name == 'nt'
    cbin = 'claude' if win else (os.path.expanduser('~/.local/bin/claude') if os.path.exists(os.path.expanduser('~/.local/bin/claude')) else 'claude')
    cfg = os.path.expanduser('~/.claude-accounts/logo-judge'); os.makedirs(cfg, exist_ok=True)
    args = [cbin, '-p', '--model', JUDGE_MODEL, '--output-format', 'json', '--tools', 'Read', '--allowedTools', 'Read', '--disable-slash-commands',
            '--setting-sources', '', '--no-session-persistence']
    last = 'no Claude token in AIOS .env'
    for tok in claude_tokens():
        if tok in _dead: continue
        try:
            e = {k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY'}
            e.update(CLAUDE_CONFIG_DIR=cfg, CLAUDE_CODE_OAUTH_TOKEN=tok)
            r = subprocess.run(args, input=msg, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240, cwd=work, shell=win, env=e)
            d = json.loads(r.stdout[r.stdout.index('{'):])
            if d.get('is_error'):
                last = str(d.get('result'))[:120]
                if not re.search(r'(?i)overloaded|timeout|timed out|5\d\d', last): _dead.add(tok)
                continue
            return str(d.get('result')), None
        except Exception as ex:
            last = 'claude call failed: ' + str(ex)[:80]
    return None, last


def hexrgb(s):
    s = s.strip().lstrip('#')
    if len(s) == 3: s = ''.join(c * 2 for c in s)
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def run(slug, company, url, bg, out_dir, name=None, preview_dir=None, keep=False, on_none='remove', approved=''):
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
    texts = [f for f in locals_ if ((checked(f)[0] or {}).get('verdict') == 'text')]   # our own text fallback is no logo candidate
    cands = fetch_candidates('' if keep else url, company, [f for f in locals_ if f not in texts])
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
    res = {'file': None, 'badge': False, 'ok': False, 'text': False, 'judge': '', 'why': '', 'round': 1}

    def passing(scored):
        ok = []
        for s, im, st, src in sorted(scored, key=lambda x: -x[0]):   # best first; every one the build guard accepts goes to the judge
            if s < 3: break
            im, badge = (fix_for_light if light else fix_for_dark)(im.copy(), st)
            if im.height > H: im = im.resize((max(1, round(im.width * H / im.height)), H), Image.LANCZOS)
            bad = guard(im, bg, badge)
            if bad: print(f'  rejected ({bad}): {src[:70]}'); continue
            ok.append((im, badge, st, src))
            if len(ok) == JUDGE_MAX: break
        return ok

    def decide(ok):
        pick, reads, why = judge(company, url, [o[0] for o in ok], bg, [o[1] for o in ok])
        res['judge'] = 'down' if pick is None else ('ok' if pick else 'none')
        print(f'  judge: pick={pick} reads="{reads}" why="{why}"')
        return (ok[pick - 1] if pick else None), reads, why
    ok = passing(scored)
    best, reads, why = None, '', 'no candidate passed the quality guard'
    if ok and approved:
        best, reads, why = ok[0], '', 'approved by hand: ' + approved; res['judge'] = 'approved'
    elif ok:
        best, reads, why = decide(ok)
    if best is None and not keep and url and res['judge'] != 'down':     # SELF REPAIR: search on before any text fallback
        res['round'] = 2; more = []
        try: cands2 = fetch_more(url, company)
        except Exception as e: print('  second round failed', str(e)[:80]); cands2 = []
        for kind, im, src, alt, prio in cands2:
            im = trim(strip_box(im))
            if im is None: continue
            s, st = score(kind, im, alt, company)
            if s > -99: s += prio
            print(f'  {s:6.2f}  {kind:5} {im.width}x{im.height}  {src[:90]}')
            more.append((s, im, st, src))
        ok2 = passing(more)
        if ok2:
            best, reads, why2 = decide(ok2); why = why2
        elif not ok: why = 'no candidate passed the quality guard, second round included'
    res['why'] = why
    if best is None:
        if on_none == 'text':
            im = write_text(company, os.path.join(out_dir, name), INK if light else (255, 255, 255), why)
            res.update(file=name, text=True)
            print(f'RESULT no confirmed logo ({why}), wordmark of the company name written to {name}')
            preview(os.path.join(preview_dir, slug + '.png'), bg, company, im, False)
        else:
            print(f'RESULT no confirmed logo ({why}), deck shows the company name in text')
            preview(os.path.join(preview_dir, slug + '.png'), bg, company, None, False)
    else:
        im, badge, st, src = best
        stamp(im, os.path.join(out_dir, name), 'logo', company, dark=not light, src=src, reads=reads, why=why, badge=badge, round=res['round'])
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
    res = run(slug, company, url, opt('--bg'), opt('--out'), opt('--name'), opt('--preview'), '--keep' in sys.argv, opt('--on-none', 'remove'),
              opt('--approved', '') if '--keep' in sys.argv else '')
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
