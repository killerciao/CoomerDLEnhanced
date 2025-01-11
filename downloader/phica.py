import os
import json
import re
import queue
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import requests
import hashlib
from concurrent.futures import ThreadPoolExecutor

# Import the BunkrDownloader class from bunkr.py
from .bunkr import BunkrDownloader
# Import the GofileDownloader class from gofile.py
from .gofile import GofileDownloader

class Phica:
    def __init__(self, download_folder, max_workers=5, log_callback=None, enable_widgets_callback=None, update_progress_callback=None, update_global_progress_callback=None, tr=None):
        self.download_folder = download_folder
        self.max_workers = max_workers
        self.descargadas = set()  # Set to track downloaded files
        self.log_callback = log_callback
        self.enable_widgets_callback = enable_widgets_callback
        self.update_progress_callback = update_progress_callback
        self.update_global_progress_callback = update_global_progress_callback
        self.cancel_requested = False  # Flag for cancel functionality
        self.total_files = 0
        self.completed_files = 0
        self.download_queue = queue.Queue()
        self.tr = tr
        self.external_links = []  # List to store external links
        self.translations = {}  # Initialize translations as an empty dictionary

        # Load cookies and handlers
        self.cookies = self.load_cookies("cookies_phica.json")
        self.handlers = self.load_handlers("handlers.json")
        self.legacy_bunkr_domains = [
            "bunkr.ax", "bunkr.cat", "bunkr.ru", "bunkrr.ru", "bunkr.su", "bunkrr.su",
            "bunkr.la", "bunkr.is", "bunkr.to"
        ]
        self.new_bunkr_domains = [
            "bunkr.ac", "bunkr.ci", "bunkr.cr", "bunkr.fi", "bunkr.ph", "bunkr.pk",
            "bunkr.ps", "bunkr.si", "bunkr.sk", "bunkr.ws", "bunkr.black", "bunkr.red",
            "bunkr.media", "bunkr.site"
        ]

    def convert_legacy_bunkr_link(self, url):
        """
        Converts a legacy Bunkr domain URL to a new Bunkr domain URL.
        """
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()

        # Check if the domain is a legacy Bunkr domain
        if domain in self.legacy_bunkr_domains:
            # Replace the legacy domain with a new domain (e.g., bunkr.si)
            new_domain = self.new_bunkr_domains[0]  # Use the first new domain as default
            new_url = parsed_url._replace(netloc=new_domain).geturl()
            self.log(self.tr(f"Converted legacy Bunkr link: {url} -> {new_url}"))
            return new_url

        # If the domain is not a legacy Bunkr domain, return the original URL
        return url
    def log(self, message):
        if self.log_callback:
            self.log_callback(message)

    def load_cookies(self, file_path):
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                cookies_list = json.load(file)
                # Convert list of cookies to a dictionary
                cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies_list}
                return cookies_dict
        return {}

    def load_handlers(self, file_path):
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                return json.load(file)
        return {}

    def sanitize_folder_name(self, name):
        return re.sub(r'[<>:"/\\|?*]', '_', name)

    def request_cancel(self):
        """
        Sets the cancel flag to stop ongoing downloads.
        """
        self.cancel_requested = True
        self.log(self.tr("Descarga cancelada por el usuario."))

    def download_files(self, link):
        try:
            # Reset cancel flag at the start of a new download
            self.cancel_requested = False

            # Fetch the page content
            response = requests.get(link, cookies=self.cookies)
            response.raise_for_status()

            # Parse the page content
            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract the thread title
            thread_title = self.extract_thread_title(soup)
            if not thread_title:
                self.log(self.tr("Thread title not found."))
                return

            # Create a folder for the thread
            folder_name = self.sanitize_folder_name(thread_title)
            download_folder = os.path.join(self.download_folder, folder_name)
            os.makedirs(download_folder, exist_ok=True)

            # Create separate folders for images and videos
            img_folder = os.path.join(download_folder, "img")
            video_folder = os.path.join(download_folder, "videos")
            os.makedirs(img_folder, exist_ok=True)
            os.makedirs(video_folder, exist_ok=True)

            # Download files from the current page
            self.download_files_from_page(soup, img_folder, video_folder)

            # Handle pagination (if there are multiple pages)
            next_page_url = self.extract_next_page_url(soup)
            while next_page_url and not self.cancel_requested:
                self.log(self.tr(f"Found next page: {next_page_url}"))
                response = requests.get(next_page_url, cookies=self.cookies)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                self.download_files_from_page(soup, img_folder, video_folder)
                next_page_url = self.extract_next_page_url(soup)

            # After downloading all files from the thread, download external files
            self.download_external_files(download_folder)

        except requests.RequestException as e:
            self.log(self.tr(f"Error fetching the page: {e}"))

    def extract_thread_title(self, soup):
        # Example: Find the thread title in the page content
        # Adjust the selector based on the actual page structure
        title_tag = soup.select_one(self.handlers.get("thread_title", "h1.p-title-value"))
        if title_tag:
            return title_tag.text.strip()
        return None

    def download_files_from_page(self, soup, img_folder, video_folder):
        # Existing code to find video tags, file links, and lightbox links...

        # Find external links (Bunkr, Gofile, Pixeldrain, etc.)
        external_links = soup.find_all('a', href=True)
        for link in external_links:
            href = link['href']
            if any(domain in href for domain in ["bunkr", "bunkrr", "gofile", "pixeldrain"]):  # Add "bunkrr" to the list
                # Convert legacy Bunkr links to new domains
                converted_link = self.convert_legacy_bunkr_link(href)
                self.external_links.append(converted_link)
                self.log(self.tr(f"Found external link: {converted_link}"))

        # Find all <a> tags with the file URL (attachments)
        file_links = soup.select(self.handlers.get("attachments_selector", "a.file-preview"))
        for file_link in file_links:
            if self.cancel_requested:
                break  # Stop processing if cancel is requested

            # Extract the relative file URL from the href attribute
            relative_file_url = file_link['href']
            # Construct the full file URL
            full_file_url = urljoin(self.base_url, relative_file_url)
            self.log(self.tr(f"Found file URL (a tag): {full_file_url}"))
            self.download_file(full_file_url, img_folder, video_folder)

        # Find all <a> tags with the class 'js-lbImage' (lightbox images)
        lightbox_links = soup.select('a.js-lbImage')
        for link in lightbox_links:
            if self.cancel_requested:
                break  # Stop processing if cancel is requested

            # Extract the file URL from the href attribute
            file_url = link.get('href')
            if file_url:
                full_file_url = urljoin(self.base_url, file_url)
                self.log(self.tr(f"Found file URL (lightbox link): {full_file_url}"))
                self.download_file(full_file_url, img_folder, video_folder)

        # Find external links (Bunkr, Gofile, Pixeldrain, etc.)
        external_links = soup.find_all('a', href=True)
        for link in external_links:
            href = link['href']
            if any(domain in href for domain in ["bunkr", "bunkrr", "gofile", "pixeldrain"]):  # Add "bunkrr" to the list
                self.external_links.append(href)
                self.log(self.tr(f"Found external link: {href}"))

    def extract_next_page_url(self, soup):
        # Find the "Next Page" link
        next_page_link = soup.select_one(self.handlers.get("next_page_selector", "a.pageNav-jump--next"))
        if next_page_link:
            return urljoin(self.base_url, next_page_link['href'])
        return None

    def generate_unique_file_name(self, file_url):
        """
        Generates a unique but fixed file name based on the file URL.
        """
        # Create a hash of the file URL to generate a unique but fixed name
        file_hash = hashlib.md5(file_url.encode()).hexdigest()
        file_extension = self.get_file_extension(file_url)
        return f"{file_hash}.{file_extension}"

    def download_file(self, file_url, img_folder, video_folder):
        try:
            if self.cancel_requested:
                return  # Skip downloading if cancel is requested

            # Generate a unique but fixed file name
            file_name = self.generate_unique_file_name(file_url)

            # Determine if the file is an image or video based on the extension
            file_extension = self.get_file_extension(file_url)
            if file_extension in ["jpg", "jpeg", "png", "gif", "webp"]:
                target_folder = img_folder
            elif file_extension in ["mp4", "webm", "mov", "avi"]:
                target_folder = video_folder
            else:
                target_folder = img_folder  # Default to images folder for unknown types

            # Check if the file already exists
            file_path = os.path.join(target_folder, file_name)
            if os.path.exists(file_path):
                self.log(self.tr(f"File already exists, skipping: {file_name}"))
                return

            # Fetch the file content with cookies
            response = requests.get(file_url, cookies=self.cookies, stream=True)
            response.raise_for_status()

            # Save the file to the folder
            with open(file_path, 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192):
                    if self.cancel_requested:
                        break  # Stop downloading if cancel is requested
                    file.write(chunk)

            if not self.cancel_requested:
                self.log(self.tr(f"File downloaded successfully: {file_path}"))
                self.descargadas.add(file_name)  # Add the file name to the set of downloaded files
        except requests.RequestException as e:
            self.log(self.tr(f"Error downloading the file: {e}"))

    def get_file_extension(self, url):
        # Extract the file extension from the URL
        parsed_url = urlparse(url)
        path = parsed_url.path
        # Match the file extension (e.g., jpg, png, etc.)
        match = re.search(r'\.([a-zA-Z0-9]+)$', path)
        if match:
            return match.group(1).lower()
        return "jpg"  # Default to .jpg if no extension is found

    def download_images_from_phica(self, url):
        self.base_url = url  # Set the base URL for the thread
        self.log(self.tr(f"Procesando hilo: {url}"))
        self.download_files(url)
        self.log(self.tr("Descarga completada."))

    def download_gofile_files(self, download_folder):
        """
        Download files from Gofile links sequentially and avoid duplicates.
        """
        if not self.external_links:
            return

        self.log(self.tr("Starting download of Gofile files..."))

        # Initialize the Gofile downloader
        gofile_downloader = GofileDownloader(
            download_folder=download_folder,  # Save files in the thread folder
            log_callback=self.log_callback,
            enable_widgets_callback=self.enable_widgets_callback,
            update_progress_callback=self.update_progress_callback,
            update_global_progress_callback=self.update_global_progress_callback,
            headers=None,
            max_workers=1,  # Set max_workers to 1 for sequential downloads
            tr=self.tr  # Pass the translation function as 'tr'
        )

        # Deduplicate Gofile links
        unique_gofile_links = set()
        for link in self.external_links:
            if "gofile" in link:
                unique_gofile_links.add(link)

        # Process Gofile links sequentially
        for link in unique_gofile_links:
            if self.cancel_requested:
                break  # Stop processing if cancel is requested
            gofile_downloader.descargar_gofile(link)

        self.log(self.tr("Gofile files download completed."))

    def download_external_files(self, download_folder):
        """
        Download files from external links (Bunkr, Gofile, Pixeldrain, etc.)
        """
        if not self.external_links:
            return

        self.log(self.tr("Starting download of external files..."))

        # Initialize the Bunkr downloader
        bunkr_downloader = BunkrDownloader(
            download_folder=download_folder,
            log_callback=self.log_callback,
            enable_widgets_callback=self.enable_widgets_callback,
            update_progress_callback=self.update_progress_callback,
            update_global_progress_callback=self.update_global_progress_callback,
            headers=None,
            max_workers=self.max_workers,
            translations=self.translations,  # Pass the translations dictionary
            tr=self.tr  # Pass the translation function explicitly
        )

        # Initialize the Gofile downloader
        self.download_gofile_files(download_folder)

        for link in self.external_links:
            if "bunkr" in link:
                # Convert legacy Bunkr links to new domains
                converted_link = self.convert_legacy_bunkr_link(link)
                bunkr_downloader.descargar_post_bunkr(converted_link)
            elif "pixeldrain" in link:
                # Implement Pixeldrain downloader here
                pass

        self.log(self.tr("External files download completed."))