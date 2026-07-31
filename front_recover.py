import requests as http_requests
import base64

api_key = self.env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.fal_api_key', '')
headers = {'Authorization': f'Key {api_key}'}

session = self.env['ai.studio.session'].sudo().search([('name', '=', 'AIS/2026/01068')], limit=1)

if session:
    front_gen = self.env['ai.studio.generation'].sudo().search([
        ('session_id', '=', session.id),
        ('photo_type', '=', 'front')
    ], limit=1)

    back_req_id = '019f7096-b897-7810-8289-1077da140120'
    resp = http_requests.get(
        'https://api.fal.ai/v1/models/requests/by-endpoint',
        headers=headers,
        params={'endpoint_id': 'fal-ai/nano-banana-2/edit', 'expand': 'payloads'},
        timeout=30
    )
    items = resp.json().get('items', [])
    back_item = next((x for x in items if x.get('request_id') == back_req_id), None)

    if not back_item:
        print("❌ Arka yüz isteği fal.ai geçmişinde bulunamadı!")
    else:
        inp = back_item.get('json_input', {})
        input_urls = inp.get('image_urls', [])
        print("=== ARKA YÜZ GİRDİ URL'LERİ ===")
        for idx, u in enumerate(input_urls):
            print(f"  [{idx}]: {u}")

        if len(input_urls) >= 3:
            front_url = input_urls[2]
            print(f"\n✅ Ön yüz URL: {front_url}")

            # Eski attachment'ı sil
            old = self.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'ai.studio.generation'),
                ('res_field', '=', 'generated_image'),
                ('res_id', '=', front_gen.id)
            ])
            if old:
                old.unlink()
                print("  Eski attachment silindi.")

            # Görseli indir ve yükle
            img_resp = http_requests.get(front_url)
            if img_resp.status_code == 200:
                img_b64 = base64.b64encode(img_resp.content).decode('utf-8')
                self.env['ir.attachment'].sudo().create({
                    'name': 'generated_image',
                    'res_model': 'ai.studio.generation',
                    'res_field': 'generated_image',
                    'res_id': front_gen.id,
                    'type': 'binary',
                    'datas': img_b64,
                    'mimetype': 'image/png',
                })
                self.env.cr.execute(
                    'UPDATE ai_studio_generation SET fal_request_id = %s WHERE id = %s',
                    ('EXTRACTED_FROM_BACK', front_gen.id)
                )
                self.env.cr.commit()
                print("\n🎉 ÖN YÜZ GÖRSELİ BAŞARIYLA YÜKLENDİ!")
            else:
                print(f"❌ Görsel indirilemedi: HTTP {img_resp.status_code}")
        else:
            print(f"❌ Yeterli input URL yok ({len(input_urls)} adet)")
else:
    print("❌ Oturum bulunamadı!")
