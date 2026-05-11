@echo off
chcp 65001 >nul
title Ugurlar Image Sync Agent
echo ========================================
echo   Ugurlar Odoo Image Sync Agent
echo   Kapatmak icin bu pencereyi kapatin
echo ========================================
echo.

REM -- Agent klasorune git
cd /d "%~dp0"

REM -- Ag surucusu baglantisi
echo Ag surucusu baglantisi kontrol ediliyor...
net use \\nbsrv02\Online_Data /user:cumas Bursa90! /persistent:yes >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Ag surucusu baglandi.
) else (
    echo [BILGI] Ag surucusu zaten bagli veya baglanti basarisiz.
)
echo.

REM -- Python kontrol
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [HATA] Python bulunamadi! Python yukleyin.
    pause
    exit /b 1
)

REM -- Pillow kontrol ve yukle
python -c "import PIL" >nul 2>&1
if %errorlevel% neq 0 (
    echo Pillow yukleniyor...
    pip install Pillow
)

echo Agent baslatiliyor...
echo.
python sync_agent.py

if %errorlevel% neq 0 (
    echo.
    echo [HATA] Agent durdu! Hata kodu: %errorlevel%
    pause
)
