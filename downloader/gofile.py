import os
import re
import requests
import hashlib
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import threading
import time
import uuid
from pathvalidate import sanitize_filename


class GofileDownloader:
    def __init__(self, download_folder, log_callback=None, enable_widgets_callback=None, update_progress_callback=None, update_global_progress_callback=None, headers=None, max_workers=5, tr=None):
        self.download_folder = download_folder
        self.log_callback = log_callback
        self.enable_widgets_callback = enable_widgets_callback
        self.update_progress_callback = update_progress_callback
        self.update_global_progress_callback = update_global_progress_callback
        self.session = requests.Session()
        self.headers = headers or {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
            'Referer': 'https://gofile.io/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
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
        self.tr = tr  # Translation function
        self._token = None
        self.wt = None

    def start_notification_thread(self):
        def notify_user():
            while not self.cancel_requested:
                if self.log_messages:
                    if self.log_callback:
                        self.log_callback("\n".join(self.log_messages))
                    self.log_messages.clear()
                time.sleep(self.notification_interval)

        notification_thread = threading.Thread(target=notify_user, daemon=True)
        notification_thread.start()

    def log(self, message_key, url=None):
        # Use the tr function to translate the message
        message = self.tr(message_key) if self.tr else message_key
        domain = urlparse(url).netloc if url else "General"
        full_message = f"{domain}: {message}"
        self.log_messages.append(full_message)

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
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        folder_name = f"{default_name}_{url_hash}"
        return self.clean_filename(folder_name)

    def update_token(self):
        if not self._token:
            response = requests.post("https://api.gofile.io/accounts")
            if response.status_code == 200:
                data = response.json()
                if data["status"] == "ok":
                    self._token = data["data"]["token"]
                    self.log("Updated GoFile API token.")
                else:
                    self.log("Failed to fetch GoFile API token.")
            else:
                self.log("Failed to connect to GoFile API.")

    def update_wt(self):
        if not self.wt:
            response = requests.get("https://gofile.io/dist/js/global.js")
            if response.status_code == 200:
                alljs = response.text
                if 'appdata.wt = "' in alljs:
                    self.wt = alljs.split('appdata.wt = "')[1].split('"')[0]
                    self.log("Updated GoFile WT.")
                else:
                    self.log("Failed to extract WT from GoFile JS.")
            else:
                self.log("Failed to fetch GoFile JS.")

    def descargar_gofile(self, url, password=None):
        try:
            content_id = url.split("/")[-1]
            self.update_token()
            self.update_wt()

            hash_password = hashlib.sha256(password.encode()).hexdigest() if password else ""
            params = {"wt": self.wt, "cache": "true", "password": hash_password}
            headers = {"Authorization": f"Bearer {self._token}"}

            response = requests.get(f"https://api.gofile.io/contents/{content_id}", headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                if data["status"] == "ok":
                    if data["data"].get("passwordStatus", "passwordOk") == "passwordOk":
                        self._process_content(data["data"], self.download_folder)
                    else:
                        self.log("Invalid password.")
                else:
                    self.log("Failed to fetch content from GoFile API.")
            else:
                self.log("Failed to connect to GoFile API.")
        except Exception as e:
            self.log(f"Error accessing GoFile link: {e}")

    def _process_content(self, content, base_path):
        if content["type"] == "folder":
            folder_name = sanitize_filename(content["name"])
            folder_path = os.path.join(base_path, folder_name)
            os.makedirs(folder_path, exist_ok=True)
            for child_id, child in content["children"].items():
                self._process_content(child, folder_path)
        else:
            file_name = sanitize_filename(content["name"])
            file_path = os.path.join(base_path, file_name)
            self.download_file(content["link"], file_path)

    def download_file(self, link, file_path):
        try:
            dir = os.path.dirname(file_path)
            if not os.path.exists(dir):
                os.makedirs(dir)

            if not os.path.exists(file_path):
                headers = {"Cookie": f"accountToken={self._token}"}
                with requests.get(link, headers=headers, stream=True) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get("content-length", 0))
                    downloaded_size = 0

                    # Increase chunk size to 1 MB (1048576 bytes)
                    chunk_size = 1048576
                    with open(file_path, "wb") as file:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if self.cancel_requested:
                                self.log("Download cancelled during file download.", url=link)
                                file.close()
                                os.remove(file_path)
                                return
                            file.write(chunk)
                            downloaded_size += len(chunk)
                            if self.update_progress_callback:
                                self.update_progress_callback(downloaded_size, total_size, file_path=file_path)

                self.log(f"Downloaded: {file_path}")
            else:
                self.log(f"File already exists: {file_path}")
        except Exception as e:
            self.log(f"Failed to download {file_path}: {e}")


def main():
    downloader = GofileDownloader(download_folder="./output")
    downloader.descargar_gofile("https://gofile.io/d/CONTENT_ID", password="your_password")


if __name__ == "__main__":
    main()