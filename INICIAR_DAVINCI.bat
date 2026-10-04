@echo off
chcp 65001 >nul
cd /d "G:\mis proyectos de programacion\Davinci-agent"
echo Iniciando DaVinci Agent...
python app.py
if errorlevel 1 (
    echo.
    echo Error al iniciar. Revisa que Python y las dependencias esten instaladas.
    pause
)
