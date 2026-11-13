"""Build one VistaMails deck per spec: py build.py specs/<slug>.json -> ../<slug>/index.html

Spec fields (JSON):
  slug          folder name and URL part (required)
  company       lead company, as it should read in text (required)
  first_name    first name of the lead
  last_name     last name of the lead (cover: "Prepared for <first_name> <last_name>, <company>")
  domain        the lead's site, shown under the screenshot (required)
  shot          file in assets/shots/ (required, the cover shows it; take it with 3DforScience/_src/tools/shot.py)
  logo          file in assets/leadlogos/, ALWAYS produced by tools/logo.py (py tools/logo.py <slug> "<Company>" https://<domain> --bg #041010 --out assets/leadlogos --spec specs/<slug>.json --badge-key logo_badge):
                it picks the site's wordmark, rejects icons, photos and pixel-small rasters, paints one-colour logos white, puts dark
                multi-colour logos on a white badge (logo_badge) and writes a preview on the deck background to assets/leadlogos/_preview/.
                No usable logo = key omitted = company name in text. build.py refuses a png that is small, square or dark without a badge.
  logo_badge    true = logo on a white badge (for dark logos)
  guarantee     "A" = 100% refund plus $5,000 transfer (message 1A), "B" = 100% refund only (message 1B). Default "B".
  cover_line    optional, default "More revenue for <company>, from the customers you already have."
  (slide 2 is fixed since 2026-10-31: heading "How we work" + the offer line from guarantee A or B, nothing lead specific;
   saw, saw_head, saw_l1, saw_l2, saw_turn, audit_tail are ignored)
  audit_tail    optional sentence appended to step 01 (something specific to their store), default ""
  proof_head    optional, default "More of our work."
  talk_text     optional, default sentence under the Let's talk headline
  booking_url   optional, default Umesh's Calendly
  lang          optional deck language (key of i18n.json, e.g. de, fr, ptbr). Not "en" = the page goes to <slug>/<lang>/index.html,
                every visible text from i18n.json (cover_line/proof_head spec overrides ignored), asset paths one level deeper.
"""
import json, sys, os, html
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
BG = '#041010'   # the deck --paper, the logo tool checks against it
BOOK = 'https://calendly.com/umesh-gps/vistamails-email-marketing-discovery-call'
LOGOS = ''.join(f'<img src="../assets/clients/{n}" alt="">' for n in
                ["walkeepaws.png", "keebos.png", "lunarchi.png", "viebys.png", "pukingball.png", "allure.png", "celsius.png", "bamboobaby.png", "marbella.png", "martonfraser.png"])
G = {'A': ("Within 60 days of starting, we raise {co}'s revenue by 20% with our segment reactivation system. If we miss that, you get back every dollar you paid us, and we send you $5,000 on top.",
           "We pay back every fee {co} paid us, in full. On top of that, we send $5,000 from our account to {co}'s account."),
     'B': ("Within 60 days of starting, we raise {co}'s revenue by 20% with our segment reactivation system. If we miss that, you get back every dollar you paid us.",
           "We pay back every fee {co} paid us, in full.")}
I18N = os.path.join(HERE, 'i18n.json')
# English fragment in template.html (as >TEXT<) per i18n key; {company} -> {{COMPANY}}, {name} -> {{PREPARED}}
FRAG = ['prep', 'nx1', 'h_offer', 'lab_target', 'p_target', 'lab_cond', 'p_cond', 'lab_miss', 'nx2', 'st1', 'st2', 'st3', 'st4',
        'c1y', 'c1b', 'c1p', 'c2y', 'c2p', 'trusted', 'nx3', 'h_talk', 'btn', 'reply']


def localize(out, lang, co, prep):
    tr = json.load(open(I18N, encoding='utf-8'))
    en, t = tr['en'], tr[lang]
    for k in FRAG:
        a = '>' + en[k].replace('{company}', '{{COMPANY}}').replace('{name}', '{{PREPARED}}') + '<'
        assert out.count(a) == 1, f'i18n anchor {k} found {out.count(a)}x'
        b = '>' + html.escape(t[k], quote=False).replace('{company}', '{{COMPANY}}').replace('{name}', '{{PREPARED}}') + '<'
        out = out.replace(a, b)
    out = out.replace('<html lang="en">', '<html lang="%s">' % ('pt-BR' if lang == 'ptbr' else 'nb' if lang == 'no' else lang), 1)
    return out


for path in sys.argv[1:]:
    sp = json.load(open(path, encoding='utf-8'))
    lang = (sp.get('lang') or 'en').lower()
    T = json.load(open(I18N, encoding='utf-8'))[lang] if lang != 'en' else None
    e = html.escape
    co = e(sp['company'])
    for k in ('slug', 'company', 'domain', 'shot'):
        assert sp.get(k), f'{path}: missing {k}'
    assert os.path.exists(os.path.join(ROOT, 'assets', 'shots', sp['shot'])), f'{path}: shot file missing'
    name = ' '.join(x for x in (sp.get('first_name', '').strip(), sp.get('last_name', '').strip()) if x)
    prep = f"{e(name)}, {co}" if name else co
    mark = f'<span class="co">{co}</span>'
    if sp.get('logo'):
        lp = os.path.join(ROOT, 'assets', 'leadlogos', sp['logo'])
        assert os.path.exists(lp), f'{path}: logo file missing'
        sys.path.insert(0, os.path.join(HERE, 'tools')); from logo import guard
        bad = guard(lp, BG, sp.get('logo_badge'))
        assert not bad, f"{path}: logo {sp['logo']} is {bad}. Run: py tools/logo.py {sp['slug']} \"{sp['company']}\" https://{sp['domain']} --bg {BG} --out assets/leadlogos --spec {path} --badge-key logo_badge"

        fb = "var s=document.createElement('span');s.className='co';s.textContent=this.alt;(this.closest('.llb')||this).replaceWith(s)"
        img = f'<img class="ll" src="../assets/leadlogos/{sp["logo"]}" alt="{co}" onerror="{fb}">'
        mark = f'<span class="llb">{img}</span>' if sp.get('logo_badge') else img
    gh, gm = (s.format(co=co) for s in G[sp.get('guarantee', 'B').upper()])
    out = open(os.path.join(HERE, 'template.html'), encoding='utf-8').read()
    if T:
        ab = 'ga' if sp.get('guarantee', 'B').upper() == 'A' else 'gb'
        gh, gm = (html.escape(T[ab + x], quote=False).replace('{company}', co) for x in ('_head', '_miss'))
        sp = dict(sp, cover_line=T['cover_line'].replace('{company}', sp['company']), proof_head=T['proof_head'])
        out = localize(out, lang, co, prep)
    for k, v in {'COMPANY': co, 'PREPARED': prep, 'CO_MARK': mark, 'DOMAIN': e(sp['domain']), 'SHOT': sp['shot'],
                 'COVER_LINE': e(sp.get('cover_line') or f"More revenue for {sp['company']}, from the customers you already have."),
                 'AUDIT_TAIL': e(sp.get('audit_tail', '')),
                 'PROOF_HEAD': e(sp.get('proof_head') or "More of our work."),
                 'G_HEAD': gh, 'G_MISS': gm, 'LOGOS': LOGOS,
                 'TALK_TEXT': e(sp.get('talk_text') or f"Thirty minutes with Umesh, Co-Founder and CEO: the audit for {sp['company']}, the dormant segments we would start with and what the first 60 days look like."),
                 'BOOKING_URL': sp.get('booking_url') or BOOK}.items():
        out = out.replace('{{' + k + '}}', v)
    assert '{{' not in out, path
    if T:
        out = out.replace('../assets/', '../../assets/').replace('../vendor/', '../../vendor/')
    d = os.path.join(ROOT, sp['slug'], *([lang] if T else [])); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, 'index.html'), 'w', encoding='utf-8').write(out)
    print('built', sp['slug'] + ('/' + lang if T else ''), '· guarantee', sp.get('guarantee', 'B').upper())
