import hashlib
import os
import requests
import time
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urljoin
import uuid
import re
import threading
import subprocess

def get_root_domain(url):
    parsed_url = urlparse(url)
    return f"{parsed_url.scheme}://{parsed_url.netloc}"

class BunkrDownloader:
    def __init__(self, download_folder, log_callback=None, enable_widgets_callback=None, update_progress_callback=None, update_global_progress_callback=None, headers=None, max_workers=5, translations=None, tr=None):
        self.download_folder = download_folder
        self.log_callback = log_callback
        self.enable_widgets_callback = enable_widgets_callback
        self.update_progress_callback = update_progress_callback
        self.update_global_progress_callback = update_global_progress_callback
        self.session = requests.Session()
        self.headers = headers or {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
            'Referer': 'https://bunkr.site/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        self.cancel_requested = False
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.total_files = 0
        self.completed_files = 0
        self.max_downloads = max_workers
        self.log_messages = []
        self.notification_interval = 10
        self.start_notification_thread()
        self.translations = translations or {}
        self.tr = tr  # Add this line to store the translation function 

    def start_notification_thread(self):
        def notify_user():
            while not self.cancel_requested:
                if self.log_messages:
                    # Enviar todos los mensajes acumulados
                    if self.log_callback:
                        self.log_callback("\n".join(self.log_messages))
                    self.log_messages.clear()
                time.sleep(self.notification_interval)

        # Iniciar un hilo para notificaciones periódicas
        notification_thread = threading.Thread(target=notify_user, daemon=True)
        notification_thread.start()

    def tr(self, key):
        # Obtener la traducción para la clave dada
        return self.translations.get(key, key)

    def log(self, message_key, url=None):
        message = self.tr(message_key)
        domain = urlparse(url).netloc if url else "General"
        full_message = f"{domain}: {message}"
        self.log_messages.append(full_message)  # Agregar mensaje a la cola

    def request_cancel(self):
        self.cancel_requested = True
        self.log("Download has been cancelled.")
        self.shutdown_executor()

    def shutdown_executor(self):
        self.executor.shutdown(wait=False)
        self.log("Executor shut down.")

    def clean_filename(self, filename):
        return re.sub(r'[<>:"/\\|?*\u200b]', '_', filename)
    
    def get_consistent_folder_name(self, url, default_name):
        # Genera un hash de la URL para crear un nombre único y consistente
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        folder_name = f"{default_name}_{url_hash}"
        return self.clean_filename(folder_name)

    def download_file(self, url_media, ruta_carpeta, file_id):
        """
        Downloads a file from the given URL and saves it to the specified path.
        This method replaces the original download logic with the one from the other project.
        """
        if self.cancel_requested:
            self.log("Descarga cancelada", url=url_media)
            return

        file_name = os.path.basename(urlparse(url_media).path)
        file_path = os.path.join(ruta_carpeta, file_name)
        
        if os.path.exists(file_path):
            self.log(f"El archivo ya existe, omitiendo: {file_path}")
            self.completed_files += 1
            if self.update_global_progress_callback:
                self.update_global_progress_callback(self.completed_files, self.total_files)
            return

        max_attempts = 3
        delay = 1
        for attempt in range(max_attempts):
            try:
                self.log(f"Intentando descargar {url_media} (Intento {attempt + 1}/{max_attempts})")
                response = self.session.get(url_media, headers=self.headers, stream=True)
                response.raise_for_status()

                total_size = int(response.headers.get('content-length', 0))
                downloaded_size = 0

                with open(file_path, 'wb') as file:
                    for chunk in response.iter_content(chunk_size=65536):  # 64KB chunks
                        if self.cancel_requested:
                            self.log("Descarga cancelada durante la descarga del archivo.", url=url_media)
                            file.close()
                            os.remove(file_path)
                            return
                        file.write(chunk)
                        downloaded_size += len(chunk)
                        if self.update_progress_callback:
                            self.update_progress_callback(downloaded_size, total_size, file_id=file_id, file_path=file_path)

                self.log("Archivo descargado", url=url_media)
                if self.log_callback:
                    self.log_callback(f"Descarga completada: {file_name}")
                self.completed_files += 1
                if self.update_global_progress_callback:
                    self.update_global_progress_callback(self.completed_files, self.total_files)
                break

            except requests.RequestException as e:
                if hasattr(e, 'response') and e.response.status_code == 429:
                    self.log(f"Límite de tasa excedido. Reintentando después de {delay} segundos.")
                    time.sleep(delay)
                    delay *= 2  # Retroceso exponencial para limitación de tasa
                else:
                    self.log(f"Error al descargar de {url_media}: {e}. Intento {attempt + 1} de {max_attempts}", url=url_media)
                    if attempt < max_attempts - 1:
                        time.sleep(3)
    
    def descargar_post_bunkr(self, url_post):
        try:
            self.log(f"Iniciando descarga para el post: {url_post}")
            response = self.session.get(url_post, headers=self.headers)
            self.log(f"Código de estado de la respuesta: {response.status_code} para {url_post}")
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')

                # Extraer y sanitizar el nombre de la carpeta para el post
                file_name_tag = soup.find('h1', {'class': 'truncate'})
                if file_name_tag:
                    file_name = file_name_tag.text.strip()
                    file_name = self.clean_filename(file_name)[:50]  # Limitar a 50 caracteres
                else:
                    file_name = "bunkr_post"
                
                # Create the main folder for the album
                folder_name = self.get_consistent_folder_name(url_post, file_name)
                ruta_carpeta = os.path.join(self.download_folder, folder_name)
                os.makedirs(ruta_carpeta, exist_ok=True)

                # Use gallery-dl to download the album
                self.log(f"Using gallery-dl to download album: {url_post}")
                command = [
                    'gallery-dl',
                    '--directory', ruta_carpeta,  # Specify the download directory
                    url_post
                ]
                result = subprocess.run(command, capture_output=True, text=True)

                if result.returncode == 0:
                    self.log(f"Album downloaded successfully: {url_post}")
                else:
                    self.log(f"Failed to download album: {url_post}")
                    self.log(f"gallery-dl output: {result.stderr}")

                if self.enable_widgets_callback:
                    self.enable_widgets_callback()
            else:
                self.log(f"Error al acceder al post {url_post}: Estado {response.status_code}")
        except Exception as e:
            self.log(f"Error al acceder al post {url_post}: {e}")
            if self.enable_widgets_callback:
                self.enable_widgets_callback()

    def descargar_perfil_bunkr(self, url_perfil):
        try:
            self.log(f"Iniciando descarga para el perfil: {url_perfil}")
            response = self.session.get(url_perfil, headers=self.headers)
            self.log(f"Código de estado de la respuesta: {response.status_code} para {url_perfil}")
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')

                # Extraer y sanitizar el nombre de la carpeta para el perfil
                file_name_tag = soup.find('h1', {'class': 'truncate'})
                if file_name_tag:
                    folder_name = file_name_tag.text.strip()
                else:
                    folder_name = "bunkr_profile"
                
                # Usar el nuevo método para obtener un nombre de carpeta consistente
                folder_name = self.get_consistent_folder_name(url_perfil, folder_name)
                ruta_carpeta = os.path.join(self.download_folder, folder_name)
                os.makedirs(ruta_carpeta, exist_ok=True)

                # Use gallery-dl to download the profile
                self.log(f"Using gallery-dl to download profile: {url_perfil}")
                command = ['gallery-dl', '-d', ruta_carpeta, url_perfil]
                result = subprocess.run(command, capture_output=True, text=True)

                if result.returncode == 0:
                    self.log(f"Profile downloaded successfully: {url_perfil}")
                else:
                    self.log(f"Failed to download profile: {url_perfil}")
                    self.log(f"gallery-dl output: {result.stderr}")

                if self.enable_widgets_callback:
                    self.enable_widgets_callback()
            else:
                self.log(f"Failed to access the profile {url_perfil}: Status {response.status_code}")
        except Exception as e:
            self.log(f"Failed to access the profile {url_perfil}: {e}")
            if self.enable_widgets_callback:
                self.enable_widgets_callback()

    def set_max_downloads(self, max_downloads):
        self.max_downloads = max_downloads