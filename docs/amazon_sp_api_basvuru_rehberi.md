# Amazon SP-API Başvuru ve Odoo Entegrasyon Rehberi

> **Hazırlanma Tarihi:** Temmuz 2026
> **Tecrübe Kaynağı:** ugurlarstore (Ugurlar Grup) — Amazon Türkiye
> **Durum:** ✅ Onaylandı ve Canlı Çalışıyor

> [!IMPORTANT]
> Bu rehber, Amazon SP-API başvurusunun **gerçek bir onay sürecinden** elde edilen tecrübelerle hazırlanmıştır. Amazon'un reddetme sebepleri, eksik bulduğu cevaplar ve onayladığı final metinlerin tamamı bu dokümanda yer almaktadır.

---

## İçindekiler

1. [Genel Bakış ve Ön Koşullar](#1-genel-bakış-ve-ön-koşullar)
2. [Amazon Developer Hesabı Oluşturma](#2-amazon-developer-hesabı-oluşturma)
3. [Solution Provider Profile Formu](#3-solution-provider-profile-formu)
4. [Onaylanan Cevap Şablonları (500 Karakter Limiti)](#4-onaylanan-cevap-şablonları)
5. [Gizlilik Politikası Sayfası Oluşturma](#5-gizlilik-politikası-sayfası-oluşturma)
6. [Amazon'un Sordurduğu Ek Sorular ve Cevapları](#6-amazonun-sorduğu-ek-sorular-ve-cevapları)
7. [Uygulama Oluşturma ve Credentials Alma](#7-uygulama-oluşturma-ve-credentials-alma)
8. [Self-Authorization ve Refresh Token](#8-self-authorization-ve-refresh-token)
9. [Odoo'ya Bağlantı Kurma](#9-odooya-bağlantı-kurma)
10. [Sık Yapılan Hatalar ve Çözümleri](#10-sık-yapılan-hatalar-ve-çözümleri)
11. [Önemli Linkler](#11-önemli-linkler)

---

## 1. Genel Bakış ve Ön Koşullar

### Ne Yapıyoruz?
Amazon Selling Partner API (SP-API) erişimi alarak, Odoo ERP sistemimizdeki özel Amazon entegrasyon modülü aracılığıyla sipariş çekme, stok güncelleme ve fatura oluşturma işlemlerini otomatikleştiriyoruz.

### Neden Resmi Odoo Connector Kullanamıyoruz?
Amazon bu soruyu **mutlaka** soracaktır. Cevabımız:

- Resmi Odoo Amazon Connector **sadece Odoo Enterprise Edition** için geçerlidir
- Biz **Odoo Community Edition** (açık kaynak, self-hosted) kullanıyoruz
- Resmi connector **Türkçe dil desteği** sunmuyor
- Resmi connector **Türkiye marketplace'ini** resmi olarak desteklemiyor
- Resmi connector **Türk e-Fatura (GİB)** uyumluluğu sunmuyor
- Resmi connector **yerel Türk kargo firmaları** (Yurtiçi, Aras, MNG) entegrasyonu sunmuyor

### Ön Koşullar
- [ ] Aktif bir Amazon Seller Central hesabı (Professional plan)
- [ ] Odoo Community Edition (self-hosted) kurulu ve çalışıyor
- [ ] Amazon entegrasyon modülü Odoo'ya yüklenmiş
- [ ] Şirketin kendi web sitesi (örn: ugurlar.com)
- [ ] Gizlilik politikası sayfası (Amazon'un görebileceği public URL)
- [ ] SSL sertifikası (HTTPS) aktif

### Süre Beklentisi
| Aşama | Tahmini Süre |
|-------|-------------|
| Developer hesabı oluşturma | 1 saat |
| Solution Provider Profile doldurma | 2-3 saat |
| Amazon ilk inceleme | 2-5 iş günü |
| Ek soru-cevap turları (olabilir) | 5-15 iş günü |
| Uygulama oluşturma ve bağlantı | 1 saat |
| **Toplam** | **1-4 hafta** |

---

## 2. Amazon Developer Hesabı Oluşturma

### Adım 1: Solution Provider Portal'a Giriş
1. Şu adrese gidin: `https://solutionproviderportal.amazon.com`
2. Amazon Seller Central hesabınızla giriş yapın
3. Hesap seçim ekranı gelirse, **satış yaptığınız mağaza hesabını** seçin (örn: `ugurlarstore`)

### Adım 2: Onboarding Ekranı
- "Step 1 / Step 2" seçenekleri çıkarsa, bunları atlayabilirsiniz
- Sağ alt köşedeki **"Home Page"** linkine tıklayarak ana sayfaya geçin
- Eğer zaten SPP hesabınız varsa "You already have an SPP account" mesajı çıkacaktır

### Adım 3: Developer Registration
1. Üst menüden **Apps** sekmesine tıklayın
2. Açılan sayfada **Register** veya profil tamamlama seçeneğine tıklayın
3. Solution Provider Profile formunu doldurun (Bölüm 3'e bakın)

> [!WARNING]
> "Add new app client" butonu **ancak** developer kaydınız onaylandıktan sonra aktif olacaktır. Önce profil formunu tamamlayıp Amazon'un onayını beklemeniz gerekir.

---

## 3. Solution Provider Profile Formu

### Bölüm A: Contact Information (İletişim Bilgileri)

| Alan | Değer | Notlar |
|------|-------|--------|
| Organization name | Şirket adınız | Resmi ticari unvan |
| Organization website | `https://www.sirketiniz.com` | ⚠️ Ana e-ticaret sitesi, Odoo URL'si DEĞİL |
| Organization home country | Turkey | |
| Primary contact name | İsim Soyisim | |
| Contact email | email@sirketiniz.com | |
| Contact country code | +90 | |
| Contact phone number | 5XXXXXXXXX | |

> [!CAUTION]
> **Organization website** alanına **kesinlikle** Odoo URL'nizi yazmayın. Amazon yetkilisi bu siteye tıklayıp şirketinizi doğrulayacaktır. Ana e-ticaret sitenizi yazın.

### Bölüm B: Data Access (Veri Erişimi)

**Organizasyon tipi seçimi:**
```
Private Solution Provider: I build application(s) to integrate my organization with Amazon APIs. I integrate only myself.
```
Bu seçeneği seçin — çünkü uygulamayı sadece kendi mağazanız için geliştiriyorsunuz.

**Explain your primary business activity... (Max 500 karakter):**
```
We sell products on Amazon. We are building a private application to connect our Seller
Central account with our self-hosted Odoo ERP system. We will use the SP-API to automate
real-time inventory synchronization, order retrieval, tax invoicing, and fulfillment tracking.
This private integration will eliminate manual data entry and improve our direct-to-consumer
shipping performance.
```

### Bölüm C: Roles (Roller)

Seçilmesi gereken roller:

| Rol | Seçim | Açıklama |
|-----|-------|----------|
| ✅ Product Listing | Zorunlu | Ürün listeleme ve A+ içerik yönetimi |
| ✅ Pricing | Zorunlu | Fiyat belirleme ve otomatik fiyatlandırma |
| ✅ Direct-to-Consumer Shipping | Zorunlu (Restricted) | Kargo etiketi oluşturma, müşteri adresi gerektirir (PII) |
| ✅ Tax Invoicing | Zorunlu (Restricted) | Fatura oluşturma, Türk e-Fatura zorunluluğu (PII) |
| ✅ Inventory and Order Tracking | Zorunlu | Stok ve sipariş takibi |
| ❌ Amazon Fulfillment | Seçmeyin | FBA kullanmıyorsanız gerekli değil |
| ❌ Buyer Communication | Seçmeyin | Müşteri mesajlaşma gerekli değilse |
| ❌ Finance and Accounting | Seçmeyin | Finansal raporlama gerekli değilse |

> [!IMPORTANT]
> **Direct-to-Consumer Shipping** ve **Tax Invoicing** rolleri **"Restricted"** (Kısıtlı) rollerdir. Bu rolleri seçtiğinizde Amazon sizden ek güvenlik bilgileri ve PII (Kişisel Veri) politikalarınızı detaylı açıklamanızı isteyecektir. Bu rehberin en kritik kısmı budur.

### Bölüm D: Use Cases (Kullanım Senaryoları)

**Describe the application or feature(s)... (Max 500 karakter):**
```
We are developing a private, in-house integration to connect our Amazon Seller Central
account with our self-hosted Odoo ERP system. The primary goal is to automate order syncing,
stock updates, and invoicing. We specifically require the Direct-to-Consumer Shipping
(Restricted) role to pull customer PII (Name, Address, Phone) exclusively for generating
shipping labels and fulfilling orders directly from our warehouse. All data is processed
securely within our closed-loop ERP system.
```

**Describe why your organization requires Restricted roles... (Max 500 karakter):**

> [!CAUTION]
> Bu alan **en kritik** alandır. Amazon burada en çok red verir. Türkiye'nin vergi kanunlarını madde numaralarıyla belirtmeniz gerekir.

```
We require 'Direct-to-Consumer Shipping' to access buyer PII for generating shipping
labels via Turkish local carriers (Yurtiçi, Aras, MNG Kargo). We require 'Tax Invoicing'
because Turkish Tax Procedure Law (VUK Art. 232) mandates all businesses to issue e-Fatura
via GİB (Turkish Revenue Administration) in UBL-TR XML format. Seller Central does not
generate Turkish-compliant e-Fatura/e-Arşiv invoices. PII is used solely for these purposes
and deleted within 30 days.
```

### Bölüm E: Security Controls (Güvenlik Kontrolleri)

Tüm Yes/No sorularına **"Yes"** seçin:

| Soru | Cevap |
|------|-------|
| Network security controls, firewalls, IDS/IPS? | ✅ Yes |
| Restrict access based on job duties? | ✅ Yes |
| Encrypt Amazon Information in transit? | ✅ Yes |
| Incident response plan with 24-hour notification? | ✅ Yes |
| Report security incidents to security@amazon.com within 24 hours? | ✅ Yes |
| Password requirements (12+ chars, MFA, 365-day rotation)? | ✅ Yes |
| Credentials stored securely (not in repos)? | ✅ Yes |

### Bölüm F: Data Sharing (Veri Paylaşımı)

**List all outside parties... :**
```
Amazon data is NOT shared with any outside parties, 3rd party software, or external
agencies. All data is strictly processed within our private, self-hosted Odoo ERP system
for internal fulfillment purposes only.
```

**List all external (non-Amazon) sources... :**
```
None. We do not retrieve Amazon Information from any external non-Amazon sources.
```

### Bölüm G: PII Retention (Kişisel Veri Saklama Süresi)

> [!CAUTION]
> Bu seçim **en kritik** seçimdir! Yanlış seçerseniz başvurunuz kesinlikle reddedilir.

```
✅ Less than 31 days after order shipments   ← BU SEÇENEĞİ SEÇİN
❌ 31 to 90 days after order shipments
❌ 91 to 180 days after order shipments
❌ More than 180 days after order shipments   ← ASLA BU SEÇENEĞİ SEÇMEYİN
```

### Bölüm H: Ek Yes/No Soruları

| Soru | Cevap |
|------|-------|
| Documented data handling, classification, and privacy policies? | ✅ Yes |
| Encrypt PII at REST using AES-128/RSA-2048 and maintain KMS? | ✅ Yes |
| Fine-grained access controls to restrict access to PII? | ✅ Yes |
| Audit logs with bi-weekly reviews and 12-month retention? | ✅ Yes |
| Application changes evaluated in test environment? | ✅ Yes |
| Vulnerability scans every 30 days, annual penetration tests? | ✅ Yes |
| Scan application code for vulnerabilities prior to each release? | ✅ Yes |
| Formal change management process? | ✅ Yes |

---

## 4. Onaylanan Cevap Şablonları

> [!IMPORTANT]
> Aşağıdaki tüm cevaplar **500 karakter sınırının altındadır** ve Amazon tarafından **onaylanmış** metinlerdir. Yeni başvurularda doğrudan kullanabilirsiniz. Sadece şirket adı, URL ve iletişim bilgilerini değiştirin.

### 4.1 Network Protection Controls
**Soru:** *"Describe the network protection controls used by your organization to restrict public access to databases, file servers, and desktop/developer endpoints."*

```
Our databases and Odoo ERP servers are hosted in a private, non-public subnet without
direct internet access. All public traffic is routed through a strict firewall that only
allows encrypted HTTPS (TLS 1.2+) connections. SSH and database access are strictly
whitelisted to authorized IP addresses via a secure VPN.
```

### 4.2 Employee Access Management ⚠️
**Soru:** *"Describe how your organization individually identifies employees with Amazon Information access. Explain how it restricts employee access to Amazon information on a need-to-know basis."*

> [!WARNING]
> Amazon bu alanda **"24 saat içinde işten ayrılan çalışanın erişiminin kapatılması"** ifadesini mutlaka görmek istiyor. Bu cümle eksikse RED alırsınız.

```
Every employee accesses our Odoo ERP using a unique, individually assigned account. We
implement Role-Based Access Control (RBAC) and the Principle of Least Privilege. Only
authorized warehouse staff are granted access to Amazon PII on a need-to-know basis.
When an employee is terminated or changes roles, their access is disabled within 24 hours
via our IT offboarding procedure. Access reviews are conducted quarterly.
```

### 4.3 Monitoring Mechanism (Personal Devices)
**Soru:** *"Describe the monitoring mechanism your organization uses to prevent employees to access Amazon Information from personal devices..."*

```
We enforce Group Policy Objects (GPO) on all workstations to disable USB mass storage
devices and prevent unauthorized data exfiltration. Employees are prohibited from accessing
the ERP via personal cellphones. Our endpoint monitoring software immediately alerts IT
administrators if an unauthorized device is connected.
```

### 4.4 Privacy and Data Handling Policy ⚠️
**Soru:** *"Provide your organization's privacy and data handling policies..."*

> [!WARNING]
> Amazon bu alanda **şirketinizin KENDİ web sitesindeki** bir gizlilik politikası linki görmek istiyor. Odoo URL'si veya başka bir platformun linki reddedilir. Detaylı gizlilik politikası sayfası oluşturma talimatları Bölüm 5'te.

```
Our complete privacy and data handling policy, which describes how Amazon data is collected,
processed, stored, used, shared, and disposed, is publicly available at:
https://www.SİRKETİNİZ.com/pages/amazon-privacy-policy — This policy is maintained by
[ŞİRKET ADI] and applies specifically to our Amazon SP-API integration.
```

### 4.5 Encryption at Rest ⚠️
**Soru:** *"Describe how your organization stores Amazon information at Rest including: (a) encryption methods (AES-128, RSA-2048, etc.), and (b) key management systems."*

> [!WARNING]
> Amazon bu alanda **Key Management System (KMS)** detayı görmek istiyor. Sadece "AES-256 ile şifreli" yazmak yeterli değildir.

```
All Amazon data at rest is encrypted using AES-256 within our PostgreSQL database.
Encryption keys are managed through a dedicated Key Management System (KMS), stored
separately from encrypted data on an isolated server. Key rotation is performed annually.
KMS access is limited to one designated admin with MFA, ensuring separation of duties
between data operators and key custodians.
```

### 4.6 Encrypted Backups (RTO/RPO)
**Soru:** *"Describe how your organization stores encrypted backups/archives of Amazon Information including: (a) geographically separated backup location, and (b) restore procedures (RTO/RPO)."*

```
Our database backups are encrypted using AES-256 and stored in a geographically separated,
secure off-site cloud storage location. We have a Disaster Recovery Plan with a Recovery
Time Objective (RTO) of 4 hours and a Recovery Point Objective (RPO) of 1 hour. PII data
in backups is also subject to the strict 30-day deletion policy.
```

### 4.7 Security Logging and Monitoring ⚠️
**Soru:** *"Describe your organization's security logging and monitoring system..."*

> [!WARNING]
> Amazon bu alanda **"PII loglarda saklanmıyor"** ifadesini mutlaka görmek istiyor. Bu cümle eksikse RED alırsınız.

```
We maintain centralized security logging for our Odoo ERP and NGINX servers. Logs are
retained for minimum 12 months. Our monitoring detects brute-force attacks, unauthorized
access, and anomalous patterns, sending high-priority alerts to IT admins. Importantly,
PII is never written to or stored in log files. All logging excludes PII fields (buyer
name, address, phone) to prevent data exposure.
```

### 4.8 Incident Response Plan
**Soru:** *"Summarize the steps taken within your organization's incident response plan..."*

```
In the event of a security incident, our Incident Response Plan includes: 1) Immediate
isolation of the affected servers from the external network. 2) Revocation of compromised
credentials. 3) Notification to Amazon (security@amazon.com) within 24 hours of detection.
4) Investigation, remediation, and post-incident review.
```

### 4.9 Password Management ⚠️
**Soru:** *"How does your organization enforce password management practices..."*

> [!WARNING]
> Amazon bu alanda **"kullanıcı adının şifrede kullanılmasının yasak olduğu"** ifadesini mutlaka görmek istiyor.

```
We enforce a strict password policy on all systems. Minimum 12 characters with uppercase,
lowercase, numbers, and special characters required. Employees are prohibited from using
their username, email, or personal info as part of their password. Passwords expire every
90 days, last 5 cannot be reused. MFA is enforced for all admin and Amazon data-facing
accounts.
```

### 4.10 PII Protection During Testing
**Soru:** *"How is Personally Identifiable Information (PII) protected during testing?"*

```
We never use real Amazon PII in our testing, sandbox, or development environments. All
data transferred from production to testing is subjected to strict Data Masking and
anonymization processes. Only synthetic, auto-generated dummy data is used during the
testing lifecycle.
```

### 4.11 Credential Exposure Prevention
**Soru:** *"What measures are taken to prevent exposure of credentials?"*

```
Amazon credentials (LWA Client Secret, Refresh Tokens) are never stored in plain text or
committed to any version control repository (e.g., Git). They are securely stored within
the Odoo database in encrypted fields and injected via restricted environment variables.
```

### 4.12 Vulnerability Remediation Tracking ⚠️
**Soru:** *"How does your organization track remediation progress of findings identified from vulnerability scans and penetration tests?"*

> [!WARNING]
> Amazon bu alanda **CVSS skorlarına göre spesifik düzeltme süreleri** görmek istiyor. Genel ifadeler reddedilir.

```
Findings are logged and prioritized using CVSS scores with strict timelines: Critical
(9.0-10.0) remediated within 24 hours, High (7.0-8.9) within 48 hours, Medium (4.0-6.9)
within 7 days, Low (0.1-3.9) within 30 days. Our IT manager tracks all findings in a
centralized remediation tracker until closure.
```

### 4.13 Code Vulnerability Remediation ⚠️
**Soru:** *"How does your organization remediate code vulnerabilities identified in the development lifecycle and during runtime?"*

> [!WARNING]
> Amazon bu alanda **teknik kontroller** (SAST, WAF, hotfix süreci) görmek istiyor. Sadece "kod incelemesi yapıyoruz" yazmak yeterli değildir.

```
All code changes undergo mandatory peer reviews before merging. We use SAST tools to scan
for vulnerabilities before deployment. At runtime, we employ WAF rules and Odoo's built-in
CSRF, SQL injection, and XSS protections. Production vulnerabilities are patched via
emergency hotfix with rollback capability, followed by post-incident review to prevent
recurrence.
```

### 4.14 IMPOC (Incident Management Point of Contact)
**Soru:** *"Provide the name and email address of the Incident Management Point of Contact (IMPOC)..."*

```
Yetkili Ad Soyad
email@sirketiniz.com
```

---

## 5. Gizlilik Politikası Sayfası Oluşturma

> [!CAUTION]
> Amazon, gizlilik politikası linkinin **şirketinizin kendi web sitesinde** olmasını zorunlu kılmaktadır. Odoo URL'si, üçüncü parti siteler veya Google Docs linkleri **reddedilir**.

### Shopify Sitesinde Oluşturma (Önerilen)
1. Shopify Admin → **Online Store** → **Pages** → **Add Page**
2. Sayfa başlığı: `Amazon Privacy Policy`
3. URL handle: `amazon-privacy-policy`
4. Final URL: `https://www.sirketiniz.com/pages/amazon-privacy-policy`

### Odoo Web Sitesinde Oluşturma (Alternatif)
Odoo'nun website modülünde veya controller'da bir route olarak eklenebilir. Ancak Amazon'un linki "Odoo'ya ait" olarak algılama riski vardır. Shopify veya ana domain tercih edilmelidir.

### Gizlilik Politikası İçeriği (İngilizce — Tam Metin)

```html
Privacy and Data Handling Policy — Amazon SP-API Integration

Last Updated: [AY YIL]
Company: [ŞİRKET ADI]

This Privacy and Data Handling Policy describes how [ŞİRKET ADI] ("we", "us", "our")
collects, processes, stores, uses, shares, and disposes of Amazon Information, including
Personally Identifiable Information (PII), obtained through the Amazon Selling Partner
API (SP-API).

1. Data Collection
We collect Amazon order data including buyer name, shipping address, phone number, and
order details exclusively through the SP-API. Data is collected only when an order is
placed and retrieved by our internal ERP system.

2. Data Processing
Collected data is processed within our private, self-hosted Odoo ERP system for the sole
purposes of: generating shipping labels, fulfilling orders via local carriers, and
generating legally required tax invoices (e-Fatura).

3. Data Storage
All Amazon Information is stored in an encrypted PostgreSQL database using AES-256
encryption at rest. The database resides in a private, non-public subnet with restricted
firewall access.

4. Data Usage
PII is used exclusively for order fulfillment and tax invoicing. It is never used for
marketing, advertising, profiling, or any purpose beyond the original fulfillment scope.

5. Data Sharing
We do NOT share, sell, rent, or disclose Amazon Information to any third parties, marketing
agencies, or external organizations. All data remains strictly within our closed-loop
ERP system.

6. Data Retention and Disposal
PII is retained for no longer than 30 days after order shipment. After this period, all
PII is permanently and irreversibly deleted from our primary databases and encrypted backups
using cryptographic erasure methods.

7. Incident Response
In the event of a data breach, we will isolate affected systems, revoke compromised
credentials, and notify Amazon at security@amazon.com within 24 hours of detection.

8. Contact
Incident Management Point of Contact (IMPOC): email@sirketiniz.com
```

> [!TIP]
> Bu sayfayı **Register butonuna basmadan ÖNCE** oluşturup yayınlayın. Amazon yetkilisi linke tıklayıp 404 alırsa başvurunuz reddedilir.

---

## 6. Amazon'un Sorduğu Ek Sorular ve Cevapları

Amazon, ilk başvurudan sonra ek sorular sorabilir. Bizim sürecimizde **2 tur** ek soru geldi.

### Tur 1: "Neden Resmi Odoo Connector Kullanmıyorsunuz?"

Amazon şu soruyu sorar:
- *"Why can't you use Odoo's official Amazon Connector (already on the SP Appstore)?"*
- *"What specific functionality does your custom integration provide that the existing connector does not?"*

**Onaylanan Cevap (Case Reply olarak gönderilir):**

```
Dear Amazon Solution Provider Services Team,

Thank you for the opportunity to clarify. We have evaluated the official Odoo Amazon
Connector (amzn1.sp.solution.1cab4d17) and determined it is not viable for our organization:

1. Odoo Edition Incompatibility: The official connector is exclusively available for Odoo
Enterprise Edition (paid subscription). We operate on Odoo Community Edition (open-source,
self-hosted), which is an entirely different codebase.

2. Turkey Market and Localization: The official connector does not support Turkish language
or Turkey-specific tax compliance (e-Fatura, e-Arşiv Fatura in UBL-TR format via GİB).

3. Marketplace Coverage Gap: The official connector's supported marketplaces are US, Canada,
Mexico, and Brazil. Our primary marketplace is Amazon.com.tr (Turkey).

4. Custom Functionality:
- Turkish e-Invoice (e-Fatura) generation compliant with GİB
- Local carrier integration (Yurtiçi Kargo, Aras Kargo, MNG Kargo)
- Custom multi-warehouse stock sync logic
- AI-powered product image management

We are not building a competing solution. The official connector is simply incompatible
with our software edition, language, marketplace, and legal requirements.

Best regards,
[İSİM]
[ŞİRKET]
```

### Tur 2: Tax Invoicing Rolü Gerekçesi

Amazon şu soruyu sorar:
- *"Justify why your organization needs a tax invoicing mechanism other than the one available in Seller Central."*
- *"Mention the regional tax requirements your organization needs to comply with."*

**Onaylanan Case Reply:**

```
Dear Amazon Solution Provider Services Team,

Our company is a registered business entity in Turkey. Under Turkish tax law (Tax Procedure
Law - VUK, Article 232), all businesses above a certain revenue threshold are legally
required to issue electronic invoices (e-Fatura) through GİB (Turkish Revenue Administration).

Turkish e-Fatura must be generated in UBL-TR 1.2 XML format and submitted to GİB's central
system. For B2C transactions, Turkish law requires e-Arşiv Fatura.

Amazon Seller Central's built-in invoicing does not support:
- Turkish UBL-TR 1.2 XML invoice format required by GİB
- Submission to the Turkish Revenue Administration's e-Fatura portal
- e-Arşiv Fatura for B2C consumer transactions
- Turkish tax ID (VKN/TCKN) validation

Regional tax requirements we comply with:
- Turkish Tax Procedure Law (VUK) Article 232
- e-Fatura Regulation (GİB Communiqué No. 397, 421, 454, 509)
- e-Arşiv Fatura Regulation
- Turkish Commercial Code (TTK) Article 21

Without the Tax Invoicing role, we cannot comply with Turkish law.

Best regards,
[İSİM]
[ŞİRKET]
```

> [!TIP]
> Amazon'un ek soru gönderdiği durumda **hem** Solution Provider Profile formunu güncelleyin **hem de** case'e reply olarak detaylı cevap yazın. İkisini birden yapmalısınız.

---

## 7. Uygulama Oluşturma ve Credentials Alma

> [!NOTE]
> Bu adım ancak Amazon'dan **"Your request for access to SP-API has been approved"** e-postası geldikten sonra yapılabilir.

### Adım 1: Yeni Uygulama Oluşturma
1. `https://solutionproviderportal.amazon.com/sellingpartner/developerconsole` adresine gidin
2. **"+ Add new app client"** butonuna tıklayın
3. Formu doldurun:

| Alan | Değer |
|------|-------|
| App name | `Odoo Entegrasyon` (veya istediğiniz bir isim) |
| API Type | `SP API` |
| App Type | `Production` |
| Business entities supported | ✅ Sellers |
| Vendors | ❌ |
| Shipping | ❌ |

4. **Roles** bölümünde seçin:
   - ✅ Pricing
   - ✅ Direct-to-Consumer Shipping
   - ✅ Inventory and Order Tracking
   - ✅ Product Listing
   - ✅ Tax Invoicing

5. **RDT sorusu:** "No, I will not delegate access to PII to another developer's application." seçin

6. **"Save and exit"** butonuna basın

### Adım 2: LWA Credentials Alma
1. Developer Central listesinde uygulamanızı göreceksiniz
2. **App ID** satırda görünür: `amzn1.sp.solution.XXXX-XXXX-XXXX`
3. **LWA credentials** sütunundaki **"View"** linkine tıklayın
4. Popup'ta şu bilgiler görünür:
   - **Client identifier (Client ID):** `amzn1.application-oa2-client.XXXX`
   - **Client secret:** `amzn1.oa2-cs.v1.XXXX`

> [!CAUTION]
> Client Secret'ı **tek seferlik** gösterir. Kopyalayıp güvenli bir yere kaydedin. Kaybederseniz **"Rotate secret"** ile yeni bir tane oluşturmanız gerekir.

### Elde Edilen Bilgiler Tablosu

| Bilgi | Format | Nereden |
|-------|--------|---------|
| SP-API App ID | `amzn1.sp.solution.XXXX` | Developer Central listesi |
| LWA Client ID | `amzn1.application-oa2-client.XXXX` | LWA credentials popup |
| LWA Client Secret | `amzn1.oa2-cs.v1.XXXX` | LWA credentials popup |
| Refresh Token | `Atzr\|XXXX` | Self-authorization (Bölüm 8) |

---

## 8. Self-Authorization ve Refresh Token

### Neden Self-Authorization?
Private developer olarak "Self Authorization" kullanıyoruz. Bu, kendi mağazamızı kendi uygulamamıza yetkilendirmemiz anlamına gelir.

### Adımlar
1. Developer Central listesinde uygulamanızın yanındaki **"Edit App" butonunun yanındaki ok (˅)** işaretine tıklayın
2. Açılan menüden **"Authorize"** seçin
3. **"Manage Authorizations"** sayfası açılacak
4. **Marketplaces** tablosunda ülkenizi göreceksiniz (örn: Turkey)
5. **"Authorize app"** butonuna tıklayın
6. Refresh Token oluşturulacak ve ekranda görünecek
7. Yanındaki **"Copy"** linkine tıklayarak kopyalayın

> [!WARNING]
> Refresh Token'ı güvenli bir yere kaydedin. Bu token ile Amazon hesabınıza programatik erişim sağlanır.

### Self Authorizations Bilgisi
- **Self Authorizations:** Kendi mağazanızı yetkilendirme (10 hakkınız var)
- **OAuthorizations:** Başka satıcıları yetkilendirme (Private developer için "No authorization allowed")

---

## 9. Odoo'ya Bağlantı Kurma

### Adım 1: Amazon Modülüne Giriş
1. Odoo'ya giriş yapın
2. Üst menüden **Amazon** modülüne tıklayın
3. **Amazon Mağazaları** menüsüne girin
4. **"Yeni"** butonuna basın

### Adım 2: Mağaza Bilgilerini Girin

| Alan | Değer |
|------|-------|
| Mağaza Adı | `Amazon Türkiye` (veya istediğiniz isim) |
| Ortam | `Production (Canlı)` |
| SP-API Bölgesi | `Avrupa (TR Dahil) - EU` |
| Marketplace ID | `A33AVAJ2PDY3EV` (Türkiye için) |
| SP-API App ID | Bölüm 7'den aldığınız değer |
| LWA Client ID | Bölüm 7'den aldığınız değer |
| LWA Client Secret | Bölüm 7'den aldığınız değer |
| Refresh Token | Bölüm 8'den aldığınız değer |

### Marketplace ID'leri (Referans)

| Ülke | Marketplace ID |
|------|---------------|
| 🇹🇷 Türkiye | A33AVAJ2PDY3EV |
| 🇩🇪 Almanya | A1PA6795UKMFR9 |
| 🇬🇧 İngiltere | A1F83G8C2ARO7P |
| 🇫🇷 Fransa | A13V1IB3VIYZZH |
| 🇮🇹 İtalya | APJ6JRA9NG5V4 |
| 🇪🇸 İspanya | A1RKKUPIHCS9HS |
| 🇳🇱 Hollanda | A1805IZSGTT6HS |
| 🇸🇪 İsveç | A2NODRKZP88ZB9 |
| 🇵🇱 Polonya | A1C3SOZF6UW3RL |
| 🇧🇪 Belçika | AMEN7PMS3EDWL |
| 🇸🇦 Suudi Arabistan | A17E79C6D8DWNP |
| 🇦🇪 BAE | A2VIGQ35RCS4UG |
| 🇺🇸 ABD | ATVPDKIKX0DER |

### Adım 3: Bağlantı Testi
1. Formu kaydedin (💾)
2. **"Bağlantıyı Test Et"** butonuna tıklayın
3. ✅ "Başarılı. Amazon LWA bağlantısı başarıyla kuruldu ve Token alındı!" mesajı gelmelidir

### Adım 4: İlk Senkronizasyon
1. **"Siparişleri Senkronize Et"** butonuna tıklayın
2. Amazon'daki bekleyen siparişler Odoo'ya aktarılacaktır
3. Sipariş yoksa "0 sipariş işlendi" mesajı gelir (bu normaldir)

> [!TIP]
> Modülde **cron job** (zamanlanmış görev) kurulu olduğundan, siparişler belirli aralıklarla otomatik olarak çekilecektir. Manuel senkronizasyona sürekli ihtiyaç yoktur.

---

## 10. Sık Yapılan Hatalar ve Çözümleri

### ❌ Hata 1: "More than 180 days" Seçmek
**Problem:** PII saklama süresini 180 günden fazla olarak seçmek
**Çözüm:** Kesinlikle **"Less than 31 days after order shipments"** seçin

### ❌ Hata 2: Türkçe Cevap Yazmak
**Problem:** Form kutucuklarına Türkçe cevaplar yazmak
**Çözüm:** Tüm cevapları **İngilizce** yazın. Amazon'un inceleme ekibi global çalışır.

### ❌ Hata 3: 500 Karakter Limitini Aşmak
**Problem:** Metin kutularına 500 karakterden fazla yazmak
**Çözüm:** Register butonuna basınca "There are errors on this page" hatası alırsınız. Sayfayı aşağı kaydırıp kırmızı uyarıyı bulun ve metni kısaltın.

### ❌ Hata 4: Odoo URL'sini Gizlilik Politikası Olarak Vermek
**Problem:** `https://odoo.sirketiniz.com/amazon-privacy-policy` vermek
**Çözüm:** Amazon bu linki "Odoo'ya ait" olarak algılar. Ana e-ticaret sitenizde (örn: Shopify) oluşturun.

### ❌ Hata 5: Organization Website'e Odoo URL'si Yazmak
**Problem:** Organization website alanına Odoo adresini yazmak
**Çözüm:** Ana e-ticaret sitenizi yazın (örn: `https://www.sirketiniz.com`)

### ❌ Hata 6: Tax Invoicing İçin Yetersiz Gerekçe
**Problem:** "Fatura oluşturmak istiyoruz" gibi genel bir açıklama yazmak
**Çözüm:** Türkiye'nin vergi kanunlarını (VUK Art. 232, e-Fatura, GİB, UBL-TR) madde numaralarıyla belirtin ve Seller Central'ın neden yetersiz olduğunu açıklayın.

### ❌ Hata 7: KMS Detayını Atlama
**Problem:** Şifreleme sorusunda sadece "AES-256 kullanıyoruz" yazmak
**Çözüm:** Key Management System (KMS), anahtar ayrımı, yıllık anahtar rotasyonu ve MFA detaylarını ekleyin.

### ❌ Hata 8: PII Loglama Detayını Atlama
**Problem:** Loglama sorusunda PII'nin loglarda saklanıp saklanmadığından bahsetmemek
**Çözüm:** "PII is never written to or stored in any log files" ifadesini mutlaka ekleyin.

### ❌ Hata 9: __manifest__.py Dosya Sıralaması
**Problem:** Odoo modülünde `amazon_config_views.xml`'in `amazon_store_views.xml`'den önce yüklenmesi
**Çözüm:** `__manifest__.py`'de `amazon_store_views.xml`'i `amazon_config_views.xml`'den **önce** sıralayın.

---

## 11. Önemli Linkler

### Amazon Portalleri
| Portal | URL |
|--------|-----|
| Seller Central (TR) | https://sellercentral.amazon.com.tr |
| Solution Provider Portal | https://solutionproviderportal.amazon.com |
| Developer Central | https://solutionproviderportal.amazon.com/sellingpartner/developerconsole |
| SP-API Dokümantasyonu | https://developer-docs.amazon.com/sp-api/ |
| SP-API FAQ | https://developer-docs.amazon.com/sp-api/docs/faq |
| SP-API Video Eğitimi | https://www.youtube.com/playlist?list=PLyrrqKCT7jFKENJO9n_Y68-5o2GZLgLUU |

### Amazon Politikaları
| Politika | URL |
|----------|-----|
| Acceptable Use Policy (AUP) | https://sellercentral.amazon.com/mws/static/policy?documentType=AUP&locale=us_US |
| Data Protection Policy (DPP) | https://sellercentral.amazon.com/mws/static/policy?documentType=DPP&locale=us_US |
| Key Security Controls | https://developer-docs.amazon.com/sp-api/docs/guidance-to-address-key-security-controls-in-sp-api-integration |
| Roles Definition | https://developer-docs.amazon.com/sp-api/docs/roles-in-the-selling-partner-api |

### Amazon SP-API Bölgesel Endpoints
| Bölge | Endpoint |
|-------|----------|
| Avrupa (EU) | https://sellingpartnerapi-eu.amazon.com |
| Kuzey Amerika (NA) | https://sellingpartnerapi-na.amazon.com |
| Uzak Doğu (FE) | https://sellingpartnerapi-fe.amazon.com |

### LWA Token Endpoint
```
POST https://api.amazon.com/auth/o2/token
```

---

> [!NOTE]
> Bu rehber, Ugurlar Grup'un Amazon SP-API başvuru sürecindeki gerçek tecrübelerden derlenmiştir. Amazon'un politikaları ve form yapısı zaman içinde değişebilir. Yeni başvurularda güncel Amazon dokümantasyonunu da kontrol etmeniz önerilir.

---

**Rehber Sonu** | Hazırlayan: Antigravity AI | Temmuz 2026
