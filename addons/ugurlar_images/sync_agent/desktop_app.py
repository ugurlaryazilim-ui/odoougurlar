import flet as ft
import threading
import time
import logging
import traceback
from sync_agent import OdooImageSync, load_config, _logger

class FletLogHandler(logging.Handler):
    """Logları Flet arayüzüne (ListView'e) basmak için özel log handler."""
    def __init__(self, add_log_callback):
        super().__init__()
        self.add_log_callback = add_log_callback
        self.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt="%H:%M:%S"))

    def emit(self, record):
        log_entry = self.format(record)
        self.add_log_callback(log_entry, record.levelno)


def main(page: ft.Page):
    # --- PENCERE AYARLARI ---
    page.title = "Uğurlar Odoo Image Sync Agent"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 900
    page.window.height = 700
    page.padding = 20
    
    # Modern font (Removed custom font to prevent rendering issues)

    # --- DURUM DEĞİŞKENLERİ ---
    is_running = False
    sync_thread = None
    stop_event = threading.Event()
    
    # Config yükle
    config = load_config()

    # --- ARAYÜZ ELEMANLARI ---
    status_text = ft.Text("Durum: BEKLİYOR", size=16, weight="bold", color="orange")
    folder_text = ft.Text(f"İzlenen Klasör: {config.get('watch_folder', 'Bilinmiyor')}", size=14, color="white70")
    
    log_view = ft.ListView(expand=False, spacing=5, auto_scroll=True)
    
    def add_log(msg, levelno):
        """LogView'e yeni bir satır ekler ve rengini ayarlar."""
        color = "white"
        if levelno >= logging.ERROR:
            color = "red400"
        elif levelno >= logging.WARNING:
            color = "amber400"
        elif "✅" in msg or "Tamamlandı" in msg:
            color = "green400"
        elif "🎨" in msg:
            color = "purple300"
        elif "📦" in msg:
            color = "blue200"
            
        log_view.controls.append(ft.Text(msg, color=color, size=13, font_family="Consolas"))
        # Çok fazla log birikmesini engelle (son 1000 satır)
        if len(log_view.controls) > 1000:
            log_view.controls.pop(0)
        try:
            page.update()
        except Exception:
            pass

    # Kendi log_handler'ımızı sisteme ekliyoruz
    flet_handler = FletLogHandler(add_log)
    _logger.addHandler(flet_handler)

    # --- ARKA PLAN İŞÇİSİ (WORKER THREAD) ---
    def sync_worker():
        nonlocal is_running
        agent = None
        try:
            add_log("Agent başlatılıyor...", logging.INFO)
            agent = OdooImageSync(config)
            interval = config.get('scan_interval_seconds', 3)
            
            # Güncellenmiş klasör yolunu UI'a yansıt
            folder_text.value = f"İzlenen Klasör: {config.get('watch_folder')}"
            page.update()
            
            add_log(f"İzleme başladı (Aralık: {interval}sn)", logging.INFO)
            
            while not stop_event.is_set():
                try:
                    agent.download_ai_exports()
                    agent.process_folder()
                except Exception as e:
                    add_log(f"Hata oluştu: {str(e)}", logging.ERROR)
                    add_log("30 sn bekleyip tekrar denenecek...", logging.INFO)
                    # Beklerken de stop event'i kontrol et
                    for _ in range(30):
                        if stop_event.is_set(): break
                        time.sleep(1)
                    if stop_event.is_set(): break
                    try:
                        agent._connect()
                        add_log("Bağlantı yenilendi.", logging.INFO)
                    except Exception:
                        pass
                    continue
                
                # Normal bekleme süresi
                for _ in range(interval):
                    if stop_event.is_set(): break
                    time.sleep(1)
                    
        except Exception as e:
            add_log(f"Kritik Hata: {str(e)}\n{traceback.format_exc()}", logging.ERROR)
        finally:
            if agent and hasattr(agent, '_db'):
                agent._db.close()
            is_running = False
            status_text.value = "Durum: DURDURULDU"
            status_text.color = "red"
            start_btn.disabled = False
            stop_btn.disabled = True
            try:
                page.update()
            except Exception:
                pass

    # --- BUTON AKSİYONLARI ---
    def start_clicked(e):
        nonlocal is_running, sync_thread
        if is_running: return
        is_running = True
        stop_event.clear()
        
        status_text.value = "Durum: ÇALIŞIYOR"
        status_text.color = "green"
        start_btn.disabled = True
        stop_btn.disabled = False
        
        # UI'ı tazele
        page.update()
        
        # İşçiyi yeni bir thread'de başlat
        sync_thread = threading.Thread(target=sync_worker, daemon=True)
        sync_thread.start()

    def stop_clicked(e):
        if not is_running: return
        status_text.value = "Durum: DURDURULUYOR..."
        status_text.color = "orange"
        stop_btn.disabled = True
        page.update()
        stop_event.set()

    # --- ARAYÜZ DİZİLİMİ ---
    start_btn = ft.ElevatedButton("BAŞLAT", icon="play_arrow", color="white", bgcolor="green700", on_click=start_clicked)
    stop_btn = ft.ElevatedButton("DURDUR", icon="stop", color="white", bgcolor="red700", on_click=stop_clicked, disabled=True)

    header = ft.Row([
        ft.Icon("sync_rounded", size=46, color="blue400"),
        ft.Column([
            ft.Text("Uğurlar Odoo Image Sync", size=26, weight="bold"),
            folder_text,
        ], spacing=2)
    ])

    controls_row = ft.Row([
        start_btn, 
        stop_btn,
        ft.Container(expand=True),
        status_text
    ])

    # Koyu gri, modern bir log kutusu (Bordersız, %100 güvenli)
    log_container = ft.Container(
        content=log_view,
        expand=True,
        bgcolor="#1E1E1E",
        border_radius=10,
        padding=10
    )

    page.add(
        header,
        ft.Divider(height=20, color="white24"),
        controls_row,
        ft.Container(height=10),
        ft.Text("İşlem Logları:", size=16, weight="bold"),
        log_container
    )

if __name__ == "__main__":
    ft.run(main)
