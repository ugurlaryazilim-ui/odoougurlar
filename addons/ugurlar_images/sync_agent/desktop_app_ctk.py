import customtkinter as ctk
import threading
import json
import os
import sys
import time
import logging
import traceback

# ═══ Görev Zamanlayıcı düzeltmesi ═══
# Windows Görev Zamanlayıcı uygulamayı C:\WINDOWS\system32'den çalıştırır.
# Bu durumda config.json, cache, log gibi göreceli yollar yanlış dizini kullanır.
# Çözüm: Çalışma dizinini exe/script'in bulunduğu dizine değiştir.
if getattr(sys, 'frozen', False):
    # PyInstaller ile paketlenmiş exe
    _app_dir = os.path.dirname(sys.executable)
else:
    # Normal Python script
    _app_dir = os.path.dirname(os.path.abspath(__file__))

os.chdir(_app_dir)
# ═══════════════════════════════════════

from sync_agent import OdooImageSync, load_config, _logger

def resource_path(relative_path):
    """PyInstaller (OneFile) için dosya yolunu çözer."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class CTkLogHandler(logging.Handler):
    """Logları CustomTkinter Textbox'a basmak için özel logging Handler'ı."""
    def __init__(self, textbox):
        super().__init__()
        self.textbox = textbox
        self.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

    def emit(self, record):
        try:
            msg = self.format(record)
            # Thread-safe: GUI güncellemelerini ana Tk thread'inde yap
            self.textbox.after(0, self._safe_insert, msg)
        except Exception:
            pass

    def _safe_insert(self, msg):
        """Ana thread'de güvenli log ekleme + bellek sızıntısı önleme."""
        try:
            self.textbox.insert("1.0", msg + "\n")
            # Max 500 satır tut — 7/24 çalışmada RAM şişmesini önle
            content = self.textbox.get("1.0", "end")
            lines = content.split("\n")
            if len(lines) > 500:
                self.textbox.delete(f"{501}.0", "end")
        except Exception:
            pass

class OdooSyncApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Tema ayarları (Odoo 19 Stili)
        ctk.set_appearance_mode("light")
        self.configure(fg_color="#F9F9F9") # Odoo Light Background
        
        self.title("Uğurlar Odoo Image Sync Agent")
        self.geometry("900x800")
        
        try:
            self.iconbitmap(resource_path("icon.ico"))
        except Exception:
            pass
        
        self.agent = None
        self.agent_thread = None
        self.stop_event = threading.Event()
        self.is_running = False

        self.config = load_config()
        
        self._build_ui()
        self._setup_logging()
        
        # Eğer Odoo URL boşsa (yeni kurulum) otomatik ayarları aç
        if not self.config.get("odoo_url"):
            self.after(500, self.open_settings_window)
        else:
            # URL varsa program açılır açılmaz otomatik BAŞLAT
            self.after(1000, self.start_sync)

    def _build_ui(self):
        # Üst Panel (Odoo Moru)
        self.header_frame = ctk.CTkFrame(self, fg_color="#714B67", corner_radius=0)
        self.header_frame.pack(fill=ctk.X, padx=0, pady=(0, 15))
        
        # İç Padding için ekstra frame
        self.header_inner = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.header_inner.pack(fill=ctk.X, padx=20, pady=15)
        
        self.title_label = ctk.CTkLabel(self.header_inner, text="Uğurlar Odoo Image Sync", text_color="white", font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"))
        self.title_label.pack(side=ctk.LEFT, anchor="w")
        
        # Ayarlar Butonu
        self.settings_btn = ctk.CTkButton(self.header_inner, text="⚙️ AYARLAR", fg_color="#F9F9F9", hover_color="#EBEBEB", text_color="#714B67", font=ctk.CTkFont(weight="bold"), width=100, command=self.open_settings_window)
        self.settings_btn.pack(side=ctk.RIGHT, anchor="e")
        
        self.header_sub = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.header_sub.pack(fill=ctk.X, padx=20, pady=(0, 15))
        
        folder = self.config.get('watch_folder', 'Bilinmiyor')
        self.folder_label = ctk.CTkLabel(self.header_sub, text=f"İzlenen Klasör: {folder}", text_color="#E0D4DE", font=ctk.CTkFont(family="Segoe UI", size=13))
        self.folder_label.pack(anchor="w")
        
        # Kontrol Paneli
        self.control_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.control_frame.pack(fill=ctk.X, padx=20, pady=5)
        
        # Odoo 19 Primary Button Style
        self.start_btn = ctk.CTkButton(self.control_frame, text="▶ BAŞLAT", fg_color="#714B67", hover_color="#5D3A54", font=ctk.CTkFont(weight="bold"), command=self.start_sync)
        self.start_btn.pack(side=ctk.LEFT, padx=(0, 10))
        
        # Odoo 19 Secondary/Danger Button Style
        self.stop_btn = ctk.CTkButton(self.control_frame, text="■ DURDUR", fg_color="#F9F9F9", border_width=1, border_color="#714B67", text_color="#714B67", hover_color="#EBEBEB", font=ctk.CTkFont(weight="bold"), state="disabled", command=self.stop_sync)
        self.stop_btn.pack(side=ctk.LEFT)
        
        self.status_label = ctk.CTkLabel(self.control_frame, text="Durum: BEKLİYOR", text_color="#F59E0B", font=ctk.CTkFont(size=15, weight="bold"))
        self.status_label.pack(side=ctk.RIGHT)
        
        # ═══ İlerleme Paneli ═══
        self.progress_frame = ctk.CTkFrame(self, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E5E7EB")
        self.progress_frame.pack(fill=ctk.X, padx=20, pady=(15, 5))

        # Üst satır: başlık + sayaç
        self.progress_header = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        self.progress_header.pack(fill=ctk.X, padx=15, pady=(10, 2))

        self.progress_title = ctk.CTkLabel(self.progress_header, text="📊 İşlem İlerlemesi", text_color="#111827", font=ctk.CTkFont(size=14, weight="bold"))
        self.progress_title.pack(side=ctk.LEFT)

        self.progress_counter = ctk.CTkLabel(self.progress_header, text="0 / 0 barkod", text_color="#6B7280", font=ctk.CTkFont(size=13))
        self.progress_counter.pack(side=ctk.RIGHT)

        # Progress bar satırı
        self.progress_bar_frame = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        self.progress_bar_frame.pack(fill=ctk.X, padx=15, pady=(2, 2))

        self.progress_bar = ctk.CTkProgressBar(self.progress_bar_frame, height=18, corner_radius=9, fg_color="#E5E7EB", progress_color="#714B67")
        self.progress_bar.pack(side=ctk.LEFT, fill=ctk.X, expand=True, padx=(0, 10))
        self.progress_bar.set(0)

        self.progress_pct = ctk.CTkLabel(self.progress_bar_frame, text="0%", text_color="#714B67", font=ctk.CTkFont(size=14, weight="bold"), width=50)
        self.progress_pct.pack(side=ctk.RIGHT)

        # Alt satır: şu anki barkod + başarılı sayısı
        self.progress_detail = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        self.progress_detail.pack(fill=ctk.X, padx=15, pady=(0, 10))

        self.progress_current = ctk.CTkLabel(self.progress_detail, text="Bekleniyor...", text_color="#9CA3AF", font=ctk.CTkFont(size=12))
        self.progress_current.pack(side=ctk.LEFT)

        self.progress_success = ctk.CTkLabel(self.progress_detail, text="✅ 0 başarılı", text_color="#10B981", font=ctk.CTkFont(size=12, weight="bold"))
        self.progress_success.pack(side=ctk.RIGHT)

        # Log Paneli
        self.log_label = ctk.CTkLabel(self, text="İşlem Logları:", text_color="#111827", font=ctk.CTkFont(size=16, weight="bold"))
        self.log_label.pack(anchor="w", padx=20, pady=(10, 5))
        
        # Koyu gri terminal gibi log kutusu (beyaz tema içinde kontrast)
        self.log_box = ctk.CTkTextbox(self, state="normal", wrap="word", fg_color="#1E1E1E", text_color="#E0E0E0", font=ctk.CTkFont(family="Consolas", size=13))
        self.log_box.pack(fill=ctk.BOTH, expand=True, padx=20, pady=(0, 20))

    def _setup_logging(self):
        handler = CTkLogHandler(self.log_box)
        _logger.addHandler(handler)
        # Mevcut dosya loglarını da arayüze yönlendir
        _logger.setLevel(logging.INFO)

    def open_settings_window(self):
        settings_win = ctk.CTkToplevel(self)
        settings_win.title("Ayarlar")
        settings_win.geometry("500x550")
        settings_win.transient(self) # Sadece bu uygulamanın üstünde kalır, diğer programları engellemez.
        settings_win.grab_set() # Focus'u kitle
        
        try:
            settings_win.iconbitmap(resource_path("icon.ico"))
        except: pass
        
        title = ctk.CTkLabel(settings_win, text="Odoo Bağlantı Ayarları", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=(20, 10))
        
        # Odoo URL
        ctk.CTkLabel(settings_win, text="Odoo URL (Örn: https://odoo.ugurlar.com)").pack(anchor="w", padx=20)
        url_entry = ctk.CTkEntry(settings_win, width=460)
        url_entry.insert(0, self.config.get("odoo_url", ""))
        url_entry.pack(padx=20, pady=(0, 10))
        
        # Odoo DB
        ctk.CTkLabel(settings_win, text="Veritabanı Adı").pack(anchor="w", padx=20)
        db_entry = ctk.CTkEntry(settings_win, width=460)
        db_entry.insert(0, self.config.get("odoo_db", ""))
        db_entry.pack(padx=20, pady=(0, 10))
        
        # Username
        ctk.CTkLabel(settings_win, text="Kullanıcı Adı / E-posta").pack(anchor="w", padx=20)
        user_entry = ctk.CTkEntry(settings_win, width=460)
        user_entry.insert(0, self.config.get("odoo_user", ""))
        user_entry.pack(padx=20, pady=(0, 10))
        
        # Password / API Key
        ctk.CTkLabel(settings_win, text="API Anahtarı (veya Odoo Şifresi)").pack(anchor="w", padx=20)
        pwd_entry = ctk.CTkEntry(settings_win, width=460, show="*")
        pwd_entry.insert(0, self.config.get("odoo_password", ""))
        pwd_entry.pack(padx=20, pady=(0, 10))
        
        # Watch Folder
        ctk.CTkLabel(settings_win, text="İzlenecek Klasör (Resimlerin atıldığı yer)").pack(anchor="w", padx=20)
        folder_frame = ctk.CTkFrame(settings_win, fg_color="transparent")
        folder_frame.pack(fill=ctk.X, padx=20, pady=(0, 20))
        
        folder_entry = ctk.CTkEntry(folder_frame)
        folder_entry.insert(0, self.config.get("watch_folder", ""))
        folder_entry.pack(side=ctk.LEFT, fill=ctk.X, expand=True, padx=(0, 10))
        
        def browse_folder():
            path = ctk.filedialog.askdirectory(title="İzlenecek Klasörü Seçin")
            if path:
                folder_entry.delete(0, ctk.END)
                folder_entry.insert(0, path)
                
        ctk.CTkButton(folder_frame, text="Gözat", width=60, command=browse_folder).pack(side=ctk.RIGHT)
        
        # Save action
        def save_settings():
            self.config["odoo_url"] = url_entry.get().strip()
            self.config["odoo_db"] = db_entry.get().strip()
            self.config["odoo_user"] = user_entry.get().strip()
            self.config["odoo_password"] = pwd_entry.get().strip()
            self.config["watch_folder"] = folder_entry.get().strip()
            
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
                
            self.folder_label.configure(text=f"İzlenen Klasör: {self.config['watch_folder']}")
            self.log_box.insert("1.0", "\n=== Ayarlar Kaydedildi ===\n\n")
            settings_win.destroy()
            
        save_btn = ctk.CTkButton(settings_win, text="AYARLARI KAYDET", fg_color="#2e7d32", hover_color="#1b5e20", font=ctk.CTkFont(weight="bold"), command=save_settings)
        save_btn.pack(pady=10)

    def _update_progress(self, processed, total, barcode, success_count):
        """progress_callback: arka plan thread'inden GUI'yi günceller."""
        pct = processed / total if total > 0 else 0
        def _update():
            self.progress_bar.set(pct)
            self.progress_pct.configure(text=f"{int(pct * 100)}%")
            self.progress_counter.configure(text=f"{processed} / {total} barkod")
            self.progress_current.configure(
                text=f"📦 {barcode}" if processed < total else "✔ Tamamlandı",
                text_color="#374151" if processed < total else "#10B981",
            )
            self.progress_success.configure(text=f"✅ {success_count} başarılı")
        self.after(0, _update)

    def _reset_progress(self):
        """İlerleme panelini sıfırla."""
        def _update():
            self.progress_bar.set(0)
            self.progress_pct.configure(text="0%")
            self.progress_counter.configure(text="0 / 0 barkod")
            self.progress_current.configure(text="Taranıyor...", text_color="#9CA3AF")
            self.progress_success.configure(text="✅ 0 başarılı")
        self.after(0, _update)

    def run_agent_loop(self):
        # Ajanı başlat
        while not self.stop_event.is_set():
            try:
                if self.agent is None:
                    self.agent = OdooImageSync(self.config)
                    
                self.agent.optimize_large_local_images()  # Önce büyük dosyaları küçült
                self._reset_progress()
                self.agent.process_folder(progress_callback=self._update_progress)  # Sonra Odoo'ya yükle
                self.agent.download_ai_exports()           # AI görsellerini indir
                
                # Her döngüde 3 saniye bekle (event set edilirse anında çıkar)
                self.stop_event.wait(3.0)
                
            except Exception as e:
                err_str = str(e)
                _logger.error("Ajan çalışırken hata: %s", err_str)
                _logger.error(traceback.format_exc())
                # ── TÜM HATALARI KURTAR — asla çökme ──
                _logger.info("🔄 30 saniye sonra tekrar denenecek...")
                self.agent = None  # Bağlantıyı sıfırla, yeniden oluşturulsun
                self.stop_event.wait(30.0)

    def _reset_ui_on_error(self):
        self.status_label.configure(text="Durum: HATA OLUŞTU", text_color="red")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.is_running = False

    def start_sync(self):
        if self.is_running:
            return
        
        # Eski agent'ı temizle — yeni thread'de temiz başlasın
        self.agent = None
            
        self.is_running = True
        self.stop_event.clear()
        
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_label.configure(text="Durum: ÇALIŞIYOR (Odoo ORM)", text_color="#10B981") # Yeşil
        
        self.log_box.insert("1.0", "\n=== Odoo Sync Agent Başlatıldı ===\n\n")
        
        self.agent_thread = threading.Thread(target=self.run_agent_loop, daemon=True)
        self.agent_thread.start()

    def stop_sync(self):
        if not self.is_running:
            return
            
        self.status_label.configure(text="Durum: DURDURULUYOR...", text_color="orange")
        self.stop_btn.configure(state="disabled")
        
        self.stop_event.set()
        
        # Thread'in bitmesini arkada bekleyip UI'ı kitlememek için yeni bir thread açıyoruz
        threading.Thread(target=self._wait_for_stop, daemon=True).start()

    def _wait_for_stop(self):
        if self.agent_thread and self.agent_thread.is_alive():
            self.agent_thread.join(timeout=10)
            
        self.after(0, self._on_stopped)

    def _on_stopped(self):
        self.status_label.configure(text="Durum: BEKLİYOR", text_color="orange")
        self.start_btn.configure(state="normal")
        self.is_running = False
        self.log_box.insert("1.0", "\n=== Agent Durduruldu ===\n\n")

if __name__ == "__main__":
    app = OdooSyncApp()
    app.mainloop()
