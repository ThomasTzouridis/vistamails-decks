# -*- coding: utf-8 -*-
"""VistaMails deck poller. Runs on the hub server automation-hub-01 (mac-hub job vista_decks, every 30 min), checkout ~/vm-decks.
Every live VistaMails HeyReach campaign "VistaMails | <Sender> | 1A|1B" (workspace key HEYREACH_VISTAMAILS_API_KEY, found via
/campaign/GetAll, DRAFT and CANCELED skipped, Klaviyo campaigns skipped because they send no deck) -> leads who connected ->
one deck per lead slug, EXACTLY the approved layout (template.html + build.py, no model call, only the lead slots change:
company, first and last name, domain, screenshot, logo, guarantee A for copy 1A and B for copy 1B) -> git push -> live at
https://vistamails-cases.com/<slug>/ (GitHub Pages). 404.html is the generic fallback for every slug not built yet, so a lead is
never sent a dead link.
Lead facts: HeyReach list custom fields normalizedcompanyname and presentation (the URL message 2 sends, slug = last path
segment), first and last name from the LinkedIn profile, the website from Supabase ocean_leads (by LinkedIn handle, domain must
share a word with the company name, else no deck and an alert). Screenshot: assets/shots/<slug>.jpg when it exists (1500 were
taken in advance), else tools/shot.py. Logo: tools/logo.py (optional, no usable logo = company name in text).
Rules: a slug is built once; infrastructure failures (site down, shot failed) retry on later runs, max 3; a lead without a
usable website gets no deck and one Slack DM; the presentation field is written only when it is missing or names another slug.
Control check every run: the deck URL HeyReach sends must end in the lead's slug and answer 200 once built, otherwise a DM.
The Presentation Log sheet is owned by mac-hub hr_track.py (clients/vistamails.json), this poller never writes a sheet.
  python3 _src/auto/vm_poll.py            real run
  python3 _src/auto/vm_poll.py --dry      list who is connected and what would be built, change nothing
  python3 _src/auto/vm_poll.py --slug x   build one slug (must be connected in HeyReach, or add --force)
"""
import os, sys, re, json, time, shutil, subprocess, urllib.request, urllib.error, datetime, argparse, signal
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.dirname(HERE); ROOT = os.path.dirname(SRC)
HOME = os.path.expanduser('~')
AIOS = os.path.join(HOME, 'Desktop', 'AIOS')
B = 'https://api.heyreach.io/api/public'
PRIV = os.path.join(ROOT, '_private')
STATE = os.path.join(PRIV, 'vm_poll_state.json')
LOCK = os.path.join(PRIV, 'vm_poll.lock')
LEADMAP = os.path.join(PRIV, 'vm_leads.json')     # slug -> company for every lead in the lists (404 fallback)
CAMP_RE = re.compile(r'^\s*VistaMails\s*\|\s*(.+?)\s*\|\s*(1A|1B)\s*$', re.I)
CONNECTED = re.compile(r'(?i)accept|^connected|already')
NOT_CONNECTED = {'None', 'ConnectionSent', 'ConnectionRequested', 'Pending', ''}
SKIP_STATUS = {'DRAFT', 'CANCELED', 'CANCELLED'}
MAX_ATTEMPTS = 3
PER_RUN = 40
SITE = 'https://vistamails-cases.com/'
ALT_SITE = 'https://thomastzouridis.github.io/vistamails-decks/'
BG = '#041010'
BOOK = 'https://calendly.com/umesh-gps/vistamails-email-marketing-discovery-call'
FREE = {'gmail', 'yahoo', 'hotmail', 'outlook', 'icloud', 'me', 'live', 'aol', 'gmx', 'web', 'proton', 'protonmail', 'mail', 'yandex', 'qq'}
GENERIC = {'inc', 'ltd', 'llc', 'gmbh', 'plc', 'sas', 'spa', 'nv', 'bv', 'ag', 'sa', 'se', 'co', 'kg', 'srl', 'corp', 'corporation', 'company',
           'the', 'and', 'group', 'holding', 'holdings', 'international', 'global', 'shop', 'store', 'online', 'brands', 'brand', 'official',
           'cosmetics', 'fashion', 'apparel', 'studio', 'labs', 'lab', 'nutrition', 'health', 'beauty', 'home', 'living', 'design', 'my', 'your'}
BROKEN_NAME = {'my', 'the', 'a', 'an', 'our', 'your', 'we', 'dr', 'dr.'}
KEY = ''
PY = sys.executable


def now(): return datetime.datetime.now().isoformat(timespec='seconds')


def say(*a): print(now(), *a, flush=True)


def env(k):
    kv = dict(re.findall(r'^([A-Z0-9_]+)=(.*)$', open(os.path.join(AIOS, '.env'), encoding='utf-8').read(), re.M))
    return kv.get(k, '').strip().strip('"').strip("'")


def alert(text):
    """DM to Thomas (Slack user U09HBPS205B), prefixed 'VistaMails decks:'."""
    say('ALERT', text)
    try:
        tok = env('SLACK_USER_TOKEN')
        r = urllib.request.Request('https://slack.com/api/chat.postMessage', json.dumps({'channel': 'U09HBPS205B', 'text': 'VistaMails decks: ' + text}).encode(),
                                   {'Content-Type': 'application/json; charset=utf-8', 'Authorization': 'Bearer ' + tok})
        urllib.request.urlopen(r, timeout=20).read()
    except Exception as e:
        say('slack failed', e)


def hr(path, body=None, method='POST'):
    for a in range(6):
        try:
            r = urllib.request.Request(B + path, json.dumps(body).encode() if body is not None else None,
                                       {'X-API-KEY': KEY, 'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}, method=method)
            t = urllib.request.urlopen(r, timeout=60).read().decode()
            return json.loads(t) if t.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and a < 5: time.sleep(20 * (a + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if a < 5: time.sleep(10 * (a + 1)); continue
            raise


def pages(path, body):
    off = 0
    while True:
        d = hr(path, dict(body, offset=off, limit=100))
        items = d.get('items') or []
        for i in items: yield i
        if len(items) < 100: return
        off += 100


def live_code(slug):
    """200 = a VistaMails deck answers at the URL HeyReach sends. 0 = the custom domain does not answer at all (then the github.io mirror
    is checked and 200 there is reported as 200, the domain problem is flagged separately)."""
    for base in (SITE, ALT_SITE):
        try:
            r = urllib.request.urlopen(urllib.request.Request(base + slug + '/', headers={'User-Agent': 'Mozilla/5.0', 'Cache-Control': 'no-cache'}), timeout=15)
            page = r.read().decode('utf-8', 'replace').lower()
            return 200 if r.status == 200 and 'vistamails' in page else r.status
        except urllib.error.HTTPError as e: return e.code
        except Exception:
            if base == SITE: continue
            return 0
    return 0


def domain_live():
    try:
        urllib.request.urlopen(urllib.request.Request(SITE, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15); return True
    except urllib.error.HTTPError: return True
    except Exception: return False


def git(*args, check=True):
    r = subprocess.run(['git'] + list(args), cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
    if check and r.returncode: raise RuntimeError('git %s: %s' % (' '.join(args), (r.stderr or r.stdout)[-400:]))
    return r.stdout


def lid_of(url):
    m = re.search(r'linkedin\.com/in/([^/?#]+)', url or '', re.I)
    return urllib.request.unquote(m.group(1)).lower() if m else ''


def slugify(s, n=40):
    s = re.sub(r'[^a-z0-9]+', '-', (s or '').lower()).strip('-')
    return s[:n].strip('-')


def host_of(w):
    h = re.sub(r'^https?://', '', (w or '').strip().lower()).split('/')[0].split(':')[0].split('?')[0]
    return h[4:] if h.startswith('www.') else h


def site_matches(company, host):
    """True when the domain and the company name share a real word, so a wrong record never becomes a deck."""
    labels = [x for x in host.split('.')[:-1] if x]
    dom = ''.join(labels).replace('-', '')
    comp = re.sub(r'[^a-z0-9 ]', ' ', (company or '').lower())
    toks = [t for t in comp.split() if len(t) >= 3 and t not in GENERIC]
    if any(t in dom for t in toks): return True
    flat = comp.replace(' ', '')
    return any(len(x) >= 4 and x.replace('-', '') in flat for x in labels)


# ---------- Supabase (ocean_leads) ----------
_SB = None


def sb():
    global _SB
    if _SB is None:
        try:
            sys.path.insert(0, os.path.join(AIOS, 'Internal Clay', 'lead-database'))
            import db
            _SB = db.connect()
        except Exception as e:
            say('supabase unavailable:', repr(e)); _SB = False
    return _SB or None


def sb_row(handle):
    """(company, [website candidates]) from ocean_leads for a LinkedIn handle, ('', []) when unknown."""
    c = sb()
    if not c or not handle: return '', []
    try:
        cur = c.cursor()
        cur.execute("select company, domain, companywebsite, sheet_company_website, company_email_domain, email, person_email from ocean_leads "
                    "where substring(lower(person_linkedin) from 'linkedin\\.com/in/([^/?#]+)') = %s limit 5", (handle,))
        comp, cands = '', []
        for r in cur.fetchall():
            comp = comp or (r[0] or '').strip()
            for w in r[1:5]:
                h = host_of(w)
                if h and '.' in h and h not in cands: cands.append(h)
            for em in r[5:7]:
                em = (em or '').strip().lower()
                d = em.split('@')[-1] if '@' in em else ''
                if d and d.split('.')[0] not in FREE and d not in cands: cands.append(d)
        return comp, cands
    except Exception as e:
        say('supabase query failed:', repr(e))
        try: c.rollback()
        except Exception: pass
        return '', []


# ---------- HeyReach ----------
def campaigns():
    """{campaign id: {'name','sender','copy' (A|B),'list'}} for every live 'VistaMails | <Sender> | 1A|1B' campaign."""
    out = {}
    for c in pages('/campaign/GetAll', {}):
        if (c.get('status') or '').upper() in SKIP_STATUS: continue
        m = CAMP_RE.match(c.get('name') or '')
        if not m: continue
        out[c['id']] = {'name': c.get('name') or '', 'sender': m.group(1), 'copy': m.group(2).upper()[-1], 'list': c.get('linkedInUserListId'),
                        'status': c.get('status') or ''}
    return out


def connected_leads(camps):
    """{linkedin id: facts} for every lead in the live campaigns whose connection is accepted or pre-existing."""
    out, seen = {}, {}
    for cid, c in camps.items():
        for i in pages('/campaign/GetLeadsFromCampaign', {'campaignId': cid}):
            st = i.get('leadConnectionStatus') or 'None'
            seen[st] = seen.get(st, 0) + 1
            pr = i.get('linkedInUserProfile') or {}
            lid = lid_of(pr.get('profileUrl'))
            if lid and st not in NOT_CONNECTED and CONNECTED.search(st):
                out[lid] = {'status': st, 'campaign': cid, 'campaign_name': c['name'], 'sender': i.get('linkedInSenderFullName') or c['sender'],
                            'copy': c['copy'], 'list': c['list'], 'url': pr.get('profileUrl') or '',
                            'first': (pr.get('firstName') or '').strip(), 'last': (pr.get('lastName') or '').strip(),
                            'li_company': (pr.get('companyName') or '').strip(), 'msg_status': i.get('leadMessageStatus') or ''}
    say('HeyReach connection statuses:', seen)
    return out


def list_facts(list_id, allmap):
    """linkedin id -> {company (normalizedcompanyname), link (presentation), slug, first, last, url}; fills allmap slug -> company."""
    out = {}
    for i in pages('/list/GetLeadsFromList', {'listId': list_id}):
        lid = lid_of(i.get('profileUrl'))
        if not lid: continue
        cf = {f.get('name'): (f.get('value') or '').strip() for f in (i.get('customFields') or []) if f.get('name')}
        link = cf.get('presentation', '')
        slug = link.rstrip('/').split('/')[-1].lower() if link else ''
        co = cf.get('normalizedcompanyname') or ''
        if slug and co: allmap.setdefault(slug, co)
        out[lid] = {'company': co, 'link': link, 'slug': slug, 'first': (i.get('firstName') or '').strip(), 'last': (i.get('lastName') or '').strip(),
                    'url': i.get('profileUrl') or ''}
    return out


def set_presentation(lead, link):
    """Writes the presentation custom field on the campaign lead and on the list lead (Symonds pattern, PATCH UpdateLeadCustomFields)."""
    body = {'leadMemberIdOrUrl': lead['url'], 'customFields': {'presentation': link}}
    hr('/campaign/UpdateLeadCustomFields/campaigns/%d/leads/custom-fields' % lead['campaign'], body, 'PATCH')
    try:
        if lead.get('list'): hr('/list/UpdateLeadCustomFields/lists/%d/leads/custom-fields' % lead['list'], body, 'PATCH')
    except Exception as e:
        say('list field update failed for %s (campaign lead is set): %s' % (lead['url'], e))


# ---------- deck ----------
def slug_files(slug):
    out = [slug + '/index.html', '_src/specs/' + slug + '.json', 'assets/shots/' + slug + '.jpg', 'assets/leadlogos/' + slug + '.png']
    return [f for f in out if os.path.exists(os.path.join(ROOT, f))]


def run(cmd, timeout, cwd=ROOT):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout,
                       env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    return p.returncode, (p.stdout + p.stderr)


def take_shot(slug, domain):
    dst = os.path.join(ROOT, 'assets', 'shots', slug + '.jpg')
    if os.path.exists(dst): return True, 'shot existed'
    tmp = os.path.join(HERE, 'runs', slug)
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp, exist_ok=True)
    rc, out = run([PY, os.path.join(SRC, 'tools', 'shot.py'), slug, tmp, 'https://' + domain], 240)
    src = os.path.join(tmp, slug + '_1.jpg')
    if os.path.exists(src):
        shutil.copyfile(src, dst); shutil.rmtree(tmp, ignore_errors=True); return True, 'shot taken'
    return False, 'shot failed: ' + out[-300:]


def build(slug, lead, state):
    """lead: company, first, last, domain, copy. True when the deck is built and committed."""
    st = state.setdefault(slug, {'status': 'new', 'attempts': 0})
    st['attempts'] += 1
    t0 = time.time()
    ok, note = take_shot(slug, lead['domain'])
    if not ok:
        if st['attempts'] >= MAX_ATTEMPTS:
            st.update(status='failed', error=note[:300], at=now())
            alert('deck for %s (/%s/, %s) failed %d times: %s. The fallback page stays.' % (lead['company'], slug, lead['domain'], st['attempts'], note[-200:]))
        else:
            st.update(status='retry', error=note[:300], at=now()); say('retry next run:', slug, note[-200:])
        return False
    spec_path = os.path.join(SRC, 'specs', slug + '.json')
    spec = {'slug': slug, 'company': lead['company'], 'first_name': lead['first'], 'last_name': lead['last'], 'domain': lead['domain'],
            'shot': slug + '.jpg', 'guarantee': lead['copy']}
    json.dump(spec, open(spec_path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    # logo: optional, never blocks the deck
    try:
        rc, out = run([PY, os.path.join(SRC, 'tools', 'logo.py'), slug, lead['company'], 'https://' + lead['domain'], '--bg', BG, '--out', 'assets/leadlogos',
                       '--spec', spec_path, '--badge-key', 'logo_badge', '--on-none', 'remove'], 300)
        logo_note = next((l for l in out.splitlines() if l.startswith('RESULT')), 'logo tool gave no RESULT line')
    except Exception as e:
        logo_note = 'logo tool crashed: %s' % str(e)[-150:]
        sp = json.load(open(spec_path, encoding='utf-8')); sp.pop('logo', None); sp.pop('logo_badge', None)
        json.dump(sp, open(spec_path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    rc, out = run([PY, os.path.join(SRC, 'build.py'), spec_path], 120, cwd=SRC)
    if rc and 'logo' in out:   # the build guard refused the logo: drop it and build with the company name in text
        sp = json.load(open(spec_path, encoding='utf-8')); sp.pop('logo', None); sp.pop('logo_badge', None)
        json.dump(sp, open(spec_path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        logo_note += ' | logo refused by build guard, deck without logo'
        rc, out = run([PY, os.path.join(SRC, 'build.py'), spec_path], 120, cwd=SRC)
    if rc == 0 and os.path.exists(os.path.join(ROOT, slug, 'index.html')):
        git('add', '--', *slug_files(slug))
        git('commit', '-q', '-m', 'deck %s (auto)\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>' % slug)
        st.update(status='built', at=now(), built_ts=time.time(), secs=int(time.time() - t0), note=(note + ' | ' + logo_note)[:300], company=lead['company'], domain=lead['domain'])
        say('built', slug, lead['company'], lead['domain'], 'guarantee', lead['copy'], '|', logo_note[:120])
        return True
    shutil.rmtree(os.path.join(ROOT, slug), ignore_errors=True)
    try: os.remove(spec_path)
    except OSError: pass
    git('checkout', '--', '.', check=False)
    if st['attempts'] >= MAX_ATTEMPTS:
        st.update(status='failed', error=out[-300:], at=now())
        alert('deck for %s (/%s/) failed to build %d times: %s' % (lead['company'], slug, st['attempts'], out[-250:]))
    else:
        st.update(status='retry', error=out[-300:], at=now()); say('build failed, retry next run:', slug, out[-200:])
    return False


def build_fallback(allmap):
    """404.html: GitHub Pages serves it for every slug without a folder. Company names only (public repo), booking link tracked."""
    m = {k: v for k, v in sorted(allmap.items()) if k and v}
    js = json.dumps(m, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex"><title>VistaMails</title>\n'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Manrope:wght@500;700&display=swap">\n'
            '<style>html,body{height:100%;margin:0;background:#041010;color:#fff;font-family:Manrope,system-ui,sans-serif}'
            'body{display:flex;align-items:center;justify-content:center;text-align:center;padding:24px}a{color:#1dd27f}'
            'h1{font-size:28px;margin:0 0 12px}p{color:#9fb0aa;margin:0 0 20px;line-height:1.5;max-width:520px}'
            '.b{display:inline-block;background:#1dd27f;color:#041010;font-weight:700;text-decoration:none;padding:12px 22px;border-radius:999px}</style></head>\n'
            '<body><div><h1>The presentation for <span id="co">your company</span> is still being prepared.</h1>'
            '<p>Umesh is putting it together right now. In the meantime, you can book a call directly.</p>'
            '<a class="b" href="' + BOOK + '">Book a call with Umesh</a>'
            '<p style="margin-top:20px"><a href="https://thevistamails.com/">thevistamails.com</a></p></div>\n'
            '<script>(()=>{const M=' + js + ';const s=(location.pathname.split("/").filter(Boolean).slice(-1)[0]||"").toLowerCase();'
            'const c=M[s];if(c){document.getElementById("co").textContent=c;document.title=c+" \\u00d7 VistaMails"}})();</script>\n</body></html>\n')
    p = os.path.join(ROOT, '404.html')
    old = open(p, encoding='utf-8').read() if os.path.exists(p) else ''
    if old != page:
        open(p, 'w', encoding='utf-8', newline='\n').write(page)
        git('add', '--', '404.html'); git('commit', '-q', '-m', '404 fallback: %d companies (auto)\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>' % len(m))
        say('404.html rebuilt with', len(m), 'companies'); return True
    return False


def push():
    for a in range(3):
        try:
            git('pull', '--rebase', '--autostash', '-q'); git('push', '-q'); return True
        except RuntimeError as e:
            say('push failed', a, e); time.sleep(15)
    return False


def resolve(lid, info, f, state):
    """Merge HeyReach facts and Supabase into one buildable lead or return (None, reason)."""
    company = f.get('company') or ''
    sb_company, cands = sb_row(lid)
    if not company or company.lower().strip('. ') in BROKEN_NAME or len(company) < 3:
        if sb_company:
            state.setdefault('_notes', {})[lid] = 'normalizedcompanyname "%s" unusable, deck uses Supabase company "%s" (message 2 still sends "%s")' % (company, sb_company, company)
            company = sb_company
        elif not company:
            return None, 'no company name (list field normalizedcompanyname empty, Supabase unknown)'
    domain = next((h for h in cands if site_matches(company, h)), '')
    if not domain and cands and sb_company and site_matches(sb_company, cands[0]) and site_matches(company, cands[0]):
        domain = cands[0]
    if not domain:
        return None, 'no website: Supabase %s for company "%s"' % (('candidates %s do not match the name' % cands) if cands else 'has no row for the LinkedIn handle', company)
    slug = f.get('slug') or slugify(company)
    if not slug: return None, 'no slug'
    return {'slug': slug, 'company': company, 'first': f.get('first') or info['first'], 'last': f.get('last') or info['last'], 'domain': domain,
            'copy': info['copy'], 'link': f.get('link', ''), 'url': f.get('url') or info['url'], 'campaign': info['campaign'], 'list': info['list'],
            'sender': info['sender'], 'status': info['status'], 'name': ('%s %s' % (f.get('first') or info['first'], f.get('last') or info['last'])).strip()}, ''


def lock_held():
    """True while another poller process holds the lock (pid alive); a lock left by a killed process is ignored."""
    if not os.path.exists(LOCK): return False
    try: pid = int(open(LOCK).read().split()[0])
    except Exception: pid = 0
    if pid:
        try: os.kill(pid, 0); return True
        except OSError: return False
    return time.time() - os.path.getmtime(LOCK) < 4 * 3600


def main():
    global KEY
    ap = argparse.ArgumentParser(); ap.add_argument('--dry', action='store_true'); ap.add_argument('--slug'); ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    if lock_held(): say('locked, previous run active'); return
    os.makedirs(PRIV, exist_ok=True)
    open(LOCK, 'w').write('%d %s' % (os.getpid(), now()))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # a scheduler restart (deploy.sh) must not leave a stale lock
    try:
        KEY = env('HEYREACH_VISTAMAILS_API_KEY')
        if not KEY: raise RuntimeError('HEYREACH_VISTAMAILS_API_KEY missing in ~/Desktop/AIOS/.env')
        git('pull', '--rebase', '--autostash', '-q')
        state = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {}
        allmap = json.load(open(LEADMAP, encoding='utf-8')) if os.path.exists(LEADMAP) else {}
        camps = campaigns()
        say('live VistaMails deck campaigns:', {k: v['name'] for k, v in camps.items()} or 'none')
        conn = connected_leads(camps) if camps else {}
        say('connected leads in HeyReach:', len(conn))
        facts = {}
        for cid, c in camps.items():
            if not c['list']: continue
            try: facts.update(list_facts(c['list'], allmap))
            except Exception as e: say('list facts failed', cid, e)
        json.dump(allmap, open(LEADMAP, 'w', encoding='utf-8'), indent=0, ensure_ascii=False)
        cs = state.setdefault('_conn', {})
        todo, unmatched = {}, []
        for lid, info in conn.items():
            lead, why = resolve(lid, info, facts.get(lid) or {}, state)
            c = cs.setdefault(lid, {'first_ts': time.time(), 'first_seen': now()})
            if not lead:
                c.update(name=('%s %s' % (info['first'], info['last'])).strip(), company=(facts.get(lid) or {}).get('company') or info['li_company'], sender=info['sender'],
                         status=info['status'], slug=(facts.get(lid) or {}).get('slug', ''), link=(facts.get(lid) or {}).get('link', ''), why=why)
                unmatched.append((lid, c['name'], c['company'], why)); continue
            c.update(name=lead['name'], company=lead['company'], sender=lead['sender'], campaign=lead['campaign'], status=lead['status'], slug=lead['slug'],
                     link=lead['link'], domain=lead['domain'], copy=lead['copy'], why='')
            todo.setdefault(lead['slug'], lead)
        if a.slug:
            if a.slug in todo or a.force:
                lead = todo.get(a.slug)
                if not lead: say('slug not connected and not resolvable, nothing to force'); return
                todo = {a.slug: lead}
            else: say('slug not connected (use --force)'); return
        if unmatched:
            known = state.setdefault('_unmatched', [])
            new = [u for u in unmatched if u[0] not in known]
            if new:
                alert('%d connected leads cannot get a deck, the fallback page stays: %s' % (len(new), '; '.join('%s (%s): %s' % (n, co, w) for _l, n, co, w in new[:6])))
                known += [u[0] for u in new]
        pending = [s for s in todo if state.get(s, {}).get('status') in (None, 'new', 'retry') and not os.path.exists(os.path.join(ROOT, s, 'index.html'))]
        say('slugs connected:', len(todo), 'to build:', len(pending), pending[:20])
        if a.dry:
            for lid, c in cs.items(): print(c.get('company'), '|', c.get('slug'), '|', c.get('domain'), '|', c.get('copy'), '|', c.get('link'), '|', c.get('why') or 'ok', '|', c['first_seen'])
            return
        built = 0
        for slug in pending[:PER_RUN]:
            try:
                if build(slug, todo[slug], state): built += 1
            except Exception as e:
                st = state.setdefault(slug, {'attempts': 0}); st['attempts'] = st.get('attempts', 0) + 1
                st.update(status='retry' if st['attempts'] < MAX_ATTEMPTS else 'failed', error=str(e)[-200:])
                say('error', slug, e)
                git('checkout', '--', '.', check=False)
                if st['status'] == 'failed': alert('deck for %s (/%s/) crashed %d times: %s' % (todo[slug]['company'], slug, MAX_ATTEMPTS, str(e)[-200:]))
            json.dump(state, open(STATE, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        changed = build_fallback(allmap) or built
        ahead = git('rev-list', '--count', '@{u}..HEAD', check=False).strip()
        if (changed or ahead not in ('', '0')) and not push():
            alert('git push FAILED after building %d decks, they are committed locally and go out on the next run' % built)
        # presentation field: write it only when it is missing or names another slug
        for slug, lead in todo.items():
            want = SITE + slug + '/'
            if lead['link'] and lead['link'].rstrip('/').split('/')[-1].lower() == slug: continue
            if state.get(slug, {}).get('status') != 'built': continue
            try:
                set_presentation(lead, want); cs[next(l for l, c in cs.items() if c.get('slug') == slug)]['link'] = want
                say('presentation field set', slug, want)
            except Exception as e:
                say('field write failed', slug, e)
        # control check: every connected lead's deck must be live and must be the URL HeyReach sends
        dom_ok = domain_live()
        if not dom_ok and not state.get('_domain_flagged'):
            alert('vistamails-cases.com does not answer (GitHub Pages custom domain or certificate). Decks are reachable on the github.io mirror only.')
            state['_domain_flagged'] = now()
        elif dom_ok: state.pop('_domain_flagged', None)
        done = {}
        for lid, c in cs.items():
            if lid not in conn: continue
            if c.get('why'): continue
            if c['slug'] not in done: done[c['slug']] = live_code(c['slug'])
            c['live'] = done[c['slug']]
            st = state.get(c['slug'], {})
            link_slug = (c.get('link') or '').rstrip('/').split('/')[-1].lower()
            age = (time.time() - c['first_ts']) / 60
            if c.get('link') and link_slug != c['slug']: chk = 'URL MISMATCH: HeyReach sends /%s/, slug is /%s/' % (link_slug, c['slug'])
            elif not c.get('link'): chk = 'NO presentation FIELD IN HEYREACH'
            elif c['live'] == 200: chk = 'OK'
            elif st.get('status') == 'failed': chk = 'DECK FAILED, fallback page is shown'
            elif st.get('status') == 'built': chk = 'BUILT BUT NOT LIVE YET' if (time.time() - st.get('built_ts', 0)) < 1800 else 'BUILT BUT NOT LIVE, CHECK PAGES'
            else: chk = 'BUILDING' if age < 90 else 'NO DECK %d min after connect' % age
            c['check'] = chk
            if chk in ('OK', 'BUILDING', 'BUILT BUT NOT LIVE YET'): continue
            kf = lid + '|' + chk[:20]
            if kf not in state.setdefault('_flagged', []):
                state['_flagged'].append(kf); alert('control check: %s (%s, /%s/): %s' % (c['name'], c['company'], c['slug'], chk))
        json.dump(state, open(STATE, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        oks = sum(1 for c in cs.values() if c.get('check') == 'OK')
        say('decks live for %d of %d connected leads; built this run: %d' % (oks, len(conn), built))
        if len(pending) > PER_RUN: say('%d more waiting for the next run' % (len(pending) - PER_RUN))
    finally:
        try: os.remove(LOCK)
        except OSError: pass


if __name__ == '__main__':
    try: main()
    except Exception as e:
        alert('poller crashed: %s' % str(e)[-300:]); raise
