import logging
import requests as http_requests
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

def test_session_recovery(env, session_name='AIS/2026/01071'):
    """Spesifik bir oturum için fal.ai eşleştirmesini test et."""
    cr = env.cr
    api_key = env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.fal_api_key', '')
    
    if not api_key:
        print("HATA: fal.ai API key tanımlı değil!")
        return

    # 1. Oturumu bul
    cr.execute("""
        SELECT s.id, s.name, s.create_date
        FROM ai_studio_session s
        WHERE s.name = %s
    """, (session_name,))
    session = cr.fetchone()
    if not session:
        print(f"HATA: {session_name} oturumu bulunamadı!")
        return

    s_id, s_name, s_date = session
    print(f"=== OTURUM: {s_name} (ID: {s_id}, Tarih: {s_date}) ===")

    # 2. Oturumdaki generation'ları bul
    cr.execute("""
        SELECT g.id, g.photo_type, g.create_date
        FROM ai_studio_generation g
        WHERE g.session_id = %s AND g.state = 'done' AND g.reject_reason_id IS NULL
        ORDER BY g.photo_type
    """, (s_id,))
    gens = cr.fetchall()

    if not gens:
        print("Bu oturumda done durumunda generation bulunamadı.")
        return

    min_date = min(g[2] for g in gens) - timedelta(hours=24)
    max_date = max(g[2] for g in gens) + timedelta(hours=24)

    # 3. fal.ai API'sinden bu geniş tarih aralığındaki istekleri çek
    headers = {'Authorization': f'Key {api_key}'}
    all_requests = []
    cursor = None

    while True:
        params = {
            'endpoint_id': 'fal-ai/nano-banana-2/edit',
            'start': min_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'end': max_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'status': 'success',
            'limit': 100,
            'expand': 'payloads',
        }
        if cursor:
            params['cursor'] = cursor

        try:
            resp = http_requests.get('https://api.fal.ai/v1/models/requests/by-endpoint', headers=headers, params=params, timeout=60)
            data = resp.json()
            items = data.get('items', [])
            all_requests.extend(items)
            if not data.get('has_more') or not data.get('next_cursor'):
                break
            cursor = data.get('next_cursor')
        except Exception as e:
            print(f"API Hatası: {e}")
            break

    print(f"fal.ai'dan Çekilen Toplam Request Sayısı: {len(all_requests)}")

    # 4. Request'leri parse et
    def detect_view(prompt_text):
        if not prompt_text:
            return 'front'
        p = prompt_text.upper()
        if 'SHOW THE BACK VIEW' in p or 'BACK VIEW' in p:
            return 'back'
        elif 'SHOW THE SIDE VIEW' in p or 'SIDE VIEW' in p:
            return 'side'
        elif 'MACRO DETAIL' in p or 'CLOSE-UP DETAIL' in p:
            return 'detail'
        return 'front'

    parsed = []
    for req in all_requests:
        ended_at_str = req.get('ended_at', '')
        if not ended_at_str:
            continue
        try:
            dt = datetime.fromisoformat(ended_at_str.replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            continue
        
        inp = req.get('json_input', {})
        prompt = inp.get('prompt', '') if isinstance(inp, dict) else ''
        v_type = detect_view(prompt)
        
        out = req.get('json_output', {})
        imgs = out.get('images', []) if isinstance(out, dict) else []
        url = imgs[0].get('url', '') if imgs else ''

        parsed.append({
            'req_id': req.get('request_id'),
            'timestamp': dt,
            'view_type': v_type,
            'url': url,
        })

    # 5. Eşleştirme yap
    print("\n=== EŞLEŞTİRME SONUÇLARI ===")
    for gen_id, p_type, g_date in gens:
        best = None
        best_diff = timedelta(days=1)
        for req in parsed:
            if req['view_type'] == p_type:
                diff = abs(req['timestamp'] - g_date)
                if diff < best_diff:
                    best_diff = diff
                    best = req

        if best:
            print(f"✅ Tip: {p_type:<6} (Gen ID: {gen_id}) -> Eşleşti!")
            print(f"   Gen Tarihi: {g_date} | fal.ai Tarihi: {best['timestamp']} | Fark: {best_diff}")
            print(f"   fal Request ID: {best['req_id']}")
            print(f"   Görsel URL    : {best['url']}")
        else:
            print(f"❌ Tip: {p_type:<6} (Gen ID: {gen_id}) -> Eşleşme Bulunamadı!")
