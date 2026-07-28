import requests as http_requests
import base64
import time
from datetime import datetime, timedelta
from collections import defaultdict

api_key = self.env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.fal_api_key', '')
headers = {'Authorization': f'Key {api_key}'}
cr = self.env.cr

print("=" * 60)
print("TOPLU GORSEL KURTARMA v3 (Duzeltilmis Prompt Eslestirme)")
print("=" * 60)

# ============================================================
# 1) Onceki yanlis yuklenen attachment'lari temizle
# ============================================================
print("\n--- Onceki yanlis yuklenen attachment'lari temizleniyor ---")
cr.execute("""
    SELECT a.id
    FROM ir_attachment a
    WHERE a.res_model='ai.studio.generation'
      AND a.res_field='generated_image'
      AND a.create_date > '2026-07-28 11:00:00'
""")
wrong_ids = [r[0] for r in cr.fetchall()]
if wrong_ids:
    cr.execute("DELETE FROM ir_attachment WHERE id = ANY(%s)", (wrong_ids,))
    cr.commit()
    print(f"  {len(wrong_ids)} yanlis attachment silindi")
else:
    print("  Temizlenecek attachment yok")

# Eksik generation'lari cek
cr.execute("""
    SELECT g.id, g.session_id, g.photo_type, s.create_date
    FROM ai_studio_generation g
    JOIN ai_studio_session s ON s.id = g.session_id
    LEFT JOIN ir_attachment a ON a.res_model='ai.studio.generation'
        AND a.res_field='generated_image' AND a.res_id=g.id
    WHERE g.state='done' AND a.id IS NULL
    ORDER BY s.create_date
""")
missing = cr.fetchall()

sess_map = defaultdict(lambda: {'gens': {}, 'date': None})
for gen_id, sess_id, ptype, sdate in missing:
    sess_map[sess_id]['gens'][ptype] = gen_id
    sess_map[sess_id]['date'] = sdate

total_gens = len(missing)
total_sess = len(sess_map)
print(f"\nToplam: {total_gens} eksik gorsel, {total_sess} oturum\n")

# fal.ai cache
fal_cache = {}
stats = {'ok': 0, 'fail': 0, 'api_calls': 0, 'api_err': 0, 'skip_detail': 0}

def get_fal_items(sdate):
    cache_key = sdate.strftime('%Y%m%d%H%M')
    if cache_key in fal_cache:
        return fal_cache[cache_key]

    min_dt = (sdate - timedelta(minutes=3)).strftime('%Y-%m-%dT%H:%M:%SZ')
    max_dt = (sdate + timedelta(minutes=7)).strftime('%Y-%m-%dT%H:%M:%SZ')

    for attempt in range(3):
        try:
            p = {
                'endpoint_id': 'fal-ai/nano-banana-2/edit',
                'start': min_dt, 'end': max_dt,
                'status': 'success', 'limit': 50, 'expand': 'payloads',
            }
            r = http_requests.get('https://api.fal.ai/v1/models/requests/by-endpoint',
                                  headers=headers, params=p, timeout=30)
            stats['api_calls'] += 1
            if r.status_code == 200:
                items = r.json().get('items', [])
                fal_cache[cache_key] = items
                return items
            elif r.status_code == 429:
                time.sleep(5 * (attempt + 1))
            else:
                stats['api_err'] += 1
                time.sleep(2)
        except:
            stats['api_err'] += 1
            time.sleep(2)
    fal_cache[cache_key] = []
    return []


def detect_prompt_type(prompt_text):
    """Prompt'un ilk 100 karakterinden photo_type belirle"""
    p = (prompt_text or '').upper()[:150]
    if 'SHOW THE BACK VIEW' in p or 'BACK VIEW' in p[:80]:
        return 'back'
    if 'SHOW THE SIDE VIEW' in p or 'SIDE VIEW' in p[:80] or 'THREE-QUARTER VIEW' in p[:80]:
        return 'side'
    if 'FRONT VIEW' in p[:80]:
        return 'front_gen'
    return 'unknown'


print("Eslestirme ve yukleme basliyor...\n")

for idx, (sess_id, sinfo) in enumerate(sess_map.items()):
    sdate = sinfo['date']
    gens = sinfo['gens']

    items = get_fal_items(sdate)
    time.sleep(0.5)

    if not items:
        stats['fail'] += len(gens)
        if idx % 50 == 0:
            print(f"[{idx}/{total_sess}] Sess {sess_id}: fal.ai'de istek yok | OK:{stats['ok']} FAIL:{stats['fail']}")
        continue

    # Garment URL'ye gore grupla
    garment_groups = defaultdict(list)
    for item in items:
        urls = item.get('json_input', {}).get('image_urls', [])
        if urls:
            garment_groups[urls[0]].append(item)

    # En yakin grubu sec
    best_group = None
    best_score = 999999
    sdate_ts = sdate.timestamp()
    for gurl, gitems in garment_groups.items():
        timestamps = []
        for item in gitems:
            ended = item.get('ended_at', '')
            if ended:
                try:
                    clean = ended.replace('Z', '').split('.')[0].split('+')[0]
                    timestamps.append(datetime.fromisoformat(clean).timestamp())
                except:
                    pass
        if timestamps:
            avg = sum(timestamps) / len(timestamps)
            score = abs(avg - sdate_ts)
            if score < best_score:
                best_score = score
                best_group = gitems

    if not best_group:
        stats['fail'] += len(gens)
        continue

    # Istekleri photo_type'a gore sinifla
    typed_items = {'back': [], 'side': [], 'front_gen': [], 'unknown': []}
    for item in best_group:
        prompt = item.get('json_input', {}).get('prompt', '')
        ptype_detected = detect_prompt_type(prompt)
        typed_items[ptype_detected].append(item)

    # Her photo_type icin eslestir ve yukle
    for ptype, gen_id in gens.items():
        try:
            img_url = None

            if ptype == 'front':
                # Front = herhangi bir BACK veya SIDE isteginin image_urls[2]
                source = typed_items['back'] or typed_items['side']
                if source:
                    u = source[0].get('json_input', {}).get('image_urls', [])
                    if len(u) >= 3:
                        img_url = u[2]

            elif ptype == 'back':
                # Back = BACK isteginin ciktisi
                if typed_items['back']:
                    out = typed_items['back'][0].get('json_output', {})
                    imgs = out.get('images', []) if isinstance(out, dict) else []
                    if imgs and imgs[0].get('url'):
                        img_url = imgs[0]['url']

            elif ptype == 'side':
                # Side = SIDE isteginin ciktisi
                if typed_items['side']:
                    out = typed_items['side'][0].get('json_output', {})
                    imgs = out.get('images', []) if isinstance(out, dict) else []
                    if imgs and imgs[0].get('url'):
                        img_url = imgs[0]['url']

            elif ptype == 'detail':
                # Detail = front gorselinden crop (fal.ai'de yoktur)
                # Front varsa front'u koy, en azindan bos olmasin
                source = typed_items['back'] or typed_items['side']
                if source:
                    u = source[0].get('json_input', {}).get('image_urls', [])
                    if len(u) >= 3:
                        img_url = u[2]  # front gorseli koy, sonra Odoo cropper duzeltir
                stats['skip_detail'] += 1

            if img_url:
                resp = http_requests.get(img_url, timeout=30)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    self.env['ir.attachment'].sudo().search([
                        ('res_model', '=', 'ai.studio.generation'),
                        ('res_field', '=', 'generated_image'),
                        ('res_id', '=', gen_id)
                    ]).unlink()
                    self.env['ir.attachment'].sudo().create({
                        'name': 'generated_image',
                        'res_model': 'ai.studio.generation',
                        'res_field': 'generated_image',
                        'res_id': gen_id,
                        'type': 'binary',
                        'datas': base64.b64encode(resp.content).decode(),
                        'mimetype': 'image/jpeg',
                    })
                    cr.commit()
                    stats['ok'] += 1
                else:
                    stats['fail'] += 1
            else:
                stats['fail'] += 1
        except Exception as e:
            stats['fail'] += 1
            try:
                cr.rollback()
            except:
                pass

    if idx % 10 == 0:
        print(f"[{idx}/{total_sess}] OK:{stats['ok']} FAIL:{stats['fail']} API:{stats['api_calls']} ERR:{stats['api_err']}")

print(f"\n{'=' * 60}")
print(f"SONUC: {stats['ok']} basarili, {stats['fail']} basarisiz / {total_gens} toplam")
print(f"API: {stats['api_calls']} cagri, {stats['api_err']} hata")
print(f"Detail (front kullanildi): {stats['skip_detail']}")
print(f"{'=' * 60}")
