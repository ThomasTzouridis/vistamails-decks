"""Build one VistaMails deck per spec: py build.py specs/<slug>.json -> ../<slug>/index.html

Spec fields (JSON):
  slug          folder name and URL part (required)
  company       lead company, as it should read in text (required)
  first_name    first name of the lead (cover: "Prepared for <first_name> · <company>")
  domain        the lead's site, shown under the screenshot (required)
  shot          file in assets/shots/ (required, the cover shows it; take it with 3DforScience/_src/tools/shot.py)
  logo          file in assets/leadlogos/ (white or light logo on transparent for the dark deck); omitted = company name in text
  logo_badge    true = logo on a white badge (for dark logos)
  guarantee     "A" = 100% refund plus $5,000 transfer (message 1A), "B" = 100% refund only (message 1B). Default "B".
  cover_line    optional, default "20% more revenue in 60 days for <company>, from the customers you already have."
  saw_head      headline of slide 2, max ~8 words
  saw_l1, saw_l2  two plain lines about what we saw on the lead's site (facts only, no numbers we did not see)
  saw_turn      the highlighted line: what the segment reactivation system changes for them (22 to 32 words, no bold)
  audit_tail    optional sentence appended to step 01 (something specific to their store), default ""
  proof_head    optional, default "<company> would not be the first."
  talk_text     optional, default sentence under the Let's talk headline
  booking_url   optional, default Umesh's Calendly
"""
import json, sys, os, html
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
BOOK = 'https://calendly.com/umeshpdy95/email-strategy-consutling'
LOGOS = ''.join(f'<img src="../assets/clients/{n}" alt="">' for n in
                ["walkeepaws.png", "keebos.png", "lunarchi.png", "viebys.png", "pukingball.png", "allure.png", "celsius.png", "bamboobaby.png", "marbella.png", "martonfraser.png"])
G = {
    'A': ("20% more revenue in 60 days, or you pay nothing and we send you $5,000.",
          "We agree the baseline with you up front. If {co} is not up 20% in revenue after 60 days, we refund everything you paid us, 100% of it and not a portion, and personally transfer $5,000 to your bank account to say sorry."),
    'B': ("20% more revenue in 60 days, or you pay nothing.",
          "We agree the baseline with you up front. If {co} is not up 20% in revenue after 60 days, we refund everything you paid us, 100% of it and not a portion."),
}
for path in sys.argv[1:]:
    sp = json.load(open(path, encoding='utf-8'))
    e = html.escape
    co = e(sp['company'])
    for k in ('slug', 'company', 'domain', 'shot', 'saw_head', 'saw_l1', 'saw_l2', 'saw_turn'):
        assert sp.get(k), f'{path}: missing {k}'
    assert os.path.exists(os.path.join(ROOT, 'assets', 'shots', sp['shot'])), f'{path}: shot file missing'
    prep = f"{e(sp['first_name'])} · {co}" if sp.get('first_name') else co
    mark = f'<span class="co">{co}</span>'
    if sp.get('logo'):
        assert os.path.exists(os.path.join(ROOT, 'assets', 'leadlogos', sp['logo'])), f'{path}: logo file missing'
        img = f'<img class="ll" src="../assets/leadlogos/{sp["logo"]}" alt="{co}">'
        mark = f'<span class="llb">{img}</span>' if sp.get('logo_badge') else img
    gh, gb = G[sp.get('guarantee', 'B').upper()]
    lines = f"<p>{e(sp['saw_l1'])}</p><p>{e(sp['saw_l2'])}</p><p class=\"turn\">{e(sp['saw_turn'])}</p>"
    out = open(os.path.join(HERE, 'template.html'), encoding='utf-8').read()
    for k, v in {'COMPANY': co, 'PREPARED': prep, 'CO_MARK': mark, 'DOMAIN': e(sp['domain']), 'SHOT': sp['shot'],
                 'COVER_LINE': e(sp.get('cover_line') or f"20% more revenue in 60 days for {sp['company']}, from the customers you already have."),
                 'SAW_HEAD': e(sp['saw_head']), 'SAW_LINES': lines, 'AUDIT_TAIL': e(sp.get('audit_tail', '')),
                 'PROOF_HEAD': e(sp.get('proof_head') or f"{sp['company']} would not be the first."),
                 'G_HEAD': gh, 'G_BODY': gb.format(co=co), 'LOGOS': LOGOS,
                 'TALK_TEXT': e(sp.get('talk_text') or f"Thirty minutes with Umesh: he walks you through the audit for {sp['company']}, the dormant segments we would start with and what the first 60 days look like."),
                 'BOOKING_URL': sp.get('booking_url') or BOOK}.items():
        out = out.replace('{{' + k + '}}', v)
    assert '{{' not in out, path
    d = os.path.join(ROOT, sp['slug']); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, 'index.html'), 'w', encoding='utf-8').write(out)
    print('built', sp['slug'], '· guarantee', sp.get('guarantee', 'B').upper())
