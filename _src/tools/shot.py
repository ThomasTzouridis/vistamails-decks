# -*- coding: utf-8 -*-
"""Screenshot pages of a lead website for a pitch deck.
Usage: py shot.py <slug> <outdir> <url1> [url2 ...]
Writes <outdir>/<slug>_<n>.jpg (1200px wide, 16:10 crop, popups removed, scrolled to top),
<outdir>/<slug>_info.json (logo candidates: inline svg or img src, h1, fonts) and prints them.
"""
import asyncio, json, sys, os, re
from playwright.async_api import async_playwright
from PIL import Image
sys.stdout.reconfigure(encoding="utf-8")
slug, out = sys.argv[1], sys.argv[2]; urls = sys.argv[3:]
os.makedirs(out, exist_ok=True)
# popup remover (2026-09-16): cookie banners, consent walls, newsletter and HCP popups, empty dimming overlays.
# Never the page itself: not html/body/main, nothing holding the h1 or more than half of the page text (corcept.com:
# <html> carries a consent class, the whole document went). A fixed or sticky element only goes when it looks like
# a popup (bicycletherapeutics.com: the hero is position:fixed, it went and the shot came out black).
KILL = """(()=>{const bl=((document.body&&document.body.innerText)||'').length;
const POP=/cookie|consent|gdpr|privacy|newsletter|subscribe|healthcare professional|medical professional/i;
const page=el=>el===document.documentElement||el===document.body||el.tagName==='MAIN'||!!el.querySelector('main,h1')||(bl>0&&(el.innerText||'').length>0.5*bl);
for(const el of document.querySelectorAll('body *')){try{if(!el.isConnected)continue;const s=getComputedStyle(el);
if((s.position==='fixed'||s.position==='sticky')&&el.getBoundingClientRect().height>150&&!el.closest('nav,header')&&el.tagName!=='NAV'&&el.tagName!=='HEADER'&&!page(el)){
const t=(el.innerText||'').trim();
const dimmer=t.length<3&&!el.querySelector('img,video,canvas,picture,svg,iframe');
if(dimmer||POP.test(t)||el.getAttribute('role')==='dialog'||el.getAttribute('aria-modal')==='true')el.remove();}}catch(e){}}
for(const el of document.querySelectorAll('body [id*=cookie i],body [class*=cookie i],body [id*=consent i],body [class*=consent i],body [class*=popup i],body [class*=modal i]')){try{if(el.isConnected&&el.getBoundingClientRect().height>60&&!page(el))el.remove();}catch(e){}}
if(document.body)document.body.style.overflow='auto';return 1;})()"""
SIZE = "()=>((document.body&&document.body.innerText)||'').length"
# consent / close clicks. 'OK' must be the whole button text (has-text is a substring match and hit "Cookie
# Settings" on corcept.com); the text= rule also catches accept links and divs that are no <button> (bicycle).
CONSENT = ["#onetrust-accept-btn-handler", "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
           "#CybotCookiebotDialogBodyButtonAccept", "button:has-text('Accept')", "button:has-text('I agree')",
           "button:text-is('OK')",
           r"text=/^\s*(accept|accept all|accept all cookies|accept cookies|allow all|allow all cookies|i agree|got it)\s*$/i",
           # 2026-10-17: German, Spanish, French, Italian, Dutch wording (biotest.com's "Alle akzeptieren" stayed in the shot)
           r"text=/^\s*(alle akzeptieren|akzeptieren|alles akzeptieren|alle cookies akzeptieren|zustimmen|einverstanden|"
           r"aceptar|aceptar todo|aceptar todas|aceptar todas las cookies|aceptar cookies|"
           r"accepter|tout accepter|accepter tout|j'accepte|accetta|accetta tutto|accetta tutti|accetto|"
           r"alles accepteren|accepteren|akkoord)\s*$/i",
           "[aria-label*=close i]", "[class*=close i]"]
INFO_JS = """()=>{const o={imgs:[],svgs:[]};
for(const i of document.querySelectorAll('header img, nav img, a[href="/"] img, [class*=logo i] img, [class*=brand i] img')){if(i.naturalWidth>40)o.imgs.push({src:i.currentSrc||i.src,w:i.naturalWidth,h:i.naturalHeight,alt:i.alt})}
for(const s of document.querySelectorAll('header svg, nav svg, a[href="/"] svg, [class*=logo i] svg')){const r=s.getBoundingClientRect(); if(r.width>40)o.svgs.push(s.outerHTML.slice(0,40000))}
for(const el of document.querySelectorAll('header *, nav *, a[href="/"], a[href="/"] *, [class*=logo i], [class*=logo i] *, [class*=brand i]')){try{const r=el.getBoundingClientRect();if(r.width<40||r.height<10)continue;const bg=getComputedStyle(el).backgroundImage||'';let u='';if(bg.indexOf('url(')===0){u=bg.slice(4,bg.lastIndexOf(')')).trim();if(u[0]==='"'||u[0]==="'")u=u.slice(1,-1)};if(u&&u.indexOf('data:')!==0)o.imgs.push({src:new URL(u,location.href).href,w:Math.round(r.width),h:Math.round(r.height),alt:(el.getAttribute('aria-label')||el.getAttribute('title')||'')+' background'})}catch(e){}}
const h1=document.querySelector('h1');o.h1=h1&&h1.innerText;o.title=document.title;return o}"""


async def ev(pg, js, default):
    """page.evaluate that never raises (a page navigating or breaking its own scripts must not kill the run)"""
    try:
        return await pg.evaluate(js)
    except Exception:
        return default


# bot check pages (telumtherapeutics.com 2026-09-17: "Checking the site connection security" got shot as the homepage)
CHALLENGE = re.compile(r"checking the site connection security|checking your browser|just a moment|verify(ing)? you are human|"
                       r"attention required|ddos protection|please wait while|pardon our interruption|you have been blocked|"
                       r"access denied|request unsuccessful|enable javascript and cookies|robot challenge|might be a robot|are you a robot|"
                       r"complete the captcha|captcha below|solve the captcha|prove you.?re (a )?human|unusual traffic", re.I)
HEAD_JS = "()=>[document.title||'', ((document.body&&document.body.innerText)||'').slice(0,1600)]"


async def load(pg, u):
    """navigate; False when the page does not load or stays behind a bot check (then it is never shot)"""
    try:
        await pg.goto(u, wait_until="networkidle", timeout=45000)
    except Exception:
        try:
            await pg.goto(u, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print("FAILED", u, e)
            return False
    await pg.wait_for_timeout(2500)
    for n in range(9):          # a bot check usually passes by itself within a few seconds and loads the page
        title, text = await ev(pg, HEAD_JS, ["", ""])
        if len(text) >= 1500 or not CHALLENGE.search(title + " " + text):
            if n:
                await pg.wait_for_timeout(2500)
            return True
        await pg.wait_for_timeout(2500)
    print("BLOCKED", u)
    return False


async def consent(pg):
    for sel in CONSENT:
        try:
            for h in await pg.query_selector_all(sel):
                if await h.is_visible():
                    await h.click(timeout=800)
        except Exception:
            pass


def blank(png):
    """True when the screenshot is one flat colour (page not rendered, or its content removed)"""
    im = Image.open(png).convert("L").resize((120, 75))
    px = list(im.getdata())
    m = sum(px) / len(px)
    return (sum((q - m) ** 2 for q in px) / len(px)) ** 0.5 <= 8


async def main():
    async with async_playwright() as p:
        # SHOT_CHROME=1 (2026-10-15): real installed Chrome, headed, for sites whose bot wall rejects headless Chromium (merckgroup.com 403)
        b = await (p.chromium.launch(channel="chrome", headless=False, args=["--disable-blink-features=AutomationControlled"]) if os.environ.get("SHOT_CHROME") else p.chromium.launch(args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]))
        ctx = await b.new_context(viewport={"width": 1440, "height": 900}, user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36", locale="en-US", ignore_https_errors=True, extra_http_headers={"Accept-Language": "en-US,en;q=0.9"})
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});window.chrome={runtime:{}};")
        pg = await ctx.new_page(); info = {}
        for i, u in enumerate(urls, 1):
            if not await load(pg, u):
                continue
            url0 = pg.url
            await consent(pg)
            if pg.url.split("#")[0].rstrip("/") != url0.split("#")[0].rstrip("/"):
                print("a popup click left the page, loading it again", u)
                await load(pg, url0)
            before = await ev(pg, SIZE, 0)
            await ev(pg, KILL, 0); await ev(pg, "window.scrollTo(0,0)", 0); await pg.wait_for_timeout(1200)
            await ev(pg, KILL, 0); await ev(pg, "window.scrollTo(0,0)", 0); await pg.wait_for_timeout(500)
            if before > 300 and await ev(pg, SIZE, 0) < 0.3 * before:
                # the popup remover still took the page content: shoot the page untouched instead
                print("popup removal emptied the page, loading it again without it", u)
                await load(pg, url0); await ev(pg, "window.scrollTo(0,0)", 0)
            png = f"{out}/{slug}_{i}.png"
            await pg.screenshot(path=png)
            if blank(png):
                # still one flat colour: load again and shoot untouched (consent is stored by now)
                print("blank screenshot, loading the page again and shooting it untouched", u)
                if await load(pg, url0):
                    await pg.wait_for_timeout(2000); await ev(pg, "window.scrollTo(0,0)", 0)
                    await pg.screenshot(path=png)
            im = Image.open(png).convert("RGB"); im = im.crop((0, 0, im.width, int(im.width * 0.625))).resize((1200, 750), Image.LANCZOS)
            im.save(f"{out}/{slug}_{i}.jpg", quality=86, optimize=True); os.remove(png); print("shot", i, u)
            if not info:    # logo candidates from the first page that loaded (the homepage unless it was blocked)
                info = await ev(pg, INFO_JS, None) or {"imgs": [], "svgs": [], "h1": None, "title": ""}
                # download logo candidates THROUGH the browser (2026-09-16): bot walls answer plain HTTP with a
                # challenge page (Telum: 202 text/html), the browser context carries the cookies the homepage set
                files, seen = [], set()
                imgs = info.get("imgs") or []
                cands = [x for x in imgs if re.search(r"logo|brand|wordmark", (x.get("src") or "") + (x.get("alt") or ""), re.I)] + imgs
                for c in cands:
                    src = c.get("src") or ""
                    if not src.startswith("http") or src in seen or len(files) >= 4:
                        continue
                    seen.add(src)
                    try:
                        body, ct = b"", ""
                        r = await ctx.request.get(src, timeout=20000)
                        if r.ok:
                            body, ct = await r.body(), (r.headers.get("content-type") or "").lower()
                        if not (ct.startswith("image/") or b"<svg" in body[:600]):
                            p2 = await ctx.new_page()
                            for _ in range(2):   # 2nd load after a JS challenge returns the file itself
                                resp = await p2.goto(src, timeout=30000)
                                await p2.wait_for_timeout(1200)
                                if resp:
                                    body, ct = await resp.body(), (resp.headers.get("content-type") or "").lower()
                                    if ct.startswith("image/") or b"<svg" in body[:600]:
                                        break
                            await p2.close()
                        if body and (ct.startswith("image/") or b"<svg" in body[:600]):
                            ext = "svg" if ("svg" in ct or b"<svg" in body[:600]) else "img"
                            fn = f"{slug}_logo{len(files) + 1}.{ext}"
                            open(f"{out}/{fn}", "wb").write(body)
                            files.append({"src": src, "file": fn, "alt": c.get("alt") or "", "w": c.get("w"), "h": c.get("h")})
                    except Exception as e:
                        print("logo download failed", src[:80], str(e)[:80])
                info["logo_files"] = files
                json.dump(info, open(f"{out}/{slug}_info.json", "w", encoding="utf-8"), indent=1)
        await b.close()
    print(json.dumps({"h1": info.get("h1"), "title": info.get("title"), "imgs": info.get("imgs", [])[:5], "svgs": len(info.get("svgs", []))}, ensure_ascii=False))
asyncio.run(main())
