import requests as http_requests
import base64
import time
from datetime import datetime, timedelta
from collections import defaultdict

api_key = self.env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.fal_api_key', '')
headers = {'Authorization': f'Key {api_key}'}
cr = self.env.cr

print("=" * 60)
print("TOPLU GORSEL KURTARMA SCRIPTI")
print("=" * 60)

# PHASE 1: Eksik generation'lari cek
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
print(f"Phase 1: {total_gens} eksik gorsel, {total_sess} oturum\n")

# PHASE 2: fal.ai gecmisini saatlik dilimlerle cek
print("Phase 2: fal.ai gecmisi cekiliyor (bu 3-5 dk surebilir)...")

all_fal = []
start_d = datetime(2026, 7, 3, 0, 0, 0)
end_d = datetime(2026, 7, 19, 0, 0, 0)
cur = start_d
hcount = 0

while cur < end_d:
    nxt = cur + timedelta(hours=1)
    try:
        p = {
            'endpoint_id': 'fal-ai/nano-banana-2/edit',
            'start': cur.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'end': nxt.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'status': 'success',
            'limit': 200,
            'expand': 'payloads',
        }
        r = http_requests.get('https://api.fal.ai/v1/models/requests/by-endpoint',
                              headers=headers, params=p, timeout=30)
        items = r.json().get('items', []) if r.status_code == 200 else []
        all_fal.extend(items)
    except:
        items = []
    hcount += 1
    if hcount % 24 == 0:
        print(f"  {cur.strftime('%Y-%m-%d')}: toplam {len(all_fal)} istek")
    time.sleep(0.15)
    cur = nxt

print(f"\nToplam {len(all_fal)} fal.ai istegi cekildi")

# PHASE 3: Istekleri garment URL + zaman ile indexle
# garment_url -> [{item, ended_ts}]
garment_idx = defaultdict(list)
for item in all_fal:
    inp = item.get('json_input', {})
    urls = inp.get('image_urls', [])
    ended = item.get('ended_at', '')
    if urls and ended:
        try:
            ended_clean = ended.replace('Z', '').split('.')[0]
            ets = datetime.fromisoformat(ended_clean).timestamp()
        except:
            ets = 0
        garment_idx[urls[0]].append({'item': item, 'ts': ets})

print(f"{len(garment_idx)} benzersiz garment URL'si\n")

# PHASE 4: Eslestirme ve yukleme
print("Phase 4: Eslestirme ve yukleme basliyor...")

stats = {'ok': 0, 'fail': 0}

for idx, (sess_id, sinfo) in enumerate(sess_map.items()):
    sdate = sinfo['date']
    gens = sinfo['gens']

    try:
        sdate_ts = sdate.timestamp()
    except:
        stats['fail'] += len(gens)
        continue

    # En yakin garment grubunu bul (+-5 dk icinde)
    best_group = None
    best_score = 999999

    for gurl, gitems in garment_idx.items():
        avg_ts = sum(g['ts'] for g in gitems) / len(gitems) if gitems else 0
        score = abs(avg_ts - sdate_ts)
        if score < 420 and score < best_score:  # 7 dakika pencere
            best_score = score
            best_group = [g['item'] for g in gitems]

    if not best_group:
        stats['fail'] += len(gens)
        if idx % 50 == 0:
            print(f"  [{idx}/{total_sess}] {sess_id}: fal grubu bulunamadi")
        continue

    for ptype, gen_id in gens.items():
        try:
            img_url = None

            if ptype == 'front':
                for it in best_group:
                    pr = (it.get('json_input', {}).get('prompt', '') or '').upper()
                    if 'BACK' in pr:
                        u = it.get('json_input', {}).get('image_urls', [])
                        if len(u) >= 3:
                            img_url = u[2]
                            break

            elif ptype in ('back', 'side', 'detail'):
                kw = {'back': ['BACK'], 'side': ['SIDE'], 'detail': ['DETAIL', 'MACRO']}
                targets = kw.get(ptype, [])
                for it in best_group:
                    pr = (it.get('json_input', {}).get('prompt', '') or '').upper()
                    if any(t in pr for t in targets):
                        out = it.get('json_output', {})
                        imgs = out.get('images', []) if isinstance(out, dict) else []
                        if imgs and imgs[0].get('url'):
                            img_url = imgs[0]['url']
                            break

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
            cr.rollback()

    if idx % 20 == 0:
        print(f"  [{idx}/{total_sess}] OK: {stats['ok']}, FAIL: {stats['fail']}")

print(f"\n{'=' * 60}")
print(f"SONUC: {stats['ok']} basarili, {stats['fail']} basarisiz / {total_gens} toplam")
print(f"{'=' * 60}")
