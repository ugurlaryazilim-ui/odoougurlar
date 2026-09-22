# Odoo Reklam Analiz & Optimizasyon Modülü — Proje Yol Haritası

**Hedef sürüm:** Odoo 19
**Kapsam:** Meta Ads + Google Ads tam entegrasyonu (raporlama + kampanya oluşturma/düzenleme) + çoklu-LLM destekli öneri motoru

---

## 1. Mimari Genel Bakış

Modülü tek bir dev blok yerine bağımsız kurulabilen alt modüllere bölmek Odoo pratiğine uygun ve bakımı kolaylaştırır (OCA yaklaşımı).

```
ads_suite/
├── ads_base/              # Platform-bağımsız veri modeli, ortak UI, dashboard
├── ads_meta_connector/    # Meta Marketing API entegrasyonu
├── ads_google_connector/  # Google Ads API entegrasyonu
├── ads_ai_advisor/        # Çoklu-LLM öneri motoru
├── ads_crm_bridge/        # CRM/Sales/Accounting ile köprü (opsiyonel, v2)
```

### Neden ayrı modüller?
- Müşteri sadece Google Ads kullanıyorsa `ads_meta_connector`'ı kurmaz.
- `ads_ai_advisor` bağımsız geliştirilip farklı LLM sağlayıcılarıyla test edilebilir.
- Odoo Apps Store / OCA'ya yayınlarken her biri ayrı değerlendirilebilir.

---

## 2. Veri Modeli (ads_base)

Platformdan bağımsız, normalize edilmiş modeller — hem Meta hem Google verisini aynı yapıya map ederiz:

| Model | Açıklama |
|---|---|
| `ads.account` | Reklam hesabı (platform: meta/google, credential referansı) |
| `ads.campaign` | Kampanya (platform_campaign_id, objective, status, budget) |
| `ads.adset` | Reklam seti / ad group |
| `ads.ad` | Reklam / kreatif |
| `ads.metric.daily` | Günlük metrik satırı (impressions, clicks, spend, conversions, ctr, cpc, cpa, roas) |
| `ads.recommendation` | LLM/kural motorunun ürettiği öneri (severity, kategori, açıklama, durum: yeni/uygulandı/reddedildi) |
| `ads.sync.log` | Senkronizasyon geçmişi ve hata takibi |

`ads.metric.daily` üzerinde `campaign_id`, `date` bileşik indeksi olmalı — büyük hesaplarda performans için kritik.

---

## 3. Meta Ads Entegrasyonu (ads_meta_connector)

- **OAuth:** Meta App oluşturma, `ads_management` ve `ads_read` izinleri, System User veya uzun ömürlü token akışı.
- **Senkronizasyon:** Ads Insights API üzerinden kampanya/adset/ad ve günlük metrik çekimi (cron ile, varsayılan günlük + isteğe bağlı near-real-time).
- **Büyük hesaplar için:** Asenkron rapor (async insights job) + polling mekanizması — senkron sorgular büyük tarih aralıklarında zaman aşımına uğrayabilir.
- **Kampanya yazma işlemleri:** Kampanya/adset/ad oluşturma ve bütçe güncelleme — **Advantage+ Shopping/App kampanyaları için Advantage+ yapısına göre tasarlanmalı**, çünkü klasik oluşturma/kopyalama uçları bu tiplerde kapatıldı (19 Mayıs 2026'dan itibaren tüm API sürümlerinde geçerli).
- **API sürümü:** Marketing API v25.0 (Şubat 2026) — sürüm numarasını konfigürasyondan yönetilebilir tutun, Meta sürümleri ~2 yılda bir deprecate ediyor.
- **Referans:** https://developers.facebook.com/documentation/ads-commerce/marketing-api/insights

## 4. Google Ads Entegrasyonu (ads_google_connector)

- **OAuth:** Google Cloud proje + OAuth2 client (client_id/secret + refresh_token), ayrıca **developer token** (Google Ads API erişimi için ayrı onay süreci gerektirir — bu, projeye en çok zaman alacak dış bağımlılıklardan biri, erkenden başvurun).
- **Okuma:** GAQL (Google Ads Query Language) ile `customers/{customerId}/googleAds:search` üzerinden kampanya/ad group/anahtar kelime/metrik sorguları.
- **Yazma:** `campaigns:mutate`, `adGroups:mutate`, `campaignBudgets:mutate` uçları.
- **Manager hesap (MCC) desteği:** Ajans senaryosu düşünülüyorsa tek bir MCC altında çoklu müşteri hesabına erişim planlanmalı.
- **Referans:** https://developers.google.com/google-ads/api

## 5. Çoklu-LLM Öneri Motoru (ads_ai_advisor)

Tek bir sağlayıcıya bağımlı kalmamak için **provider-agnostic bir soyutlama katmanı** öneriyorum:

```
ads_ai_advisor/
├── models/
│   ├── ai_provider.py       # ads.ai.provider (Claude / Gemini / OpenAI vb. — API key, model adı, aktif/pasif)
│   ├── ai_advisor.py        # Ortak prompt şablonları, response parsing
│   └── recommendation.py    # Kural motoru + LLM çıktısının birleştirildiği yer
```

**Yaklaşım — hibrit sistem öneriyorum, sadece LLM'e bırakmayın:**
1. **Kural katmanı (deterministik, ücretsiz, hızlı):** CPA hedef üstü, frequency > eşik, CTR düşüşü, bütçe tükenmesi gibi durumlar için eşik tabanlı tetikleyiciler. Bunlar her zaman çalışır, LLM'e ihtiyaç duymaz.
2. **LLM katmanı (doğal dil analizi/özetleme):** Kural motorunun tespit ettiği anomalileri alıp "neden olmuş olabilir, ne önerilir" şeklinde bağlamsal, okunabilir açıklama üretir. Ham veriyi LLM'e göndermek yerine önce agregatlar/özetler hazırlayıp ona gönderin — hem token maliyeti düşer hem tutarlılık artar.

**Sağlayıcı seçimi hakkında:** "En iyi" tek bir model yok — kullanım şekline göre değişir:
- Uzun bağlamda çok kampanyalı, çok haftalık veriyi tek seferde analiz etmek istiyorsanız büyük context window'lu modeller (Claude, Gemini) avantajlı.
- Maliyet/hız önceliğiyse daha küçük/ucuz modeller (Haiku, Gemini Flash gibi) günlük özet üretiminde yeterli olur, büyük analizler için daha güçlü model (Sonnet/Opus, Gemini Pro) kullanılabilir.
- Bunu kod seviyesinde sabitlemek yerine `ads.ai.provider` modelinde konfigüre edilebilir bıraktım — müşteri hangi API key'e sahipse onu kullanır, hatta görev tipine göre (hızlı günlük özet vs. derin haftalık analiz) farklı model seçilebilir.

Anthropic API kullanımı için genel model/versiyon bilgisi zamanla değişebileceğinden, geliştirme sırasında güncel model adlarını ve fiyatlandırmayı https://docs.claude.com üzerinden teyit edin; Google tarafı için https://ai.google.dev/gemini-api/docs.

## 6. Odoo 19 Uyumluluğu — Dikkat Edilecekler

- Odoo 19, Eylül 2025'te yayınlandı ve OWL frontend migrasyonu, performans ve AI odaklı workflow'lara ağırlık veriyor — dashboard'ları OWL component olarak kurgulamak gelecek sürümlerle uyumu kolaylaştırır.
- Resmi geliştirici dokümantasyonu (Server framework 101, model/view/security temelleri): https://www.odoo.com/documentation/latest/developer.html
- Manifest'te `'version': '19.0.1.0.0'` formatı kullanılmalı.

## 7. Git / Proje Yol Haritası (Milestone Bazlı)

**M0 — Kurulum (1 hafta)**
- Repo iskeleti, `ads_base` modülünün model/view/security taslağı
- Meta App ve Google Ads developer token başvurularının başlatılması (bu ikisi onay bekleme süresi olduğu için en erken tetiklenmeli)

**M1 — Meta MVP (2-3 hafta)**
- OAuth akışı, kampanya/adset/ad senkronizasyonu, günlük insight çekimi
- Temel dashboard (kanban/pivot/graph view)

**M2 — Google Ads MVP (2-3 hafta)**
- OAuth + GAQL senkronizasyonu, aynı `ads_base` modeline map

**M3 — Kural tabanlı öneri motoru (1-2 hafta)**
- Eşik tabanlı tetikleyiciler, `ads.recommendation` üretimi, bildirim (activity/e-posta)

**M4 — LLM entegrasyonu (2 hafta)**
- Provider-agnostic katman, prompt şablonları, ilk sağlayıcı (Claude) ile uçtan uca test, ardından Gemini desteği

**M5 — Yazma işlemleri / tam entegrasyon (2-3 hafta)**
- Kampanya/bütçe oluşturma-düzenleme (Meta Advantage+ yapısına uygun, Google mutate uçları)
- Değişiklik onay akışı (LLM önerisini kullanıcı onaylamadan uygulamama seçeneği — güvenlik için önemli)

**M6 — Cilalama & yayın**
- Multi-company/multi-currency testleri, performans testi (yüksek hacimli hesaplarda cron süresi), Odoo Apps Store / OCA hazırlığı, dokümantasyon

### Branch stratejisi önerisi
- `main` (stabil), `dev` (entegrasyon), her modül için `feature/ads-meta-*`, `feature/ads-google-*`, `feature/ads-ai-*` branch'leri
- Her milestone sonunda `dev` → `main` release tag'i (`v0.1.0-meta-mvp` gibi)

---

## 8. Riskler / Erken Ele Alınması Gerekenler

1. **Google Ads developer token onayı** — süreç haftalar sürebilir, projeye en başta başlatılmalı.
2. **Meta Advantage+ deprecation'ı** — kampanya yazma özelliği bu yapıya göre tasarlanmazsa kısa sürede kırılır.
3. **Rate limit / async job yönetimi** — özellikle çok hesaplı (ajans) kullanımda cron zamanlamasının API kotalarını aşmaması gerekir.
4. **LLM maliyeti** — ham veri yerine agregat gönderme disiplini baştan kurulmazsa token maliyeti hızla büyür.
5. **Veri gizliliği** — reklam hesabı verisi ve API key'lerin Odoo'da nasıl saklanacağı (encrypted fields / `ir.config_parameter` vs. ayrı credential modeli) baştan netleştirilmeli.

---

## Kaynak Linkleri

- Odoo Geliştirici Dokümantasyonu: https://www.odoo.com/documentation/latest/developer.html
- Odoo 19 Release Notes: https://odoo.com/odoo-19-release-notes
- Meta Ads Insights API: https://developers.facebook.com/documentation/ads-commerce/marketing-api/insights
- Meta Marketing API Changelog (v25.0): https://developers.facebook.com/docs/graph-api/changelog/version25.0
- Google Ads API: https://developers.google.com/google-ads/api
