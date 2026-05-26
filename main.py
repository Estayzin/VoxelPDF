"""
Punto de entrada para el .exe — arranca FastAPI + abre la ventana con pywebview.

Uso en desarrollo:
    python main.py

Distribución:
    build.bat  →  genera dist/Revisor Planimetria.exe
"""
import os
import socket
import sys
import threading
import time
import traceback


# ── Helpers de rutas ──────────────────────────────────────────────────────────
def resource_path(*parts: str) -> str:
    """Ruta a un archivo bundleado (sys._MEIPASS) o relativo al script."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def exe_dir() -> str:
    """Directorio donde vive el .exe (o el script en desarrollo)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ── Puerto libre ──────────────────────────────────────────────────────────────
def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def find_port(preferred: int = 8000) -> int:
    if _port_free(preferred):
        return preferred
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]


# ── Servidor ──────────────────────────────────────────────────────────────────
_server_error: str = ''   # captura errores del thread para mostrarlos al usuario


def start_server(port: int) -> None:
    global _server_error
    try:
        # --windowed elimina la consola → stdout/stderr son None.
        # uvicorn llama stderr.isatty() al configurar su logger → AttributeError.
        # Redirigir a devnull antes de cualquier import de uvicorn.
        if sys.stdout is None:
            sys.stdout = open(os.devnull, 'w')
        if sys.stderr is None:
            sys.stderr = open(os.devnull, 'w')

        os.environ['PLANIMETRIA_PORT'] = str(port)

        # En .exe: HTML está en sys._MEIPASS (bundleado por PyInstaller)
        # En desarrollo: HTML está dos niveles arriba, en VoxelBIM/app/
        if getattr(sys, '_MEIPASS', None):
            html_path = resource_path('planimetria.html')
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            html_path = os.path.normpath(
                os.path.join(script_dir, '..', '..', 'VoxelBIM', 'app', 'planimetria.html')
            )

        os.environ['PLANIMETRIA_HTML'] = html_path

        import uvicorn
        uvicorn.run('api:app', host='127.0.0.1', port=port, log_level='error')

    except Exception:
        _server_error = traceback.format_exc()
        # Escribir log junto al .exe para depuración
        try:
            log_path = os.path.join(exe_dir(), 'error.log')
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(_server_error)
        except Exception:
            pass


def wait_for_server(port: int, timeout: float = 45.0) -> bool:
    """Espera hasta que el servidor responda o se agote el tiempo.
    45 s para dar margen en la primera extracción del .exe en equipos lentos.
    """
    end = time.time() + timeout
    while time.time() < end:
        # Si el thread ya murió con error, no tiene sentido seguir esperando
        if _server_error:
            return False
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = find_port(8000)

    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()

    if not wait_for_server(port):
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()

        if _server_error:
            msg = (
                f'El servidor falló al iniciar.\n\n'
                f'Revisa error.log junto al .exe para más detalles.\n\n'
                f'{_server_error[:600]}'
            )
        else:
            msg = (
                f'No se pudo iniciar el servidor en el puerto {port}.\n\n'
                f'Puede que el antivirus esté bloqueando la app o el equipo '
                f'necesite más tiempo. Intenta abrirla de nuevo.'
            )

        messagebox.showerror('VoxelBIM — Error de inicio', msg)
        sys.exit(1)

    import webview
    webview.create_window(
        title='VoxelBIM — Revisor de Planimetría',
        url=f'http://127.0.0.1:{port}',
        width=1280,
        height=820,
        resizable=True,
        min_size=(900, 620),
    )
    webview.start()
