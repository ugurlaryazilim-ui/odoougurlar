# fal.ai × FASHN — Ürün Giydirme Tam Rehberi

> Hazırlayan: AI Araştırma Notu | Güncelleme: Haziran 2026  
> Kaynak: fal.ai API dokümantasyonu, FASHN resmi blogu, 2026 sektör araştırmaları

---

## İçindekiler

1. [Model Seçimi: v1.5 vs v1.6](#1-model-seçimi-v15-vs-v16)
2. [Kalite Modları](#2-kalite-modları)
3. [Kritik API Parametreleri](#3-kritik-api-parametreleri)
4. [Girdi Görseli Kuralları](#4-girdi-görseli-kuralları)
5. [Tutarlılık İçin Workflow](#5-tutarlılık-i̇çin-workflow)
6. [Kategori Bazlı Öneriler](#6-kategori-bazlı-öneriler)
7. [Kaçınılacaklar](#7-kaçınılacaklar)
8. [Örnek API Çağrısı](#8-örnek-api-çağrısı)
9. [Maliyet Hesabı](#9-maliyet-hesabı)
10. [Genel AI Ürün Giydirme Trickler](#10-genel-ai-ürün-giydirme-trickler)

---

## 1. Model Seçimi: v1.5 vs v1.6

| Özellik | v1.5 | v1.6 |
|---|---|---|
| **Endpoint** | `fal-ai/fashn/tryon/v1.5` | `fal-ai/fashn/tryon/v1.6` |
| **Native çözünürlük** | 576 × 864 px | 864 × 1296 px (maks) |
| **Fiyat** | $0.075 / gen | $0.075 / gen |
| **Kararlılık** | Proven, production-ready | En güncel, daha iyi detay |
| **Cilt dokusu (Quality mode)** | Orta | Belirgin iyileşme |
| **Anatomik doğruluk** | İyi | Daha iyi (bacaklar, eller) |
| **Grafik baskı koruması** | İyi | Mükemmel |

**Öneri:** Yeni projeler için doğrudan **v1.6** kullan. Stabil pipeline varsa v1.5'ten geçişi test et, aynı seed ile karşılaştır.

> ⚠️ **Önemli:** v1.6, giriş görselinin çözünürlüğünü aşmaz. Model fotoğrafın 600px ise çıktı da 600px civarı olur — v1.6'nın avantajı kaybolur. **Giriş görselini en az 768px yükseklikte ver.**

---

## 2. Kalite Modları

### Performance — ~7 saniye
- Hız önceliklidir
- v1.5 Balanced modundan bile daha iyi görsel kalite
- **Ne zaman:** Önizleme, A/B test, toplu ön eleme

### Balanced — ~10 saniye
- Hız ve kalite dengesi
- Grafik baskı, desen, doku detayları belirgin şekilde iyileşir
- **Ne zaman:** Standart katalog üretimi, PDP görselleri

### Quality — ~19 saniye
- Cilt dokusu, anatomik doğruluk, gerçekçi giysi-vücut entegrasyonu maksimize edilir
- Aydınlatma uyumu, kol/boyun geçişleri çok daha doğal
- **Ne zaman:** Hero görseller, kampanya içerikleri, yüksek profilli ürünler

---

## 3. Kritik API Parametreleri

### `garment_photo_type`
```
"model" | "flat-lay" | "auto"
```
- `flat-lay` → Flatlay veya ghost mannequin fotoğrafı. **Bu seçenek olmadan** iç etiket, hanger clip gibi istenmeyen detaylar çıktıya taşınır.
- `model` → Giysinin başka bir modelde olduğu fotoğraf
- `auto` → Otomatik algılama (daha yavaş, pipeline için önerilmez)

**Kural:** Kaynak tipini her zaman elle belirt, `auto`'ya bırakma.

---

### `seed`
```
integer, varsayılan: 42
```
- Aynı seed + aynı girdi = deterministik çıktı
- **Katalog tutarlılığı için tüm SKU'larda aynı seed'i sabitle**
- Farklı varyasyon görmek istiyorsan seed'i değiştir (42, 123, 777...)

---

### `num_samples`
```
1 – 4, varsayılan: 1
```
- Tek API çağrısında 4 varyasyon üretir
- Başarılı sonuç olasılığını artırır, sıralı çağrı yapmaktan daha verimli
- **Öneri:** Yeni bir SKU veya model tipini ilk kez denerken `num_samples: 4` kullan, en iyisini seç. Sonra seed'i sabitle.

---

### `mode`
```
"performance" | "balanced" | "quality"
```
Bkz. [Kalite Modları](#2-kalite-modları)

---

### `cover_feet`
```
boolean, varsayılan: false
```
- `false` → Model'in ayakkabıları/çıplak ayakları korunur
- `true` → Ayakların üstüne kıyafet üretilir

**Ne zaman açık olmalı:** Uzun etek, maxi dress, gelinlik, trençkot gibi ayakları örtmesi gereken her parça. Kapalıyken model uzun kıyafetle birlikte ayakkabılarını görünür bırakır — garip sonuç.

---

### `adjust_hands`
```
boolean, varsayılan: false
```
- `false` → Eller olduğu gibi korunur, gerekirse kol kıvrılır
- `true` → Uzun kol elleri örtebilir, eldiven çıkarılabilir, cep içindeki el çıkarılabilir

**Ne zaman açık olmalı:** Uzun kollu kazak, sweatshirt, trençkot, blazer. Kapalıyken model uzun kolu kıvırarak eli açıkta bırakır.

---

### `restore_background`
```
boolean, varsayılan: false
```
- Karmaşık arka planda detaylar (araba, mobilya, mekan öğeleri) kayboluyorsa `true` yap
- **Trade-off:** Süre artar
- Sade studio arka planı için gerekli değil

---

### `restore_clothes`
```
boolean, varsayılan: false
```
- Kıyafet swapı sırasında diğer parçanın (örn. etekteki ip bağı, aksesuar) kaybolmasını önler
- **Dikkat:** Her durumda iyi çalışmaz. Yeni bir kıyafet kombinasyonunda test et, varsayılan olarak kapalı bırak.

---

### `output_format`
```
"png" | "jpeg", varsayılan: "png"
```
- `png` → En yüksek kalite, daha büyük dosya
- `jpeg` → Daha hızlı işlem, biraz daha küçük dosya
- **Katalog için her zaman `png`**

---

### `long_top` (v1.6 ek parametre)
Uzun üst giysilerin (tunik, uzun sweatshirt) alt kısımlarının doğru işlenmesi için. Uzun üst parça giydirilirken etkinleştir.

---

## 4. Girdi Görseli Kuralları

### Model Fotoğrafı
| Kural | Detay |
|---|---|
| **Çözünürlük** | En az 768px yükseklik. v1.6 maksimum için 864px+ tercih et |
| **Çerçeveleme** | Tam vücut veya ¾ boy. Baş kesilmiş, bel kesimli görseller poz/garment hizalamasını bozar |
| **Poz** | Kollar vücuttan hafif açık, nötr duruş. Karmaşık pozlar (çömelme, yatma) warp sorununa yol açar |
| **Arka plan** | Sade, düz tercih edilir. Karmaşık sahne → `restore_background: true` |
| **Işık** | Yumuşak, düzgün dağılımlı. Sert gölgeler çıktıya sızar |
| **Hizalama** | Model ve ürün fotoğrafının pozunun mümkün olduğunca yakın olması kritik — minimal warp = daha iyi sonuç |

### Ürün (Garment) Fotoğrafı
| Kural | Detay |
|---|---|
| **Arka plan** | Beyaz veya şeffaf. Sahne detaylı arka plan → model yanılır |
| **Tercih edilen tip** | Flatlay veya ghost mannequin. Katlanmış, çok kıvrımlı görsel detay kaybına yol açar |
| **Aksesuar** | Yükleme yapılan görselde yüzük, kemer, şapka gibi swaplamak istemediğin öğeleri çıkar |
| **Etiket** | İç etiket görünüyorsa `garment_photo_type: "flat-lay"` ile gider |
| **Tek parça** | Her yüklemede tek kıyafet parçası. Üst + alt birlikte yükleme detay düşürür |
| **Çözünürlük** | Ürün fotoğrafı yüksek çözünürlüklü olmalı. Model fotoğrafıyla benzer çözünürlük dengesi ideal |

---

## 5. Tutarlılık İçin Workflow

### Katalog üretimi için önerilen pipeline

```
1. Referans model fotoğrafını seç ve sabitle
2. Seed'i belirle (örn. 42) ve tüm katalog boyunca kullan
3. mode: "balanced" ile standart çekim
4. garment_photo_type her SKU için elle belirt
5. İlk SKU için num_samples: 4 ile test, seed'i onayla
6. Geri kalan SKU'lar için num_samples: 1 ile toplu üretim
7. Hero görseller için aynı girdi + mode: "quality" ile yeniden çalıştır
```

### Stil Kılavuzu Oluştur
- Tüm katalogda aynı model kimliği → aynı yüz, ten tonu, vücut oranı
- Aynı arka plan türü (sade studio veya lifestyle — karıştırma)
- Aynı poz kategorisi (frontal, ¾, full body — tutarlı kal)
- Aynı ışık yönü referansı

---

## 6. Kategori Bazlı Öneriler

### Üst Giysi (T-shirt, bluz, gömlek)
- `garment_photo_type: "flat-lay"`
- `adjust_hands: false` (kısa kol için)
- `mode: "balanced"` yeterli

### Uzun Kollu (Kazak, sweatshirt, ceket)
- `adjust_hands: true`
- `mode: "balanced"` veya `"quality"`

### Alt Giysi (Pantolon, etek, şort)
- `garment_photo_type: "flat-lay"`
- `cover_feet: false` (çoğu durumda)

### Uzun Etek / Maxi Dress / Gelinlik
- `cover_feet: true` — zorunlu
- `mode: "quality"` — önerilir
- `long_top: true` (uygulanabilirse)

### Takım Elbise / Blazer
- On-model ürün fotoğrafı daha iyi sonuç verebilir (`garment_photo_type: "model"`)
- `adjust_hands: true`
- `restore_clothes: true` (altta farklı parça varsa)

### Dış Giysi (Trençkot, mont, parka)
- `cover_feet: true` (uzun kesimler için)
- `adjust_hands: true`
- `mode: "quality"`
- `restore_background: true` (lifestyle arka plan varsa)

### Grafik Baskı / Logolu Ürün
- v1.6 kullan — v1.5'e kıyasla grafik koruma belirgin şekilde iyi
- `mode: "balanced"` minimum, mümkünse `"quality"`
- Ürün fotoğrafında desen/baskı net ve düzgün olmalı (kıvrım olmadan)

---

## 7. Kaçınılacaklar

| Sorun | Neden | Çözüm |
|---|---|---|
| Düşük çözünürlüklü girdi | v1.6 upscale etmez, avantaj kaybolur | Min 768px yükseklik |
| `auto` garment_photo_type | Yavaş, hatalı sınıflandırma riski | Elle `flat-lay` veya `model` belirt |
| Farklı seed kullanımı | Katalog tutarsızlığı | Tüm SKU'larda aynı seed |
| Mayo / iç çamaşırı | Eğitim setinde yok, zayıf sonuç | Bu kategori için FASHN uygun değil |
| Çok kıvrımlı/katlanmış ürün fotoğrafı | Yanlış desen mapping | Flatlay'de düzgün, gerilmiş çekim |
| Çok farklı poz (model vs ürün) | Fazla warp → bozulma | Poz hizalamasına dikkat et |
| `restore_clothes` her zaman açık | Yanlış restorasyona yol açabilir | Test et, varsayılan kapalı tut |
| jpeg output formatı | Detay kaybı | Katalog için daima `png` |
| Tek çağrıda üst + alt birlikte | Detay düşer | Parçaları ayrı gönder |

---

## 8. Örnek API Çağrısı

### Standart Katalog (Flatlay → Model)

```javascript
import { fal } from "@fal-ai/client";

const result = await fal.subscribe("fal-ai/fashn/tryon/v1.6", {
  input: {
    model_image: "https://cdn.example.com/model-photo.png",
    garment_image: "https://cdn.example.com/urun-flatlay.png",
    garment_photo_type: "flat-lay",
    mode: "balanced",
    num_samples: 1,
    seed: 42,
    output_format: "png",
    cover_feet: false,
    adjust_hands: false,
    restore_background: false,
    restore_clothes: false,
  },
  logs: true,
  onQueueUpdate: (update) => {
    if (update.status === "IN_PROGRESS") {
      update.logs.map((log) => log.message).forEach(console.log);
    }
  },
});

console.log(result.data.images[0].url);
```

---

### Hero Görsel (Uzun Kol, Kaliteli Çıktı)

```javascript
const result = await fal.subscribe("fal-ai/fashn/tryon/v1.6", {
  input: {
    model_image: "https://cdn.example.com/model-fullbody-768.png",
    garment_image: "https://cdn.example.com/kazak-flatlay.png",
    garment_photo_type: "flat-lay",
    mode: "quality",
    num_samples: 4,           // 4 varyasyon üret, en iyiyi seç
    seed: 42,
    output_format: "png",
    cover_feet: false,
    adjust_hands: true,       // uzun kol → eller örtülsün
    restore_background: true, // sahne varsa
    restore_clothes: false,
  },
});
```

---

### Yeni SKU Keşif (İlk Test)

```javascript
// Önce 4 sample ile dene, seed bul, sonra sabitleyerek toplu üret
const keşif = await fal.subscribe("fal-ai/fashn/tryon/v1.6", {
  input: {
    model_image: "...",
    garment_image: "...",
    garment_photo_type: "flat-lay",
    mode: "balanced",
    num_samples: 4,   // hangisi daha iyi?
    seed: 42,
    output_format: "png",
  },
});

// Beğenilen varyasyonun seed'ini not et ve sabitleyerek devam et
```

---

## 9. Maliyet Hesabı

| Senaryo | Hesap | Maliyet |
|---|---|---|
| 100 SKU, 1 görsel/SKU | 100 × $0.075 | **$7.50** |
| 100 SKU, 4 varyasyon/SKU | 400 × $0.075 | **$30.00** |
| 1000 SKU, balanced | 1000 × $0.075 | **$75.00** |
| Geleneksel çekim (100 SKU) | Stüdyo + model + rötuş | **$5.000 – $15.000** |

> v1.5 ve v1.6 aynı fiyatta. v1.6'yı kullanmak için ekstra maliyet yok.

---

## 10. Genel AI Ürün Giydirme Trickler

Bu bölüm fal.ai'ye özel olmayıp tüm AI giydirme araçları için geçerlidir.

### Tutarlılık Sistemi Kur
- **Photography Style kilitle:** Her SKU için aynı ışık, renk tonu, atmosfer
- **Model kimliğini sabitle:** Tüm katalogda aynı AI model kimliği — aynı yüz, ten, vücut oranı
- **Arka plan kategorisi:** Studio için studio, lifestyle için lifestyle. İkisini aynı katalogda karıştırma

### Girdi Kalitesi = Çıktı Kalitesi
- Ürünü değil çevreyi üret: ürün piksellerini koru, AI yalnızca etrafı oluştursun
- Flatlay'de kıvrım, katlanma, bez iğnesi kalmasın
- Arka plan sade → AI'ın "icat etmesi" azalır → detay korunur

### Skala İçin
- `num_samples: 4` ile ilk test → beğenilen seed'i not al → `num_samples: 1` ile toplu üretim
- Aynı görselden birden fazla arka plan / lifestyle context üret: A/B test için maliyet neredeyse sıfır
- Batch processing: sıralı değil, paralel API çağrısı yap

### Amazon / Platform Uyumu
- AI görsel platform kurallarına teknik olarak uyar, ama **yanıltıcı detay** (olmayan cep, bozuk logo, farklı oran) Amazon'un AI taramasını tetikler → listing kaldırılabilir
- Her üretimden sonra ürün detaylarını kaynak fotoğrafla karşılaştır
- Logo, metin içeren ürünlerde Quality modu kullan ve çıktıyı elle kontrol et

### Zor Kategoriler
| Kategori | Zorluk | Öneri |
|---|---|---|
| Şeffaf kumaş (şifon, tül) | Yüksek | Quality modu + manuel rötuş planla |
| Metalik/parlak yüzey | Yüksek | Birden fazla varyasyon üret |
| Grafik baskı / logolu ürün | Orta | v1.6 + Quality modu |
| Uzun/yapısal ceket | Orta | `adjust_hands: true`, on-model kaynak tercih et |
| Mayo / iç çamaşırı | FASHN için uygun değil | Alternatif araç dene |

---

## Hızlı Referans Kartı

```
✅ Her zaman yap:
  - v1.6 kullan
  - garment_photo_type elle belirt (flat-lay / model)
  - Seed'i sabitle (örn. 42)
  - output_format: "png"
  - Girdi min 768px yükseklik

✅ Uzun kıyafette:
  - cover_feet: true (gelinlik, maxi, trençkot)
  - adjust_hands: true (uzun kol)

✅ İlk test:
  - num_samples: 4, mode: "balanced"

✅ Hero görsel:
  - mode: "quality"

❌ Yapma:
  - garment_photo_type: "auto" (production'da)
  - Farklı seed farklı SKU
  - Düşük çözünürlüklü girdi (<600px)
  - Mayo / iç çamaşırı
  - jpeg output (katalog için)
```

---

*Son güncelleme: Haziran 2026 | fal.ai FASHN v1.6 baz alınarak hazırlanmıştır.*
