# -*- coding: utf-8 -*-
"""VistaMails tracking: Presentation Log, copy docs, Calendly bookings, Meetings tab, open rate. Runs on the Mac (mac-hub job vista_track,
every 4 h), checkout ~/vm-decks. One-to-one the craze&friends model (cf_track.py) plus the Symonds Meetings model (sy_track.py):
1. Deck events: every deck (template.html, before </body>) posts open / slide / video / book / ping / leave beacons to mac-hub
   (/webhook/vm-deck-track), which appends them to ~/Desktop/AIOS/automations/mac-hub/logs/events.jsonl with the visitor IP. Read
   incrementally (byte offset in _private/vm_track_state.json), aggregated per slug and per session; bots / link scanners and sessions from
   NOT_COUNTED_CC never count. -> Presentation Log tracking block (after the manual block, which is never touched).
2. Presentation Log (sheet "VistaMails | Meetings & Tracking"): one row per lead who is CONNECTED in the 16 live campaigns
   "VistaMails | <Sender> | 1A / 1B" (already connected or connected back), keyed by LinkedIn id. Auto block rewritten every run, manual block
   moved with the lead, never touched. Facts from HeyReach (statuses, custom fields normalizedcompanyname / presentation), own connected
   stamp (message 1 is due 3 h after the connection check, message 2 with the deck 4 days after message 1).
3. Copy docs: one Google Doc per copy (1A, 1B, Klaviyo Campaign 1, Klaviyo Campaign 2), built from the HeyReach sequences in the exact
   format of the craze&friends doc "Messages Craze & Friends" (normal text, bold message lines, one empty line between paragraphs and
   messages, "Examples for Presentation" heading), rebuilt only when a sequence changes, linked in the Copy tab column B.
4. Meetings tab (the craze&friends layout, 14 columns): a meeting is (a) a booking on our exclusive Calendly event type
   VistaMails Email Marketing Discovery Call (calendly.com/umesh-gps/vistamails-email-marketing-discovery-call, Umesh's other event types are
   his own and skipped), matched to THE LEAD by the 7 craze&friends rules (resolve()), (b) a HeyReach tag containing "meeting" on the lead,
   (c) a date typed into Presentation Log "Meeting booked date". One row per meeting, enriched (email, website, LinkedIn, company LinkedIn,
   phone via HeyReach / Supabase / Prospeo with retry), the lead stopped in its campaign, tagged "Meeting booked", Supabase
   ocean_leads.mailvista_status = 'meeting booked'. Slack #meeting-booked-notifier: Calendly bookings are posted by the booking-tracker
   (Vercel) already, so only tag / typed meetings are posted from here.
5. Performance tab column C (presentation open rate per messaged lead) per sender and Total; B, D:F come from mac-hub hr_perf.py
   (job vista_perf daily 04:00, and right after a new meeting).
Self-check: open issues DM Thomas (NEW / STILL OPEN / resolved), a crash DMs at most once every 20 h. No Status tab (Thomas 2026-10-17).
  python3 _src/auto/vm_track.py
"""
import os, sys, re, json, time, datetime, difflib, hashlib, unicodedata, traceback, urllib.request, urllib.parse, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.dirname(HERE); ROOT = os.path.dirname(SRC)
HOME = os.path.expanduser('~')
HUB = os.path.join(HOME, 'Desktop', 'AIOS', 'automations', 'mac-hub')
EVENTS = os.path.join(HUB, 'logs', 'events.jsonl')
STATE = os.path.join(ROOT, '_private', 'vm_track_state.json')
CRASH = os.path.join(ROOT, '_private', 'vm_track_crash.json')
HR_CACHE = os.path.join(ROOT, '_private', 'vm_hr_leads.json')   # HeyReach lead facts of every campaign, refreshed every 6 h
MEET_ACC = os.path.join(ROOT, '_private', 'vm_meet_accounts.json')   # {lead id: HeyReach account id} of every Meetings lead, read by jobs/vista_perf.py
B = 'https://api.heyreach.io/api/public'
PATH = 'vm-deck-track'
SITE = 'https://thomastzouridis.github.io/vistamails-decks/'
SHEET = '1j6zKhSLC46BIm-oWQmYd761nQuHsVili-na1xGKbQfE'   # "VistaMails | Meetings & Tracking"
TAB = 'Presentation Log'
SENDERS = {'Nischaya Basnet': 239349, 'Samir Shrestha': 239352, 'Safal Poudel': 239353, 'Umesh Prasad Pandey': 239355, 'Sushan Phagami': 239356,
           'Prajwol Bohara': 241564, 'Shreya Joshi': 241565, 'Shubhank Bhattarai': 242690}
# live campaigns (started 2026-10-19): id -> (copy, sender)
LIVE = {665669: ('1A', 'Prajwol Bohara'), 665671: ('1B', 'Prajwol Bohara'), 665672: ('1A', 'Sushan Phagami'), 665673: ('1B', 'Sushan Phagami'),
        665674: ('1A', 'Samir Shrestha'), 665675: ('1B', 'Samir Shrestha'), 665676: ('1A', 'Nischaya Basnet'), 665677: ('1B', 'Nischaya Basnet'),
        665678: ('1A', 'Umesh Prasad Pandey'), 665679: ('1B', 'Umesh Prasad Pandey'), 665680: ('1A', 'Shubhank Bhattarai'), 665681: ('1B', 'Shubhank Bhattarai'),
        665682: ('1A', 'Shreya Joshi'), 665683: ('1B', 'Shreya Joshi'), 665684: ('1A', 'Safal Poudel'), 665685: ('1B', 'Safal Poudel')}
# paused Klaviyo campaigns (2026-09): no decks, but their leads can still book
KLAVIYO = {598361: ('Klaviyo Campaign 1', 'Umesh Prasad Pandey'), 598362: ('Klaviyo Campaign 1', 'Nischaya Basnet'), 598363: ('Klaviyo Campaign 1', 'Safal Poudel'),
           598364: ('Klaviyo Campaign 1', 'Samir Shrestha'), 598365: ('Klaviyo Campaign 1', 'Sushan Phagami'), 598366: ('Klaviyo Campaign 1', 'Prajwol Bohara'),
           598367: ('Klaviyo Campaign 1', 'Shubhank Bhattarai'), 598368: ('Klaviyo Campaign 1', 'Shreya Joshi'),
           598534: ('Klaviyo Campaign 2', 'Umesh Prasad Pandey'), 598535: ('Klaviyo Campaign 2', 'Nischaya Basnet'), 598536: ('Klaviyo Campaign 2', 'Safal Poudel'),
           598537: ('Klaviyo Campaign 2', 'Samir Shrestha'), 598538: ('Klaviyo Campaign 2', 'Sushan Phagami'), 598539: ('Klaviyo Campaign 2', 'Prajwol Bohara'),
           598540: ('Klaviyo Campaign 2', 'Shubhank Bhattarai'), 598541: ('Klaviyo Campaign 2', 'Shreya Joshi')}
CAMPAIGNS = dict(LIVE); CAMPAIGNS.update(KLAVIYO)
CAMPAIGNS_ALL = list(CAMPAIGNS)
COPIES = [('1A', [c for c, (cp, s) in LIVE.items() if cp == '1A']), ('1B', [c for c, (cp, s) in LIVE.items() if cp == '1B']),
          ('Klaviyo Campaign 1', [c for c, (cp, s) in KLAVIYO.items() if cp == 'Klaviyo Campaign 1']),
          ('Klaviyo Campaign 2', [c for c, (cp, s) in KLAVIYO.items() if cp == 'Klaviyo Campaign 2'])]
CAL_USER = 'https://api.calendly.com/users/c6ea9b6b-4f66-4c29-8450-2462ee56d2ef'   # umesh-gps (the PAT has no users:read, so the URI is fixed)
CAL_EVENT_TYPE = '827bbde0-a5da-4d5a-9604-e73b1d8de857'   # VistaMails Email Marketing Discovery Call, OUR exclusive link (Thomas 2026-09-13)
AUTO_HDR = ['Lead', 'Company', 'Sender', 'Campaign', 'Copy', 'LinkedIn id', 'Connection status (HeyReach)', 'Connected', 'First seen connected',
            'Message 1 due (connect + 3 h)', 'Message 2 (deck) due (message 1 + 4 days)', 'Message status (HeyReach)', 'Replied (HeyReach)',
            'Campaign status (HeyReach)', 'Last action (HeyReach)', 'Company name (message 2)', 'Deck URL HeyReach sends', 'Deck slug', 'Live check', 'Check', 'Note or error']
MAN_HDR = ['Reply date', 'Reply summary', 'Interested', 'Meeting booked date', 'Showed up', 'Closed', 'Deal value', 'Notes']
TRACK_HDR = ['Deck opens', 'Deck sessions', 'First opened', 'Last opened', 'Deepest slide', 'Time on deck (s)', 'Videos played', 'Book clicks', 'Meeting booked (Calendly)', 'Opened from']
NA, NM = len(AUTO_HDR), len(MAN_HDR)
MEET_HDR = ['Lead Name', 'Email address', 'Website', 'Linkedin', 'Company Linkedin', 'Phone number (Whatsapp)', 'Event Date', 'Conversation', 'Outcome', '$ Collected',
            'Calendly invitee (auto key)', 'Booked by (if not the lead)', 'Matched by', 'Lead override (type the lead name, the row is then yours)']
MEET_HDR_LN = MEET_HDR[11:]
HOME_CC = 'NP'   # VistaMails sit in Nepal: opens from there are most likely the client, flagged in 'Opened from'
OUR_CC = {'NP', 'SI'}   # the client (Nepal) and Thomas (Slovenia): a booking from there that matches no lead is internal
NOT_COUNTED_CC = {'SI'}   # we sit in Celje, every deck session from Slovenia is ours and never counts
INTERNAL_DOMAINS = {'actiscale.com', 'actiscale.co', 'thevistamails.com', 'vistamails.com'}
TEAM = {norm_ for norm_ in ()}   # filled below (needs norm)
CONNECTED = re.compile(r'(?i)accept|^connected|already')
INACTIVE = {'Finished', 'Failed', 'Stopped', 'ManuallyStopped', 'Excluded', 'Canceled'}
BAD = ('DECK NOT LIVE', 'FAILED')
LINK_RE = re.compile(r'(?i)calendly\.com/umesh-gps')
DECK_RE = re.compile(r'(?i)vistamails-decks|vistamails-cases\.com')
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
FREE = {'gmail', 'googlemail', 'outlook', 'hotmail', 'live', 'yahoo', 'ymail', 'rocketmail', 'icloud', 'me', 'mac', 'gmx', 'web', 't-online', 'proton',
        'protonmail', 'pm', 'aol', 'msn', 'orange', 'wanadoo', 'free', 'sfr', 'laposte', 'yandex', 'mail', 'libero', 'virgilio', 'tiscali', 'bluewin',
        'telenet', 'skynet', 'ziggo', 'kpnmail', 'comcast', 'att', 'verizon', 'btinternet', 'sky', 'zoho', 'hey', 'fastmail', 'posteo', 'mailbox', 'tutanota', 'tuta'}
FREEMAIL = {'gmail.com', 'googlemail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'live.com', 'icloud.com', 'me.com', 'aol.com', 'proton.me',
            'protonmail.com', 'gmx.de', 'gmx.net', 'web.de', 'yandex.com', 'mail.com'}
PHONE_RETRY_DAYS = 30   # a Prospeo miss is retried after this many days (re-enrichment within 90 days is free, so a retry never double charges)
SLACK_BOOKING_CHANNEL = 'C0BQ7TM6QGL'   # #meeting-booked-notifier
COUNTRY = {'france': 'FR', 'germany': 'DE', 'deutschland': 'DE', 'united states': 'US', 'usa': 'US', 'united states of america': 'US', 'united kingdom': 'GB',
           'uk': 'GB', 'england': 'GB', 'scotland': 'GB', 'wales': 'GB', 'italy': 'IT', 'italia': 'IT', 'spain': 'ES', 'espana': 'ES', 'netherlands': 'NL',
           'the netherlands': 'NL', 'belgium': 'BE', 'switzerland': 'CH', 'schweiz': 'CH', 'austria': 'AT', 'osterreich': 'AT', 'sweden': 'SE', 'norway': 'NO',
           'denmark': 'DK', 'finland': 'FI', 'ireland': 'IE', 'portugal': 'PT', 'poland': 'PL', 'czechia': 'CZ', 'czech republic': 'CZ', 'hungary': 'HU',
           'greece': 'GR', 'romania': 'RO', 'croatia': 'HR', 'serbia': 'RS', 'slovenia': 'SI', 'canada': 'CA', 'australia': 'AU', 'new zealand': 'NZ',
           'mexico': 'MX', 'brazil': 'BR', 'japan': 'JP', 'united arab emirates': 'AE', 'israel': 'IL', 'turkey': 'TR', 'turkiye': 'TR', 'luxembourg': 'LU',
           'south africa': 'ZA', 'india': 'IN', 'singapore': 'SG', 'hong kong': 'HK', 'argentina': 'AR', 'chile': 'CL', 'colombia': 'CO', 'estonia': 'EE',
           'latvia': 'LV', 'lithuania': 'LT', 'slovakia': 'SK', 'bulgaria': 'BG', 'ukraine': 'UA', 'iceland': 'IS', 'malta': 'MT', 'cyprus': 'CY', 'nepal': 'NP'}
CITY = {'US': 'new york|los angeles|san francisco|chicago|boston|seattle|denver|austin|dallas|houston|miami|atlanta|phoenix|san diego|portland|washington|detroit|'
              'philadelphia|minneapolis|salt lake|las vegas|nashville|charlotte|orlando|tampa|san jose|sacramento|pittsburgh|cleveland|cincinnati|columbus|indianapolis|'
              'kansas city|st louis|milwaukee|raleigh|richmond|baltimore|new jersey|brooklyn|manhattan|silicon valley|bay area|california|texas|florida',
        'GB': 'london|manchester|birmingham|leeds|glasgow|edinburgh|bristol|liverpool|sheffield|nottingham|newcastle|cambridge|oxford|brighton|belfast|cardiff|leicester|southampton',
        'CA': 'toronto|vancouver|montreal|calgary|ottawa|edmonton|quebec|winnipeg', 'AU': 'sydney|melbourne|brisbane|perth|adelaide|gold coast|canberra', 'NZ': 'auckland|wellington|christchurch',
        'IE': 'dublin|cork|galway', 'FR': 'paris|lyon|marseille|bordeaux|lille|toulouse|nantes|nice|strasbourg|montpellier|rennes|grenoble|ile de france',
        'DE': 'berlin|munich|munchen|hamburg|frankfurt|cologne|koln|dusseldorf|stuttgart|leipzig|dresden|hannover|nuremberg|nurnberg|bremen|essen|dortmund|mannheim|karlsruhe|bonn|mainz|wiesbaden',
        'NL': 'amsterdam|rotterdam|utrecht|eindhoven|the hague|den haag|groningen', 'BE': 'brussels|bruxelles|antwerp|antwerpen|ghent|gent|leuven|liege',
        'CH': 'zurich|geneva|geneve|basel|bern|lausanne|lugano|winterthur|zug', 'AT': 'vienna|wien|graz|linz|salzburg|innsbruck', 'LU': 'luxembourg',
        'IT': 'milan|milano|rome|roma|turin|torino|florence|firenze|bologna|naples|napoli|venice|venezia|verona', 'ES': 'madrid|barcelona|valencia|seville|sevilla|malaga|bilbao|palma',
        'PT': 'lisbon|lisboa|porto', 'SE': 'stockholm|gothenburg|goteborg|malmo', 'NO': 'oslo|bergen', 'DK': 'copenhagen|kobenhavn|aarhus', 'FI': 'helsinki|tampere',
        'PL': 'warsaw|warszawa|krakow|wroclaw|gdansk|poznan', 'CZ': 'prague|praha|brno', 'HU': 'budapest', 'GR': 'athens|thessaloniki', 'RO': 'bucharest', 'HR': 'zagreb', 'RS': 'belgrade|beograd|novi sad',
        'SI': 'ljubljana|maribor', 'AE': 'dubai|abu dhabi', 'IL': 'tel aviv|jerusalem', 'SG': 'singapore', 'HK': 'hong kong', 'MX': 'mexico city|guadalajara|monterrey',
        'BR': 'sao paulo|rio de janeiro', 'ZA': 'cape town|johannesburg', 'TR': 'istanbul|ankara', 'IN': 'mumbai|bangalore|bengaluru|delhi|hyderabad|pune|chennai', 'JP': 'tokyo|osaka',
        'NP': 'kathmandu|pokhara|lalitpur'}
CITY = {c: cc for cc, cs in CITY.items() for c in cs.split('|')}
DC_ORG = re.compile(r'microsoft|azure|google|amazon|aws|linkedin|cloudflare|akamai|digitalocean|hetzner|ovh|oracle|facebook|meta platforms|proofpoint|mimecast|barracuda', re.I)
from zoneinfo import ZoneInfo
BERLIN = ZoneInfo('Europe/Berlin')
UTC = datetime.timezone.utc
sys.path.insert(0, os.path.join(HOME, 'Desktop', 'AIOS'))


# ---------- small helpers ----------
def col(n):
    """1-based column number -> letter(s)."""
    s = ''
    while n: n, r = divmod(n - 1, 26); s = chr(65 + r) + s
    return s


TRACK_COL = col(NA + NM + 1)   # first column after the manual block
MEET_DATE_COL = col(NA + 4)    # Presentation Log "Meeting booked date" (4th manual column)


def ts(t): return datetime.datetime.fromtimestamp(t, BERLIN).strftime('%Y-%m-%d %H:%M') if t else ''


def now(): return datetime.datetime.now().isoformat(timespec='seconds')


def say(*a): print(now(), *a, flush=True)


def env(k):
    kv = dict(re.findall(r'^([A-Z0-9_]+)=(.*)$', open(os.path.join(HOME, 'Desktop', 'AIOS', '.env'), encoding='utf-8').read(), re.M))
    return kv.get(k, '').strip().strip('"').strip("'")


def alert(text):
    """DM to Thomas (the mac-hub alert channel is archived, so common.slack_alert goes nowhere)."""
    say('ALERT', text)
    try:
        r = urllib.request.Request('https://slack.com/api/chat.postMessage', json.dumps({'channel': 'U09HBPS205B', 'text': 'VistaMails decks: ' + text}).encode(),
                                   {'Content-Type': 'application/json; charset=utf-8', 'Authorization': 'Bearer ' + env('SLACK_USER_TOKEN')})
        urllib.request.urlopen(r, timeout=20).read()
    except Exception as e:
        say('slack failed', e)


def hr(path, body=None, method='POST'):
    for a in range(6):
        try:
            r = urllib.request.Request(B + path, json.dumps(body).encode() if body is not None else None,
                                       {'X-API-KEY': env('HEYREACH_VISTAMAILS_API_KEY'), 'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}, method=method)
            t = urllib.request.urlopen(r, timeout=90).read().decode()
            return json.loads(t) if t.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and a < 5: time.sleep(20 * (a + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if a < 5: time.sleep(10 * (a + 1)); continue
            raise


def lid_of(url):
    u = urllib.parse.unquote((url or '').strip().lower().split('?')[0].rstrip('/'))
    return u.split('linkedin.com/in/')[-1] if 'linkedin.com/in/' in u else ''


def cf_of(lead):
    return {c.get('name'): str(c.get('value')) for c in (lead.get('customFields') or []) if c.get('name') and c.get('value') not in (None, '')}


def list_leads(list_id):
    out, off = {}, 0
    while True:
        items = hr('/list/GetLeadsFromList', {'listId': list_id, 'offset': off, 'limit': 1000}).get('items') or []
        for l in items: out[lid_of(l.get('profileUrl'))] = l
        if len(items) < 1000: return out
        off += 1000


def campaign_leads(cid):
    out, off = {}, 0
    while True:
        items = hr('/campaign/GetLeadsFromCampaign', {'campaignId': cid, 'offset': off, 'limit': 100}).get('items') or []
        for x in items: out[lid_of((x.get('linkedInUserProfile') or {}).get('profileUrl'))] = x
        if len(items) < 100: return out
        off += 100


def gsvc(api, ver):
    from google_auth import get_creds
    from googleapiclient.discovery import build
    return build(api, ver, credentials=get_creds(), cache_discovery=False)


def sheets_svc(): return gsvc('sheets', 'v4').spreadsheets()


def load_json(p, default):
    try: return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError): return default


def save_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(obj, open(p, 'w', encoding='utf-8'))


def unmojibake(s):
    """HeyReach returns the sequence text double-encoded ('Iâ€™ve', 'Â£258k'): back to 'I’ve', '£258k' when the bytes allow it."""
    try: return s.encode('cp1252').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError): return s


def ensure_tab(sv):
    """Presentation Log tab (frozen bold header) if missing, wide enough for the tracking block, header row kept current."""
    meta = sv.get(spreadsheetId=SHEET, fields='sheets.properties').execute()['sheets']
    need = NA + NM + len(TRACK_HDR)
    pl = next((x['properties'] for x in meta if x['properties']['title'] == TAB), None)
    if not pl:
        r = sv.batchUpdate(spreadsheetId=SHEET, body={'requests': [{'addSheet': {'properties': {'title': TAB, 'gridProperties': {'frozenRowCount': 1, 'columnCount': need + 2}}}}]}).execute()
        sid = r['replies'][0]['addSheet']['properties']['sheetId']
        sv.batchUpdate(spreadsheetId=SHEET, body={'requests': [{'repeatCell': {'range': {'sheetId': sid, 'startRowIndex': 0, 'endRowIndex': 1},
            'cell': {'userEnteredFormat': {'textFormat': {'bold': True}, 'backgroundColor': {'red': .9, 'green': .9, 'blue': .9}}},
            'fields': 'userEnteredFormat(textFormat,backgroundColor)'}}]}).execute()
        say('created tab', TAB)
    elif pl['gridProperties']['columnCount'] < need:
        sv.batchUpdate(spreadsheetId=SHEET, body={'requests': [{'appendDimension': {'sheetId': pl['sheetId'], 'dimension': 'COLUMNS', 'length': need - pl['gridProperties']['columnCount']}}]}).execute()
    sv.values().update(spreadsheetId=SHEET, range="'%s'!A1" % TAB, valueInputOption='RAW', body={'values': [AUTO_HDR + MAN_HDR + TRACK_HDR]}).execute()
    return meta


def live_code(url, cache):
    """200 = the deck URL HeyReach sends serves a VistaMails deck, else the HTTP code (GitHub Pages 404 fallback) or 0."""
    if url in cache: return cache[url]
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Cache-Control': 'no-cache'}), timeout=20)
        cache[url] = 200 if r.status == 200 and 'vistamails' in r.read().decode('utf-8', 'replace').lower() else r.status
    except urllib.error.HTTPError as e: cache[url] = e.code
    except Exception: cache[url] = 0
    return cache[url]


ISO_RE = re.compile(r'(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:\.(\d+))?\s*(Z|[+-]\d\d:?\d\d)?')


def iso(s):
    """Calendly / HeyReach timestamp -> aware UTC datetime, None if missing."""
    m = ISO_RE.match(s or '')
    if not m: return None
    y, mo, d, h, mi, se, frac, z = m.groups()
    off = datetime.timedelta(0)
    if z and z != 'Z': off = datetime.timedelta(hours=int(z[1:3]), minutes=int(z[-2:])) * (1 if z[0] == '+' else -1)
    try: return datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(se), int((frac or '0')[:6].ljust(6, '0')), tzinfo=UTC) - off
    except ValueError: return None


def iso_ts(s):
    d = iso(s)
    return d.timestamp() if d else 0


def ago(delta):
    s = int(abs(delta.total_seconds()))
    return '%d min' % (s // 60) if s < 7200 else '%.1f h' % (s / 3600) if s < 172800 else '%d days' % (s // 86400)


# ---------- normalising ----------
def norm(s):
    """accent-free lowercase letters and spaces."""
    s = (s or '').lower()
    for a, b in (('đ', 'd'), ('ð', 'd'), ('ł', 'l'), ('ø', 'o'), ('ß', 'ss'), ('æ', 'ae'), ('œ', 'oe')): s = s.replace(a, b)
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^a-z ]', ' ', s).split())


TEAM = {norm(n) for n in SENDERS} | {'thomas tzouridis', 'umesh pandey', 'nischaya basnet pandey'}


def toks(s): return norm(s).split()


def name_rel(a, b):
    """'exact' | 'strong' | None between two person names."""
    ta, tb = toks(a), toks(b)
    if not ta or not tb: return None
    if sorted(ta) == sorted(tb): return 'exact'
    sa, sb = set(ta), set(tb)
    if min(len(sa), len(sb)) >= 2 and (sa <= sb or sb <= sa): return 'strong'
    if ta[-1] == tb[-1] and (ta[0] == tb[0] or (len(ta[0]) == 1 and tb[0].startswith(ta[0])) or (len(tb[0]) == 1 and ta[0].startswith(tb[0]))): return 'strong'
    if difflib.SequenceMatcher(None, ' '.join(ta), ' '.join(tb)).ratio() >= 0.88: return 'strong'
    return None


def dom(u):
    """registrable domain of a URL / email domain, no www."""
    u = (u or '').strip().lower()
    if '@' in u: u = u.split('@')[-1]
    host = urllib.parse.urlparse(u if '//' in u else '//' + u).netloc or u
    return re.sub(r'^www\.', '', host.split(':')[0])


def label(d):
    p = dom(d).split('.')
    if len(p) >= 3 and p[-2] in ('co', 'com', 'org', 'net', 'gov', 'ac', 'edu'): return p[-3]
    return p[-2] if len(p) >= 2 else (p[0] if p else '')


def same_company(d1, d2):
    a, b = dom(d1), dom(d2)
    if not a or not b: return False
    if a == b or a.endswith('.' + b) or b.endswith('.' + a): return True
    return label(a) == label(b) and len(label(a)) >= 5


def is_free(email): return label(email) in FREE or dom(email).split('.')[0] in FREE


_ZONES = None
def tz_cc(tz):
    """IANA timezone -> country code via the system zone.tab (macOS has it), '' if unknown."""
    global _ZONES
    if _ZONES is None:
        _ZONES = {}
        for pth in ('/usr/share/zoneinfo/zone.tab', '/usr/share/zoneinfo/zone1970.tab'):
            try:
                for line in open(pth, encoding='utf-8'):
                    if line.startswith('#'): continue
                    f = line.rstrip('\n').split('\t')
                    if len(f) >= 3: _ZONES.setdefault(f[2], f[0].split(',')[0])
            except OSError: pass
    return _ZONES.get(tz or '', '')


def loc_cc(location):
    parts = [norm(x) for x in (location or '').split(',')]
    for cand in (parts[-1] if parts else '', norm(location)):
        if cand in COUNTRY: return COUNTRY[cand]
        if len(cand) == 2 and cand.upper() in COUNTRY.values(): return cand.upper()
    m = re.search(r', ([A-Z]{2})$', location or '')
    if m: return m.group(1)
    padded = ' ' + norm(location) + ' '
    return next((cc for city, cc in CITY.items() if ' ' + city + ' ' in padded), '')


# ---------- deck events (same rules as craze&friends cf_track.py) ----------
def geo(ip, cache):
    """'City, CC' via ipinfo.io (free, no token), cached forever; the owner lands in cache['org:' + ip] for is_bot()."""
    if not ip or ip.startswith(('10.', '100.', '127.', '192.168.')): return ''
    if ip in cache and ('org:' + ip) in cache: return cache[ip]
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request('https://ipinfo.io/%s/json' % ip, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15).read().decode())
        cache[ip] = ', '.join(x for x in (d.get('city'), d.get('country')) if x) or '?'
        cache['org:' + ip] = d.get('org') or ''
    except Exception as e:
        say('geo lookup failed', ip, e); return cache.get(ip, '')
    return cache[ip]


def is_bot(s):
    """Link scanners (LinkedIn / Microsoft Safe Links, mail security): data center IP, impossible ping clock, zero-width window or headless UA."""
    if DC_ORG.search(s.get('org') or ''): return True
    if s.get('pings', 0) > s.get('secs', 0) // 30 + 1: return True
    if s.get('w') == 0 or 'headless' in (s.get('ua') or '').lower(): return True
    return False


def read_events(st):
    """New vm-deck-track beacons since the stored offset -> st['slugs'][slug]['sids'][sid]."""
    size = os.path.getsize(EVENTS) if os.path.exists(EVENTS) else 0
    if st.get('v') != 1: st.update(v=1, offset=None, slugs={})
    off = st.get('offset')
    if off is None or off > size: off = 0   # first run: the whole log (0 VistaMails events before 2026-10-19), a truncated log: from the start
    agg = st.setdefault('slugs', {})
    if size:
        with open(EVENTS, 'rb') as f:
            f.seek(off)
            for line in f:
                if not line.endswith(b'\n'): break
                off += len(line)
                if PATH.encode() not in line: continue
                try: e = json.loads(line)
                except ValueError: continue
                if e.get('path') != PATH: continue
                p = e.get('payload') or {}
                if not isinstance(p, dict): continue
                slug, sid, ev, t = (p.get('slug') or '').lower(), p.get('sid') or '', p.get('ev') or '', e.get('ts') or time.time()
                if not slug or slug.startswith('_'): continue
                a = agg.setdefault(slug, {'sids': {}})
                s = a['sids'].setdefault(sid, {'opens': 0, 'first': t, 'last': t, 'secs': 0, 'max': 1, 'videos': [], 'book': 0, 'open_t': t, 'pings': 0})
                s['first'], s['last'] = min(s['first'], t), max(s['last'], t)
                if e.get('ip') and not s.get('ip'): s['ip'] = e['ip']
                if ev == 'open':
                    s['opens'] += 1
                    s['open_t'] = min(s.get('open_t', t), t); s['tz'] = p.get('tz') or ''; s['phone'] = bool(p.get('phone'))
                    s['w'] = p.get('w'); s['ua'] = (p.get('ua') or '')[:160]
                elif ev in ('slide', 'leave', 'ping', 'book'):
                    s['max'] = max(s['max'], int(p.get('max') or 0))
                    if ev in ('leave', 'ping'): s['secs'] = max(s['secs'], int(p.get('secs') or 0))
                    if ev == 'ping': s['pings'] = s.get('pings', 0) + 1
                    if ev == 'book': s['book'] += 1; s['book_t'] = t
                elif ev == 'video' and p.get('v') and p['v'] not in s['videos']: s['videos'].append(str(p['v'])[:60])
    st['offset'] = off
    cache = st.setdefault('geo', {})
    for a in agg.values():
        for s in a['sids'].values():
            if s.get('ip') and ('loc' not in s or 'org' not in s):
                s['loc'] = geo(s['ip'], cache); s['org'] = cache.get('org:' + s['ip'], '')
            s['bot'] = is_bot(s)


def sess_cc(s): return (s.get('loc') or '').rsplit(', ', 1)[-1] if s.get('loc') and ', ' in s['loc'] else tz_cc(s.get('tz'))


def sess_t(s): return s.get('book_t') or s.get('open_t') or 0


def sess_str(s):
    when = 'book_t' if s.get('book_t') else 'open_t'
    return '%s %s from %s%s' % ('Book clicked' if when == 'book_t' else 'deck opened', ts(sess_t(s)), s.get('loc') or s.get('tz') or '?', ' on phone' if s.get('phone') else '')


def counted(a):
    """Slug totals over the sessions that count (has an IP, not a bot, not from NOT_COUNTED_CC), None if none."""
    ss = [s for s in a['sids'].values() if s.get('ip') and not s.get('bot') and sess_cc(s) not in NOT_COUNTED_CC] if a else []
    if not ss: return None
    return {'opens': sum(s['opens'] for s in ss), 'sessions': len(ss), 'first': min(s['first'] for s in ss), 'last': max(s['last'] for s in ss),
            'max': max(s['max'] for s in ss), 'secs': sum(s['secs'] for s in ss), 'videos': list(dict.fromkeys(v for s in ss for v in s['videos'])),
            'book': sum(s['book'] for s in ss), 'sids': ss}


def where(ss):
    """'Paris, FR (2), Kathmandu, NP (1, VistaMails?)': opens per location, home country flagged as probably the client."""
    n = {}
    for s in ss:
        if s.get('loc'): n[s['loc']] = n.get(s['loc'], 0) + 1
    return ', '.join('%s (%d%s)' % (k, v, ', VistaMails?' if k.endswith(', ' + HOME_CC) else '') for k, v in sorted(n.items(), key=lambda x: -x[1]))


# ---------- Calendly ----------
def cal(path, tok, q=None):
    url = 'https://api.calendly.com' + path + ('?' + urllib.parse.urlencode(q) if q else '') if path.startswith('/') else path
    for a in range(4):
        try:
            r = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + tok, 'User-Agent': 'Mozilla/5.0'})
            return json.loads(urllib.request.urlopen(r, timeout=60).read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and a < 3: time.sleep(15 * (a + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):   # transient getaddrinfo on the Mac
            if a < 3: time.sleep(10 * (a + 1)); continue
            raise


def bookings(tok):
    """Every invitee of every event of OUR event type on Umesh's Calendly (active and canceled), as (event, invitee)."""
    out, d = [], cal('/scheduled_events', tok, {'user': CAL_USER, 'count': 100, 'sort': 'start_time:desc'})
    while True:
        for ev in d.get('collection', []):
            if not (ev.get('event_type') or '').endswith('/' + CAL_EVENT_TYPE): continue   # Umesh's own event types are his own business
            inv = cal(ev['uri'] + '/invitees', tok, {'count': 100})
            for i in inv.get('collection', []): out.append((ev, i))
        nxt = (d.get('pagination') or {}).get('next_page')
        if not nxt: break
        d = cal(nxt, tok)
    return out


# ---------- Presentation Log ----------
def leads_now(st):
    """{lid: facts} for every CONNECTED lead of the 16 live campaigns (already connected, or connected back)."""
    first = st.setdefault('first', {})   # own stamp the first time the tracker sees a lead connected
    out = {}
    for cid, (copy, sender) in LIVE.items():
        camp = campaign_leads(cid)
        src = list_leads(next(l for l, c in LISTS.items() if c == cid)) if camp else {}
        for lid, x in camp.items():
            stt = x.get('leadConnectionStatus') or 'None'
            connected = bool(CONNECTED.search(stt)) or x.get('errorCode') == 'AlreadyAConnection'
            if not connected: continue
            p = x.get('linkedInUserProfile') or {}
            l = src.get(lid) or {}
            cf = cf_of(l)
            if lid not in first: first[lid] = {'first_ts': time.time(), 'first_seen': time.strftime('%Y-%m-%d %H:%M')}
            f = first[lid]
            link = cf.get('presentation') or ''
            slug = link.rstrip('/').split('/')[-1].lower() if link else ''
            ms = x.get('leadMessageStatus') or 'None'
            out[lid] = {'name': ('%s %s' % (l.get('firstName') or p.get('firstName') or '', l.get('lastName') or p.get('lastName') or '')).strip(),
                        'company': l.get('companyName') or p.get('companyName') or '', 'sender': x.get('linkedInSenderFullName') or sender, 'copy': copy,
                        'campaign': cid, 'status': stt, 'connected': connected, 'first_seen': f.get('first_seen', ''), 'first_ts': f.get('first_ts'),
                        'msg_status': ms, 'msg_out': ms != 'None', 'replied': 'Yes' if 'repl' in ms.lower() else 'No',
                        'camp_status': x.get('leadCampaignStatus') or '', 'active': (x.get('leadCampaignStatus') or '') not in INACTIVE,
                        'last_action': (x.get('lastActionTime') or '')[:19].replace('T', ' '), 'last_ts': iso_ts(x.get('lastActionTime')),
                        'companyname': cf.get('normalizedcompanyname') or '', 'hr_url': link, 'slug': slug,
                        'email': next((e for e in (p.get('emailAddress'), p.get('enrichedEmailAddress'), p.get('customEmailAddress'), l.get('emailAddress')) if e and '@' in e), ''),
                        'website': next((v for k, v in cf.items() if k.lower() in ('website', 'company_website', 'companywebsite', 'domain')), ''),
                        'company_url': p.get('companyUrl') or l.get('companyUrl') or '', 'location': p.get('location') or l.get('location') or ''}
    return out


LISTS = {1037560: 665669, 1037561: 665671, 1037562: 665672, 1037563: 665673, 1037564: 665674, 1037565: 665675, 1037566: 665676, 1037567: 665677,
         1037568: 665678, 1037569: 665679, 1037570: 665680, 1037571: 665681, 1037572: 665682, 1037573: 665683, 1037574: 665684, 1037575: 665685}


def verdict(a, booked):
    """One plain sentence per lead; the prefixes in BAD DM Thomas once."""
    if booked: return 'meeting booked' + ('' if a['active'] else ', stopped (%s)' % a['camp_status'])
    if a['camp_status'] == 'Failed': return 'FAILED in HeyReach: %s' % (a.get('err') or '')
    if not a['active']: return 'inactive (%s)' % a['camp_status']
    if a['hr_url'] and a['live'] != 200: return 'DECK NOT LIVE (%s), HeyReach would send a dead link' % a['live']
    if a['hr_url']: return 'OK'
    if a['msg_out']: return 'message 1 out, no deck: message 2 goes out as the fallback text without a link'
    return 'waiting for message 1, no deck set'


def sync_log(sv, st, al, booked):
    old = sv.values().get(spreadsheetId=SHEET, range="'%s'!%s2:%s" % (TAB, col(6), col(NA + NM))).execute().get('values', [])
    w = NA + NM - 5
    old = [[str(x) for x in r] + [''] * (w - len(r)) for r in old]
    manual = {r[0]: r[NA - 5:w] for r in old if r[0]}   # manual block typed by hand, moved with the lead
    order = [r[0] for r in old if r[0] in al]   # a lead that left the set leaves the log
    have = set(order)
    for lid in sorted((l for l in al if l not in have), key=lambda l: (al[l].get('first_ts') or 9e12, al[l]['name'])): order.append(lid)
    live = {}
    rows, track, flagged = [], [], st.setdefault('flagged', [])
    per = {}   # sender -> [messaged with a deck, opened], Performance tab column C
    for lid in order:
        a = al.get(lid)
        if not a: rows.append([''] * NA); track.append([''] * len(TRACK_HDR)); continue
        a['live'] = live_code(a['hr_url'], live) if a['hr_url'] else ''
        chk = verdict(a, booked.get(lid))
        due1 = ts(a['first_ts'] + 3 * 3600) if a['first_ts'] else ''
        due2 = ts(a['last_ts'] + 4 * 86400) if a['msg_out'] and a['last_ts'] else ''
        rows.append([a['name'], a['company'], a['sender'], a['campaign'], a['copy'], lid, a['status'], 'Yes', a['first_seen'], due1, due2,
                     a['msg_status'], a['replied'], a['camp_status'], a['last_action'], a['companyname'], a['hr_url'], a['slug'], a['live'], chk, ''])
        t = counted(st['slugs'].get(a['slug'])) if a['slug'] else None
        track.append([t['opens'], t['sessions'], ts(t['first']), ts(t['last']), t['max'], t['secs'], ', '.join(t['videos']), t['book'], booked.get(lid, ''), where(t['sids'])]
                     if t else ['', '', '', '', '', '', '', '', booked.get(lid, ''), ''])
        if a['msg_out'] and a['slug']:
            c = per.setdefault(a['sender'], [0, 0]); c[0] += 1; c[1] += 1 if t and t['opens'] else 0
        if chk.startswith(BAD):
            kf = lid + '|' + chk[:24]
            if kf not in flagged: flagged.append(kf); alert('control check: %s (%s): %s' % (a['name'], a['company'], chk))
    if rows:
        sv.values().batchUpdate(spreadsheetId=SHEET, body={'valueInputOption': 'RAW', 'data': [
            {'range': "'%s'!A2" % TAB, 'values': rows}, {'range': "'%s'!%s2" % (TAB, col(NA + 1)), 'values': [manual.get(l, [''] * NM) for l in order]},
            {'range': "'%s'!%s2" % (TAB, TRACK_COL), 'values': track}]}).execute()
    if len(old) > len(rows):
        sv.values().clear(spreadsheetId=SHEET, range="'%s'!A%d:%s%d" % (TAB, len(rows) + 2, col(NA + NM + len(TRACK_HDR)), len(old) + 1), body={}).execute()
    st['open_rate_per'] = per
    say('sheet synced:', len(rows), 'connected leads, open rate per sender (messaged with deck, opened):', per)
    return rows


# ---------- Copy docs (Thomas 2026-10-19: the exact format of "Messages Craze & Friends", one doc per copy, built from the HeyReach sequences) ----------
EXAMPLES = [('Julian, Huel', 'https://www.linkedin.com/company/huel/', SITE + 'huel/'), ('Lena, Allbirds', 'https://www.linkedin.com/company/allbirds/', SITE + 'allbirds/')]


def chain(seq):
    """The connected path of a HeyReach sequence: [(delay number, unit, text)] for every MESSAGE node in sending order (no-reply path)."""
    node, out, first = seq, [], True
    while node and node.get('nodeType') != 'END' and len(out) < 20:
        t = node.get('nodeType')
        if t == 'CHECK_IS_CONNECTION': node = node.get('conditionalNode'); continue
        if t == 'MESSAGE':
            txt = unmojibake(((node.get('payload') or {}).get('messages') or [''])[0] or '')
            out.append((node.get('actionDelay') or 0, (node.get('actionDelayUnit') or 'DAY').lower(), txt))
        node = node.get('unconditionalNode') or node.get('conditionalNode')
    return out


def copy_messages(cids):
    """One message chain per copy. The campaigns of a copy differ only by the sender's first name in message 1 (Klaviyo Campaign 1):
    that name becomes {senderFirstName}."""
    chains = {}
    for cid in cids:
        seq = hr('/campaign/GetCampaignSequence', {'campaignId': cid})
        if not seq.get('nodeType'): seq = hr('/campaign/GetCampaignSequence?campaignId=%d' % cid, method='GET')
        ch = chain(seq)
        fn = CAMPAIGNS[cid][1].split()[0]
        chains[cid] = [(d, u, re.sub(r"(It's |I'm |It is )%s\b" % re.escape(fn), lambda m: m.group(1) + '{senderFirstName}', t)) for d, u, t in ch]
    first = chains[cids[0]]
    diff = [c for c, ch in chains.items() if ch != first]
    if diff: say('copy docs: campaigns differ from %s beyond the sender name: %s (first campaign used)' % (cids[0], diff))
    return first


def delay_text(n, unit):
    unit = unit.rstrip('s')
    return '%d %s%s' % (n, unit, '' if n == 1 else 's')


def doc_body(label, msgs):
    """Paragraph list [(text, kind)] in the craze&friends format: bold message line, text paragraphs, one empty line between everything,
    then the Examples heading (only for copies that send {presentation})."""
    out = []
    for i, (d, u, txt) in enumerate(msgs, start=1):
        if i > 1: out.append(('', 'normal'))
        out.append(('Message %d, %s' % (i, (delay_text(d, u) + ' after connecting') if i == 1 else delay_text(d, u) + ' later'), 'bold'))
        paras = [p.strip() for p in re.split(r'\n\s*\n', txt.strip()) if p.strip()]
        for j, p in enumerate(paras):
            if j: out.append(('', 'normal'))
            out.append((p.replace('\n', ' '), 'normal'))
    if any('{presentation}' in t for d, u, t in msgs):
        out += [('', 'normal'), ('', 'normal'), ('Examples for Presentation', 'h2')]
        for k, (who, page, deck) in enumerate(EXAMPLES):
            if k: out.append(('', 'normal'))
            out += [(who, 'bold'), ('Company page: ' + page, 'link:' + page), ('Presentation: ' + deck, 'link:' + deck)]
    return out


def u16(s): return len(s.encode('utf-16-le')) // 2


def write_doc(docs, doc_id, body):
    """Replaces the whole document body with the paragraphs; styles: NORMAL_TEXT everywhere except the HEADING_2 line, bold lines, links."""
    d = docs.get(documentId=doc_id).execute()
    end = d['body']['content'][-1]['endIndex']
    reqs = []
    if end > 2: reqs.append({'deleteContentRange': {'range': {'startIndex': 1, 'endIndex': end - 1}}})
    text = '\n'.join(t for t, k in body)
    reqs.append({'insertText': {'location': {'index': 1}, 'text': text}})
    reqs.append({'updateParagraphStyle': {'range': {'startIndex': 1, 'endIndex': 1 + u16(text)}, 'paragraphStyle': {'namedStyleType': 'NORMAL_TEXT'}, 'fields': 'namedStyleType'}})
    reqs.append({'updateTextStyle': {'range': {'startIndex': 1, 'endIndex': 1 + u16(text)}, 'textStyle': {'bold': False, 'underline': False},
                                     'fields': 'bold,link,underline,foregroundColor'}})   # fields not in textStyle are reset: no leftover links
    pos = 1
    for t, k in body:
        n = u16(t)
        if k == 'bold' and n: reqs.append({'updateTextStyle': {'range': {'startIndex': pos, 'endIndex': pos + n}, 'textStyle': {'bold': True}, 'fields': 'bold'}})
        elif k == 'h2': reqs.append({'updateParagraphStyle': {'range': {'startIndex': pos, 'endIndex': pos + n + 1}, 'paragraphStyle': {'namedStyleType': 'HEADING_2'}, 'fields': 'namedStyleType'}})
        elif k.startswith('link:'):
            url = k[5:]; s = pos + u16(t) - u16(url)
            reqs.append({'updateTextStyle': {'range': {'startIndex': s, 'endIndex': s + u16(url)}, 'textStyle': {'link': {'url': url}}, 'fields': 'link'}})
        pos += n + 1
    docs.batchUpdate(documentId=doc_id, body={'requests': reqs}).execute()


def copy_docs(st):
    """One Google Doc per copy, "Messages VistaMails <copy>", rebuilt only when the sequence text changed. Returns {label: edit URL}."""
    docs = gsvc('docs', 'v1').documents()
    reg = st.setdefault('docs', {})
    links = {}
    for label, cids in COPIES:
        try:
            body = doc_body(label, copy_messages(cids))
            h = hashlib.sha1(json.dumps(body).encode()).hexdigest()
            e = reg.get(label) or {}
            if not e.get('id'):
                e = {'id': docs.create(body={'title': 'Messages VistaMails ' + label}).execute()['documentId'], 'hash': ''}
                say('copy doc created:', label, e['id'])
            if e.get('hash') != h:
                write_doc(docs, e['id'], body); e['hash'] = h; say('copy doc written:', label, len(body), 'paragraphs')
            reg[label] = e
        except Exception as ex:
            say('copy doc %s failed: %r' % (label, ex))
        if reg.get(label, {}).get('id'): links[label] = 'https://docs.google.com/document/d/%s/edit' % reg[label]['id']
    return links


def copy_links(sv, links):
    """Copy tab column B = the doc link of the row whose A contains the copy label (hr_perf never rewrites A or B)."""
    rows = sv.values().get(spreadsheetId=SHEET, range='Copy!A2:B40').execute().get('values', [])
    data = []
    for i, r in enumerate(rows, start=2):
        a = (r[0] if r else '').strip(); b = r[1] if len(r) > 1 else ''
        hit = next((l for l, _c in COPIES if a and l.lower() in a.lower()), None)
        if hit and links.get(hit) and b != links[hit]: data.append({'range': 'Copy!B%d' % i, 'values': [[links[hit]]]})
    if data: sv.values().batchUpdate(spreadsheetId=SHEET, body={'valueInputOption': 'RAW', 'data': data}).execute()
    return len(data)


# ---------- context for matching (HeyReach, Supabase), built only when a booking needs a match ----------
class Ctx:
    def __init__(self, st, al):
        self.st, self.al = st, al
        self.leads = {lid: {'name': a['name'], 'company': a['company'], 'slug': a['slug'], 'website': a['website'], 'sender': a['sender']} for lid, a in al.items()}
        self.sids = {sid: (slug, s) for slug, a in st['slugs'].items() for sid, s in a['sids'].items()}
        self.by_slug = {}
        for k, v in self.leads.items():
            if v['slug']: self.by_slug.setdefault(v['slug'], []).append(k)
        self._hr = self._convs = self._sb = None
        self.errs = []

    def hr(self):
        """{lead id: {name, company, emails, location, cc, sender, msg_sent, campaign, connected, company_url, position}} for every lead of every campaign, cached 6 h."""
        if self._hr is not None: return self._hr
        c = load_json(HR_CACHE, {})
        if c.get('v') == 1 and time.time() - c.get('at', 0) < 6 * 3600: self._hr = c['leads']; return self._hr
        out = {}
        for cid in CAMPAIGNS_ALL:
            for lid, i in campaign_leads(cid).items():
                pr = i.get('linkedInUserProfile') or {}
                if not lid: continue
                emails = {e.lower() for e in (pr.get('emailAddress'), pr.get('customEmailAddress'), pr.get('enrichedEmailAddress')) if e and '@' in e}
                out[lid] = {'name': ('%s %s' % (pr.get('firstName') or '', pr.get('lastName') or '')).strip(), 'company': pr.get('companyName') or '',
                            'emails': sorted(emails), 'location': pr.get('location') or '', 'cc': loc_cc(pr.get('location') or ''),
                            'sender': i.get('linkedInSenderFullName') or CAMPAIGNS[cid][1], 'msg_sent': (i.get('leadMessageStatus') or 'None') != 'None',
                            'campaign': cid, 'connected': bool(CONNECTED.search(i.get('leadConnectionStatus') or '')),
                            'company_url': (pr.get('companyUrl') or '').strip(), 'position': pr.get('position') or ''}
        self._hr = out
        save_json(HR_CACHE, {'v': 1, 'at': time.time(), 'leads': out})
        return out

    def convs(self):
        """{lead id: {link_sent, deck_sent, text, emails, last_lead_at, tags, profile, messages}} from the HeyReach inbox."""
        if self._convs is not None: return self._convs
        out, off = {}, 0
        while True:
            items = hr('/inbox/GetConversationsV2', {'filters': {}, 'offset': off, 'limit': 100}).get('items') or []
            for c in items:
                cp = c.get('correspondentProfile') or {}
                lid = lid_of(cp.get('profileUrl'))
                if not lid: continue
                v = out.setdefault(lid, {'link_sent': [], 'deck_sent': [], 'text': '', 'emails': set(), 'last_lead_at': None, 'tags': [], 'profile': cp, 'messages': []})
                v['tags'] += [((t.get('name') if isinstance(t, dict) else str(t)) or '', ((t.get('creationTime') if isinstance(t, dict) else '') or '')[:10])
                              for t in (cp.get('tags') or []) + (cp.get('autoTags') or [])]
                v['messages'] += c.get('messages') or []
                for msg in c.get('messages') or []:
                    body, t = msg.get('body') or '', iso(msg.get('createdAt'))
                    ours = (msg.get('sender') or '').upper() == 'ME'
                    if ours and t and LINK_RE.search(body): v['link_sent'].append(t)
                    if ours and t and DECK_RE.search(body): v['deck_sent'].append(t)
                    if not ours and t and (v['last_lead_at'] is None or t > v['last_lead_at']): v['last_lead_at'] = t
                    v['text'] += ' ' + body
                    v['emails'] |= {e.lower() for e in EMAIL_RE.findall(body)}
            if len(items) < 100: break
            off += 100
        self._convs = out
        return out

    def sb(self):
        """Supabase connection (ocean_leads), None if unreachable: the match then runs without it."""
        if self._sb is None:
            try:
                import psycopg2
                self._sb = psycopg2.connect(host='aws-0-eu-central-1.pooler.supabase.com', port=5432, user='postgres.' + env('SUPABASE_PROJECT_REF'),
                                            password=env('SUPABASE_DB_PASSWORD'), dbname='postgres', sslmode='require', connect_timeout=30)
                self._sb.autocommit = True
            except Exception as e:
                say('supabase unavailable:', e); self._sb = False
        return self._sb or None

    def sb_by_email(self, email):
        c = self.sb()
        if not c or not email: return []
        try:
            cur = c.cursor()
            cur.execute("""select person_linkedin, coalesce(person_name, fullnames, ''), coalesce(company, companyname, ''), coalesce(domain, companywebsite, company_email_domain, '')
                           from ocean_leads where lower(person_email)=%(e)s or lower(email)=%(e)s or lower(findymail_email)=%(e)s or lower(email_2)=%(e)s
                              or lower(email_3)=%(e)s or lower(email_4)=%(e)s or lower(email_5)=%(e)s limit 10""", {'e': email.lower()})
            return [(lid_of(li), nm, co, d) for li, nm, co, d in cur.fetchall()]
        except Exception as e:
            say('supabase query failed:', e); return []

    def sb_company_linkedin(self, lid):
        c = self.sb()
        if not c or not lid: return ''
        try:
            cur = c.cursor()
            cur.execute("select coalesce(company_linkedin_url, linkedincompanypageurl, sheet_company_linkedin, '') from ocean_leads where person_linkedin ilike %s limit 5", ('%/in/' + lid + '%',))
            return next((r[0] for r in cur.fetchall() if r[0]), '')
        except Exception as e:
            say('supabase query failed:', e); return ''

    def sb_lead(self, lid, email=''):
        """{email, website, company_linkedin, person_phone, company_phone, company} from ocean_leads, {} if nothing."""
        c = self.sb()
        if not c or not (lid or email): return {}
        cols = """coalesce(email, person_email, findymail_email, email_2, ''), coalesce(domain, companywebsite, sheet_company_website, company_email_domain, ''),
                  coalesce(company_linkedin_url, linkedincompanypageurl, sheet_company_linkedin, ''), coalesce(person_phone, person_phone_sheet, ''),
                  coalesce(company_phone, imprint_phone, generic_company_phones, ''), coalesce(company, companyname, '')"""
        try:
            cur = c.cursor()
            rows = []
            if lid:
                cur.execute("select %s from ocean_leads where substring(lower(person_linkedin) from 'linkedin\\.com/in/([^/?#]+)') = %%s limit 5" % cols, (lid.lower(),))
                rows = cur.fetchall()
            if not rows and email:
                cur.execute("select %s from ocean_leads where lower(email)=%%(e)s or lower(person_email)=%%(e)s or lower(findymail_email)=%%(e)s limit 5" % cols, {'e': email.lower()})
                rows = cur.fetchall()
            out = {}
            for r in rows:
                for k, v in zip(('email', 'website', 'company_linkedin', 'person_phone', 'company_phone', 'company'), r):
                    v = re.split(r'[,;|]', (v or '').strip())[0].strip() if k.endswith('phone') else (v or '').strip()
                    if v and not out.get(k): out[k] = v
            return out
        except Exception as e:
            say('supabase query failed:', e); return {}

    def sb_booked(self, lid, row, phone_is_mobile, src):
        """ocean_leads: mailvista_status = 'meeting booked' for the lead, phone / email gap-filled (never overwrite), provenance appended to
        matched_sources. A lead the DB does not have yet is inserted (append-only). Returns a note, raises on failure."""
        c = self.sb()
        if not c: raise RuntimeError('supabase unavailable')
        li = 'https://www.linkedin.com/in/' + lid
        name = re.sub(r'\s*\(no lead match\)$', '', row[0])
        email, site, phone = row[1] if '@' in row[1] else None, dom(row[2]) or None, row[5] or None
        comp = self.fact(lid).get('company') or None
        cur = c.cursor()
        cur.execute("""update ocean_leads set mailvista_status = 'meeting booked',
                          email = coalesce(nullif(email, ''), %(email)s), person_phone = coalesce(nullif(person_phone, ''), %(pp)s),
                          company_phone = coalesce(nullif(company_phone, ''), %(cp)s), domain = coalesce(nullif(domain, ''), %(site)s),
                          matched_sources = case when coalesce(matched_sources, '') like %(like)s then matched_sources else concat_ws(', ', nullif(matched_sources, ''), %(src)s) end
                        where substring(lower(person_linkedin) from 'linkedin\\.com/in/([^/?#]+)') = %(lid)s returning id""",
                    {'email': email, 'pp': phone if phone_is_mobile else None, 'cp': None if phone_is_mobile else phone, 'site': site,
                     'like': '%' + src + '%', 'src': src, 'lid': lid.lower()})
        ids = [r[0] for r in cur.fetchall()]
        if ids: return 'supabase: meeting booked on id %s' % ids
        cur.execute("""insert into ocean_leads (person_linkedin, person_name, company, domain, email, person_phone, company_phone, mailvista_status, matched_sources)
                       values (%s, %s, %s, %s, %s, %s, %s, 'meeting booked', %s) returning id""",
                    (li, name, comp, site, email, phone if phone_is_mobile else None, None if phone_is_mobile else phone, src))
        return 'supabase: inserted id %s, meeting booked' % cur.fetchone()[0]

    def fact(self, lid):
        """one merged view of a lead: live log facts + HeyReach cache."""
        a, b = self.al.get(lid) or {}, self.hr().get(lid) or {}
        emails = sorted(set(b.get('emails') or []) | ({a['email'].lower()} if a.get('email') else set()))
        return {'id': lid, 'name': a.get('name') or b.get('name') or lid, 'company': a.get('company') or b.get('company') or '', 'website': a.get('website') or '',
                'slug': a.get('slug') or '', 'emails': emails, 'location': a.get('location') or b.get('location') or '', 'cc': loc_cc(a.get('location') or b.get('location') or ''),
                'sender': a.get('sender') or b.get('sender') or '', 'msg_sent': a.get('msg_out', b.get('msg_sent', False)), 'connected': a.get('connected', b.get('connected', False)),
                'company_url': a.get('company_url') or b.get('company_url') or '', 'position': b.get('position') or '', 'campaign': a.get('campaign') or b.get('campaign')}

    def all_ids(self): return list(dict.fromkeys(list(self.al) + list(self.hr())))


def pick_by_person(ctx, cands, name, email):
    for rel in ('exact', 'strong'):
        hit = [l for l in cands if name_rel(ctx.fact(l)['name'], name) == rel]
        if len(hit) == 1: return hit[0], 'name matches'
        if hit: return hit[0], 'name matches (%d leads with that name)' % len(hit)
    if email:
        hit = [l for l in cands if email.lower() in ctx.fact(l)['emails']]
        if hit: return hit[0], 'email is the lead\'s email'
    return None, ''


def pick_among(ctx, cands, created, inv_cc):
    cv = ctx.convs()
    got = [l for l in cands if cv.get(l, {}).get('link_sent') or cv.get(l, {}).get('deck_sent') or ctx.fact(l)['msg_sent']]
    pool = got or cands
    if inv_cc:
        fit = [l for l in pool if ctx.fact(l)['cc'] == inv_cc]
        if fit: pool = fit
    if len(pool) == 1: return pool[0], '', True
    def last(l):
        v = cv.get(l, {}); t = max(v.get('link_sent', []) + v.get('deck_sent', []) + ([v['last_lead_at']] if v.get('last_lead_at') else []), default=None)
        return t or datetime.datetime(2000, 1, 1, tzinfo=UTC)
    pool = sorted(pool, key=last, reverse=True)
    return pool[0], 'also possible: ' + ', '.join(ctx.fact(l)['name'] for l in pool[1:4]), False


def resolve(ctx, inv, ev):
    """-> {'lead': id|None, 'internal': bool, 'how': sentence, 'check': bool, 'booker_is_lead': bool}; rules 0-6 of craze&friends, first hit wins."""
    name, email = (inv.get('name') or '').strip(), (inv.get('email') or '').strip().lower()
    created = iso(inv.get('created_at')) or iso(ev.get('created_at')) or datetime.datetime.now(UTC)
    inv_cc = tz_cc(inv.get('timezone'))
    tr = inv.get('tracking') or {}
    def R(lead, how, check=False):
        f = ctx.fact(lead) if lead else {}
        return {'lead': lead, 'internal': False, 'how': how, 'check': check,
                'booker_is_lead': bool(lead) and (name_rel(f['name'], name) is not None or (email and email in f['emails']))}
    INT = lambda how: {'lead': None, 'internal': True, 'how': how, 'check': False, 'booker_is_lead': False}
    # 0 internal
    if dom(email) in INTERNAL_DOMAINS: return INT('internal: email domain %s' % dom(email))
    if norm(name) in TEAM: return INT('internal: team member %s' % name)
    # 1 deck tag (the deck's Book button would carry utm_source=vm-deck&utm_campaign=<slug>&utm_content=<session>)
    slug = (tr.get('utm_campaign') or '').lower() if (tr.get('utm_source') or '') == 'vm-deck' else ''
    if slug:
        sid = tr.get('utm_content') or ''
        s = ctx.sids.get(sid, (None, None))[1]
        ev_s = 'deck tag %s' % slug + ((', ' + sess_str(s) + ', booking %s later' % ago(created - datetime.datetime.fromtimestamp(sess_t(s), UTC))) if s and sess_t(s) else ', untracked device')
        cands = ctx.by_slug.get(slug, [])
        if cands:
            lead, why = pick_by_person(ctx, cands, name, email)
            if lead: return R(lead, ev_s + ', ' + why)
            if s and sess_cc(s) in OUR_CC: return INT(ev_s + ': opened from our side, booker %s is no lead' % name)
            if len(cands) == 1: return R(cands[0], ev_s + ', booked by another person for this lead (colleague or partner)')
            lead, note, sure = pick_among(ctx, cands, created, inv_cc)
            return R(lead, ev_s + ', shared deck, booker is not one of the leads; ' + (note or 'this lead got the message'), not sure)
    # 2 email
    if email:
        hit = [l for l in ctx.all_ids() if email in ctx.fact(l)['emails']]
        if hit: return R(hit[0], 'email %s is the lead\'s email (HeyReach)' % email)
        for lid, nm, co, d in ctx.sb_by_email(email):
            if lid and (lid in ctx.al or lid in ctx.hr()): return R(lid, 'email %s is the lead\'s email (Supabase)' % email)
        if not is_free(email):
            at = [l for l in ctx.all_ids() if same_company(email, ctx.fact(l)['website'])]
            if not at:
                for lid, nm, co, d in ctx.sb_by_email(email):
                    at = [l for l in ctx.all_ids() if d and same_company(d, ctx.fact(l)['website'])]
                    if at: break
            if at:
                lead, why = pick_by_person(ctx, at, name, email)
                if lead: return R(lead, 'email domain %s = lead website, %s' % (dom(email), why))
                lead, note, sure = pick_among(ctx, at, created, inv_cc)
                return R(lead, 'email domain %s = lead website, booked by a colleague; %s' % (dom(email), note or 'this lead got the message'), not sure)
    # 3 chat
    cv = ctx.convs()
    nt = [t for t in toks(name) if len(t) >= 3]
    hit = [l for l, v in cv.items() if (email and email in v['emails']) or (len(nt) >= 2 and all(t in norm(v['text']).split() for t in nt))]
    if len(hit) == 1: return R(hit[0], 'booker %s %s is mentioned in the lead\'s HeyReach chat' % (name, email))
    if hit:
        lead, note, sure = pick_among(ctx, hit, created, inv_cc)
        return R(lead, 'booker mentioned in several chats; ' + note, True)
    # 4 name
    for rel in ('exact', 'strong'):
        hit = [l for l in ctx.all_ids() if name_rel(ctx.fact(l)['name'], name) == rel]
        if len(hit) == 1: return R(hit[0], 'name matches a campaign lead (%s)' % rel + (', timezone %s fits' % inv.get('timezone') if inv_cc and ctx.fact(hit[0])['cc'] == inv_cc else ''))
        if hit:
            lead, note, sure = pick_among(ctx, hit, created, inv_cc)
            return R(lead, 'name matches %d campaign leads; %s' % (len(hit), note or 'this one got the message'), not sure)
    # 5 plain link recipients
    recent = [(max(v['link_sent']), l) for l, v in cv.items() if v['link_sent'] and created - datetime.timedelta(days=30) <= max(v['link_sent']) <= created]
    if recent:
        recent.sort(reverse=True)
        pool = [l for t, l in recent]
        fit = [l for l in pool if inv_cc and ctx.fact(l)['cc'] == inv_cc]
        lead = (fit or pool)[0]
        t = dict((l, t) for t, l in recent)[lead]
        others = [ctx.fact(l)['name'] for l in (fit or pool)[1:4]]
        return R(lead, 'best guess: Calendly link sent in HeyReach %s, booking %s later, booker %s is not the lead%s%s' % (
            t.astimezone(BERLIN).strftime('%Y-%m-%d %H:%M'), ago(created - t), name, ', timezone fits' if fit else '', ('; also possible: ' + ', '.join(others)) if others else ''), check=True)
    # 6 deck activity shortly before the booking
    near = []
    for sid, (sl, s) in ctx.sids.items():
        t = sess_t(s)
        if t and 0 <= (created - datetime.datetime.fromtimestamp(t, UTC)).total_seconds() <= 2 * 3600 and ctx.by_slug.get(sl) and sess_cc(s) not in OUR_CC:
            near.append((int(bool(s.get('book_t'))), int(bool(inv_cc) and sess_cc(s) == inv_cc), t, sl, s))
    if near:
        near.sort(key=lambda x: x[:3], reverse=True)
        booked_click, fits, t, sl, s = near[0]
        lead, note, sure = pick_among(ctx, ctx.by_slug[sl], created, inv_cc)
        return R(lead, 'best guess: %s, booking %s later, no tag%s%s' % (sess_str(s), ago(created - datetime.datetime.fromtimestamp(t, UTC)),
                                                                      ', timezone fits' if fits else '', ('; ' + note) if note else ''), check=True)
    # nothing
    if inv_cc in OUR_CC: return INT('internal: timezone %s, no lead matches %s %s' % (inv.get('timezone'), name, email))
    return {'lead': None, 'internal': False, 'how': 'no lead matches %s %s' % (name, email), 'check': True, 'booker_is_lead': False}


# ---------- phone + email via Prospeo (every Meetings row carries the lead's number when Prospeo has one, fully automatic) ----------
def prospeo(data):
    """POST /enrich-person with enrich_mobile (10 credits per revealed mobile, email included, 0 on a miss, same record free again for 90 days)."""
    key = env('PROSPEO_API_KEY')
    if not key: raise RuntimeError('PROSPEO_API_KEY missing in .env')
    r = urllib.request.Request('https://api.prospeo.io/enrich-person', json.dumps({'enrich_mobile': True, 'data': data}).encode(),
                               {'X-KEY': key, 'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
    try:
        out = json.loads(urllib.request.urlopen(r, timeout=60).read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors='replace')[:300]
        if e.code == 429: raise   # rate or daily cap: this run stops enriching, the next run retries
        say('prospeo', list(data), '-> HTTP', e.code, body); return {'mobile': '', 'hq': '', 'email': '', 'website': '', 'company_linkedin': '', 'linkedin': ''}
    person, comp = out.get('person') or {}, out.get('company') or {}
    mob, em = person.get('mobile') or {}, person.get('email') or {}
    return {'mobile': (mob.get('mobile_international') or '').strip() if mob.get('revealed') else '',
            'hq': ((comp.get('phone_hq') or {}).get('phone_hq_international') or '').strip(),
            'email': (em.get('email') or '').strip() if em.get('revealed') and '@' in (em.get('email') or '') else '',
            'website': (comp.get('website') or '').strip(), 'company_linkedin': (comp.get('linkedin_url') or comp.get('linkedin') or '').strip(),
            'linkedin': (person.get('linkedin_url') or person.get('linkedin') or '').strip()}


def prospeo_lead(st, linkedin, email, name, website, company):
    """LinkedIn URL -> work email -> name + company website. Personal mobile wins, the company HQ line is the fallback. Cached per lead:
    a hit is final, a miss is retried every PHONE_RETRY_DAYS days."""
    ck = (linkedin or email or name).lower().rstrip('/')
    cache = st.setdefault('phones', {})
    c = cache.get(ck)
    if c and (c.get('phone') or time.time() - c.get('at', 0) < PHONE_RETRY_DAYS * 86400): return c
    attempts = []
    if linkedin: attempts.append({'linkedin_url': linkedin})
    if email and email.split('@')[-1].lower() not in FREEMAIL: attempts.append({'email': email})
    parts = (name or '').split()
    site = dom(website or '') or (email.split('@')[-1] if email and email.split('@')[-1].lower() not in FREEMAIL else '')
    if len(parts) >= 2 and site: attempts.append(dict({'first_name': parts[0], 'last_name': parts[-1], 'company_website': 'https://' + site}, **({'company_name': company} if company else {})))
    res = {'at': time.time(), 'phone': '', 'how': 'none', 'email': '', 'website': '', 'company_linkedin': '', 'linkedin': '', 'tried': len(attempts)}
    hq = ''
    for data in attempts:
        o = prospeo(data)
        hq = hq or o['hq']
        for k in ('email', 'website', 'company_linkedin', 'linkedin'): res[k] = res[k] or o.get(k, '')
        if o['mobile']: res.update(phone=o['mobile'], how='mobile via ' + list(data)[0]); break
    if not res['phone'] and hq: res.update(phone=hq, how='company HQ line')
    cache[ck] = res
    say('prospeo for', name, '->', res['phone'] or 'no phone', '(%s)' % res['how'], ('email ' + res['email']) if res['email'] else '')
    return res


def enrich_row(ctx, row, lid=None):
    """Fills every empty cell of a Meetings row: B email, C website, D LinkedIn, E company LinkedIn, F phone. Sources in order: what the row
    has, the HeyReach lead profile, the lead's custom fields, Supabase ocean_leads, Prospeo (only while the phone is missing). Filled cells
    are never overwritten. Returns True when a cell changed."""
    if row[0].startswith('INTERNAL') or not (row[3] or row[1] or row[0]): return False
    if not lid and row[3]: lid = lid_of(row[3]) or None
    before = list(row)
    hrf = (ctx.hr().get(lid) or {}) if lid else {}
    a = (ctx.al.get(lid) or {}) if lid else {}
    sb = ctx.sb_lead(lid, row[1] if '@' in row[1] else '')
    name = re.sub(r'\s*\(no lead match\)$', '', row[0])

    def put(i, *vals):
        if not row[i]: row[i] = next((str(v).strip() for v in vals if v and str(v).strip()), '')
    put(1, *(hrf.get('emails') or []), a.get('email'), sb.get('email'))
    site = a.get('website') or sb.get('website') or (row[1] if row[1] and '@' in row[1] and not is_free(row[1]) else '')
    put(2, ('https://' + dom(site)) if dom(site) else '')
    put(3, ('https://www.linkedin.com/in/%s/' % lid) if lid else '')
    put(4, hrf.get('company_url'), a.get('company_url'), sb.get('company_linkedin'))
    put(5, sb.get('person_phone'))
    if not row[5]:
        pr = prospeo_lead(ctx.st, row[3], row[1], name, row[2], hrf.get('company') or a.get('company') or sb.get('company') or '')
        put(5, pr.get('phone')); put(1, pr.get('email')); put(2, pr.get('website')); put(3, pr.get('linkedin')); put(4, pr.get('company_linkedin'))
    put(5, sb.get('company_phone'))
    if not row[4] and not lid and row[3]:
        l2 = lid_of(row[3])
        if l2: put(4, ctx.sb_lead(l2).get('company_linkedin'))
    return row != before


def phone_is_mobile(ctx, row):
    for ck in ((row[3] or '').lower().rstrip('/'), (row[1] or '').lower()):
        c = ctx.st.get('phones', {}).get(ck)
        if c and c.get('phone') == row[5]: return c.get('how', '').startswith('mobile')
    return True


# ---------- a booked lead leaves the sequence ----------
def on_booked(ctx, lid, row, src):
    """Every step once per lead, each retried on the next run until it worked (state 'acted'[lid][step]):
    stop: StopLeadInCampaign in the lead's campaign; tag: "Meeting booked" on the lead; sb: Supabase mailvista_status = 'meeting booked'."""
    a = ctx.st.setdefault('acted', {}).setdefault(lid, {})
    if a.get('stop') and a.get('tag') and a.get('sb'): return
    url, notes = 'https://www.linkedin.com/in/%s' % lid, []
    fact = ctx.fact(lid)
    if not a.get('stop'):
        ok = True
        for cid in ([fact['campaign']] if fact.get('campaign') else CAMPAIGNS_ALL):
            try: hr('/campaign/StopLeadInCampaign', {'campaignId': cid, 'leadUrl': url}); notes.append('stopped in %s' % cid)
            except Exception as e:
                if 'HTTP Error 4' not in repr(e): ok = False   # a 4xx = the lead is not in that campaign, fine
                notes.append('stop %s: %s' % (cid, repr(e)[:80]))
        a['stop'] = ok
    if not a.get('tag'):
        try: r = hr('/lead/AddTags', {'leadProfileUrl': url, 'tags': ['Meeting booked'], 'createTagIfNotExisting': True}); notes.append('tagged %s' % (r.get('newAssignedTags') or 'already')); a['tag'] = True
        except Exception as e: notes.append('tag: ' + repr(e)[:80])
    if not a.get('sb'):
        try: notes.append(ctx.sb_booked(lid, row, phone_is_mobile(ctx, row), src)); a['sb'] = True
        except Exception as e: notes.append('supabase: ' + repr(e)[:120])
    a['at'] = time.time(); a['notes'] = notes
    say('booked lead', lid, '->', '; '.join(notes))


def slack_meeting(ctx, row, key):
    """One Slack line per new tag / typed meeting in #meeting-booked-notifier. Calendly bookings of our event type are posted by the
    booking-tracker (Vercel) already and are never posted twice from here."""
    done = ctx.st.setdefault('slacked', [])
    if key in done or row[0].startswith('INTERNAL'): return
    if key.startswith('http'): done.append(key); return   # Calendly invitee URI: the booking-tracker's post
    tok = env('SLACK_USER_TOKEN')
    if not tok: say('slack meeting: SLACK_USER_TOKEN missing'); return
    bits = [row[0], row[1], row[2], row[5] or 'no phone yet', 'meeting ' + row[6], row[11], row[12]]
    text = '📅 VistaMails: new meeting ' + ', '.join(b for b in bits if b) + '\nhttps://docs.google.com/spreadsheets/d/%s' % SHEET
    try:
        r = urllib.request.Request('https://slack.com/api/chat.postMessage', json.dumps({'channel': env('SLACK_BOOKING_CHANNEL') or SLACK_BOOKING_CHANNEL, 'text': text}).encode(),
                                   {'Content-Type': 'application/json; charset=utf-8', 'Authorization': 'Bearer ' + tok})
        out = json.loads(urllib.request.urlopen(r, timeout=20).read().decode())
        if out.get('ok'): done.append(key); say('slack: meeting posted for', row[0])
        else: say('slack meeting failed:', out.get('error'))
    except Exception as e: say('slack meeting failed:', e)


# ---------- self-check ----------
ISSUE = {'steps': (24, 1), 'match': (168, 1), 'slack': (24, 2), 'enrich': (24, 2)}   # kind -> (hours between repeat alerts, runs seen before the first alert)


def issues_of(ctx, seen):
    """What is still undone after this run, {key: text}. An empty cell because every source came back empty is NOT an issue."""
    out = {}
    for key, r, lid, active in seen:
        if not active or r[0].startswith('INTERNAL'): continue
        if lid:
            a = ctx.st.get('acted', {}).get(lid, {})
            left = [x for x in ('stop', 'tag', 'sb') if not a.get(x)]
            if left: out['steps ' + lid] = 'booked lead %s: %s still open after retry (%s)' % (r[0], ', '.join(left), '; '.join(a.get('notes') or [])[:200])
        elif r[13]: out['match ' + key] = 'Lead override "%s" on booking %s matches no lead in the lead map, fix Meetings column N' % (r[13], r[0])
        else: out['match ' + key] = 'booking %s (%s, %s) matched no lead, so no HeyReach stop / tag / Supabase: set the Lead override in Meetings column N' % (r[0], r[1], r[6])
        if key not in ctx.st.get('slacked', []): out['slack ' + key] = 'Slack post missing for meeting %s' % r[0]
    for who, err in ctx.errs: out['enrich ' + who] = 'enrich %s failed: %s' % (who, err)
    return out


def report(st, issues):
    """One DM to Thomas per run at most: NEW / STILL OPEN / resolved (state 'issues')."""
    known, now_, lines = st.setdefault('issues', {}), time.time(), []
    for k, text in issues.items():
        rep, minr = ISSUE.get(k.split(' ', 1)[0], (24, 1))
        e = known.setdefault(k, {'first': now_, 'runs': 0, 'alerted': 0, 'text': text}); e['runs'] += 1; e['text'] = text
        if e['runs'] < minr: continue
        if not e['alerted']: e['alerted'] = now_; lines.append('NEW: ' + text)
        elif now_ - e['alerted'] >= rep * 3600: e['alerted'] = now_; lines.append('STILL OPEN since %s: %s' % (ts(e['first']), text))
    for k in [k for k in known if k not in issues]:
        e = known.pop(k)
        if e.get('alerted'): lines.append('resolved: ' + e['text'])
    if lines: alert('vm_track report, %d open\n' % len(issues) + '\n'.join(lines))


def status_line(st, failed):
    """Run summary into the job log only (no Status tab, Thomas 2026-10-17)."""
    if not failed: st['last_ok'] = time.time()
    issues = st.get('issues', {})
    say('status: last ok', ts(st.get('last_ok')), '| open issues', ('%d: ' % len(issues) + '; '.join(e['text'] for e in issues.values()))[:500] if issues else 'none',
        '| this run', 'FAILED: ' + repr(failed)[:150] if failed else 'OK')


def crashed(e):
    say(traceback.format_exc())
    last = load_json(CRASH, {}).get('at', 0)
    if time.time() - last < 20 * 3600: return
    tb = traceback.format_exc().strip().splitlines()
    alert('vista_track FAILED on the Mac: %s\n%s\nRetried every 4 h, this alert at most once a day. Log: ~/Desktop/AIOS/automations/mac-hub/logs/jobs/vista_track.log'
          % (repr(e)[:200], (tb[-3] if len(tb) >= 3 else '')[:200]))
    save_json(CRASH, {'at': time.time(), 'err': repr(e)[:200]})


# ---------- Meetings tab ----------
def ensure_meet_tab(sv, meta):
    if any(x['properties']['title'] == 'Meetings' for x in meta): return
    res = sv.batchUpdate(spreadsheetId=SHEET, body={'requests': [{'addSheet': {'properties': {'title': 'Meetings', 'gridProperties': {'rowCount': 300, 'columnCount': 16, 'frozenRowCount': 1}}}}]}).execute()
    sid = res['replies'][0]['addSheet']['properties']['sheetId']
    sv.values().update(spreadsheetId=SHEET, range='Meetings!A1', valueInputOption='RAW', body={'values': [MEET_HDR]}).execute()
    sv.batchUpdate(spreadsheetId=SHEET, body={'requests': [{'repeatCell': {'range': {'sheetId': sid, 'startRowIndex': 0, 'endRowIndex': 1},
                   'cell': {'userEnteredFormat': {'textFormat': {'bold': True}}}, 'fields': 'userEnteredFormat.textFormat.bold'}}]}).execute()
    say('created tab Meetings')


def chain_root(inv, by_uri):
    seen = set()
    while inv.get('old_invitee') and inv['old_invitee'] in by_uri and inv['uri'] not in seen:
        seen.add(inv['uri']); inv = by_uri[inv['old_invitee']]
    return inv['uri']


def thread_text(cv, lead_name, sender):
    lines = ['[LinkedIn, HeyReach inbox]']
    for m in cv.get('messages') or []:
        who = sender if (m.get('sender') or '').upper() == 'ME' else lead_name
        lines.append('%s (%s)\n%s\n---' % (who, (m.get('createdAt') or '')[:16].replace('T', ' '), (m.get('body') or '').strip()))
    return '\n'.join(lines)[:40000] if len(lines) > 1 else ''


def meet_row(ctx, res, inv, ev, start, key):
    name, email = (inv.get('name') or '').strip(), (inv.get('email') or '').strip()
    phone = inv.get('text_reminder_number') or next((q.get('answer', '') for q in inv.get('questions_and_answers') or [] if re.search(r'(?i)phone|whatsapp|number', q.get('question', ''))), '')
    lead = ctx.fact(res['lead']) if res['lead'] else None
    if res['internal']:
        row = ['INTERNAL: ' + name, email, '', '', '', phone, start, '', '', '', key, '', res['how'], '']
    elif lead:
        row = [lead['name'], email if res['booker_is_lead'] else (lead['emails'][0] if lead['emails'] else ''), ('https://' + dom(lead['website'])) if lead['website'] else '',
               'https://www.linkedin.com/in/%s/' % lead['id'], lead['company_url'] or ctx.sb_company_linkedin(lead['id']), phone, start, '', '', '', key,
               '' if res['booker_is_lead'] else 'Booked by %s, %s' % (name, email), res['how'] + (', CHECK' if res['check'] else ''), '']
    else:
        row = [name + ' (no lead match)', email, '', '', '', phone, start, '', '', '', key, '', res['how'] + ', CHECK', '']
    try: enrich_row(ctx, row, res['lead'])
    except Exception as e: say('enrich failed for', row[0], repr(e)[:120]); ctx.errs.append((row[0], repr(e)[:120]))
    return row


def sync_meetings(sv, st, al, meta):
    """Calendly bookings + HeyReach "meeting" tags + typed dates -> Meetings tab. Returns ({lid: date} of active meetings, new rows landed)."""
    ensure_meet_tab(sv, meta)
    ctx = Ctx(st, al)
    booked, new, updates, seen = {}, [], [], []
    rows = sv.values().get(spreadsheetId=SHEET, range='Meetings!A2:N').execute().get('values', [])
    hdr = sv.values().get(spreadsheetId=SHEET, range='Meetings!K1:N1').execute().get('values', [[]])[0]
    hdr = hdr + [''] * (4 - len(hdr))
    if hdr != MEET_HDR[10:]: sv.values().update(spreadsheetId=SHEET, range='Meetings!K1:N1', valueInputOption='RAW', body={'values': [MEET_HDR[10:]]}).execute()
    have = {}   # key -> (row number, row values)
    for i, r in enumerate(rows, start=2):
        r = [str(x) for x in r] + [''] * (14 - len(r))
        if r[10].strip(): have[r[10].strip()] = (i, r)
    name_of = {norm(v['name']): k for k, v in ctx.leads.items()}
    sender_of = lambda lid: (al.get(lid) or {}).get('sender') or (ctx.hr().get(lid) or {}).get('sender') or ''
    # (a) Calendly, our event type only
    tok = env('CALENDLY_VISTAMAILS_API_KEY')
    all_inv = bookings(tok) if tok else []
    if not tok: say('CALENDLY_VISTAMAILS_API_KEY missing: Calendly skipped')
    by_uri = {i['uri']: i for ev, i in all_inv}
    for ev, inv in sorted(all_inv, key=lambda x: iso(x[1].get('created_at')) or datetime.datetime.now(UTC)):
        if inv.get('rescheduled') and inv.get('new_invitee') in by_uri: continue
        key = chain_root(inv, by_uri)
        start = iso(ev['start_time']).astimezone(BERLIN).strftime('%Y-%m-%d %H:%M')
        active = ev.get('status') == 'active' and inv.get('status') == 'active'
        cell = start + ('' if active else ' (canceled)')
        src = 'VistaMails Calendly booking ' + datetime.datetime.now(BERLIN).strftime('%Y-%m-%d')
        if key in have:
            rn, r = have[key]
            if r[6] != cell: updates.append({'range': 'Meetings!G%d' % rn, 'values': [[cell]]}); r[6] = cell
            lid = name_of.get(norm(r[13])) if r[13] else (lid_of(r[3]) if r[3] and lid_of(r[3]) in ctx.all_ids() else None)
            try:
                if enrich_row(ctx, r, lid): updates.append({'range': 'Meetings!B%d:F%d' % (rn, rn), 'values': [r[1:6]]})
            except Exception as e: say('enrich failed for', r[0], repr(e)[:120]); ctx.errs.append((r[0], repr(e)[:120]))
            if active and lid: booked[lid] = start; on_booked(ctx, lid, r, src)
            if active: slack_meeting(ctx, r, key)
            seen.append((key, r, lid, active))
            continue
        res = resolve(ctx, inv, ev)
        row = meet_row(ctx, res, inv, ev, cell, key)
        new.append(row); have[key] = (None, row)
        if active and res['lead']: booked[res['lead']] = start; on_booked(ctx, res['lead'], row, src)
        if active: slack_meeting(ctx, row, key)
        seen.append((key, row, res['lead'], active))
        say('booking', inv.get('name'), inv.get('email'), start, '->', row[0], '|', res['how'])
    # (b) HeyReach tag containing "meeting", (c) typed date in the Presentation Log
    cvs = ctx.convs()
    pl = sv.values().get(spreadsheetId=SHEET, range="'%s'!%s2:%s" % (TAB, col(6), MEET_DATE_COL)).execute().get('values', [])
    w = NA + 4 - 5
    typed = {}
    for r in pl:
        r = [str(x) for x in r] + [''] * (w - len(r))
        if r[0].strip() and r[w - 1].strip(): typed[r[0].strip().lower()] = r[w - 1].strip()
    want = {}   # lid -> (source sentence, date)
    for lid, cv in cvs.items():
        mt = [t for t in cv['tags'] if 'meeting' in t[0].lower()]
        if mt: want[lid] = ('HeyReach tag "%s"' % mt[0][0], mt[0][1])
    for lid, d in typed.items():
        want[lid] = (want[lid][0] + ' + typed date', d) if lid in want else ('Presentation Log: Meeting booked date', d)
    cal_leads = {lid_of(r[3]) for k, (rn, r) in have.items() if k.startswith('http') and r[3]}
    for lid, (how, date) in want.items():
        if lid in cal_leads: continue   # the Calendly row is the meeting row of this lead
        a, cv = al.get(lid) or {}, cvs.get(lid)
        pr = (cv or {}).get('profile') or {}
        name = a.get('name') or ctx.fact(lid)['name'] or ('%s %s' % (pr.get('firstName') or '', pr.get('lastName') or '')).strip() or lid
        src = 'VistaMails meeting (%s) %s' % (how, datetime.datetime.now(BERLIN).strftime('%Y-%m-%d'))
        if lid in have:
            rn, r = have[lid]
            if typed.get(lid) and r[6] != typed[lid]: r[6] = typed[lid]; updates.append({'range': 'Meetings!G%d' % rn, 'values': [[r[6]]]})
            if r[12] != how: r[12] = how; updates.append({'range': 'Meetings!M%d' % rn, 'values': [[how]]})
            try:
                if enrich_row(ctx, r, lid): updates.append({'range': 'Meetings!B%d:F%d' % (rn, rn), 'values': [r[1:6]]})
            except Exception as e: say('enrich failed for', name, repr(e)[:120]); ctx.errs.append((name, repr(e)[:120]))
            if not r[7].strip() and cv:
                t = thread_text(cv, name, sender_of(lid))
                if t: r[7] = t; updates.append({'range': 'Meetings!H%d' % rn, 'values': [[t]]})
        else:
            r = [name, '', '', 'https://www.linkedin.com/in/%s/' % lid, '', '', date, thread_text(cv, name, sender_of(lid)) if cv else '', '', '', lid, '', how, '']
            try: enrich_row(ctx, r, lid)
            except Exception as e: say('enrich failed for', name, repr(e)[:120]); ctx.errs.append((name, repr(e)[:120]))
            new.append(r); have[lid] = (None, r)
            say('meeting:', name, date, '|', how)
        booked[lid] = r[6]; on_booked(ctx, lid, r, src); slack_meeting(ctx, r, lid)
        seen.append((lid, r, lid, True))
    if updates: sv.values().batchUpdate(spreadsheetId=SHEET, body={'valueInputOption': 'RAW', 'data': updates}).execute()
    if new: sv.values().append(spreadsheetId=SHEET, range='Meetings!A1', valueInputOption='RAW', insertDataOption='INSERT_ROWS', body={'values': new}).execute()
    # lead id -> HeyReach account of every Meetings lead, for the Performance tab meeting rate (jobs/vista_perf.py extra_meetings)
    acc = {}
    for k, (rn, r) in have.items():
        lid = lid_of(r[3]) if r[3] else (k if not k.startswith('http') else '')
        if not lid or r[0].startswith('INTERNAL'): continue
        s = sender_of(lid)
        if s in SENDERS: acc[lid] = SENDERS[s]
    save_json(MEET_ACC, acc)
    report(st, issues_of(ctx, seen))
    say('meetings:', len(have), 'rows,', len(new), 'new,', len(updates), 'cell updates,', len(booked), 'active lead meetings')
    return booked, bool(new)


# ---------- main ----------
def run():
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    st = load_json(STATE, {})
    read_events(st)
    save_json(STATE, st)   # events are consumed, save before anything that can fail
    sv = sheets_svc()
    meta = ensure_tab(sv)
    sys.path.insert(0, HUB)
    import hr_perf
    from jobs.vista_perf import CFG
    hr_perf.ensure_tabs(CFG, sv)
    failed, al, booked, new = None, {}, {}, False
    try:
        al = leads_now(st)
    except Exception as e:
        failed = e; say('HEYREACH LEADS FAILED:', repr(e))
    try:
        if al or not failed: booked, new = sync_meetings(sv, st, al, meta)
    except Exception as e:
        failed = failed or e; say('MEETINGS SYNC FAILED:', repr(e))
    save_json(STATE, st)   # acted / slacked / phones are consumed
    try:
        if al or not failed: sync_log(sv, st, al, booked)
    except Exception as e:
        failed = failed or e; say('LOG SYNC FAILED:', repr(e))
    try:
        copy_links(sv, copy_docs(st))
    except Exception as e:
        say('COPY DOCS FAILED:', repr(e))
    save_json(STATE, st)
    try:
        hr_perf.open_rate_cells(CFG, {k: tuple(v) for k, v in st.get('open_rate_per', {}).items()}, sv)
        if new: hr_perf.run(CFG); say('performance tab refreshed after a new meeting')
    except Exception as e:
        failed = failed or e; say('PERFORMANCE FAILED:', repr(e))
    status_line(st, failed)
    save_json(STATE, st)
    say('tracked decks:', len(st.get('slugs', {})))
    if failed: raise failed


def main():
    try: run()
    except Exception as e:
        crashed(e); raise


if __name__ == '__main__':
    main()
