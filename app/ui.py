import datetime
import json
import queue
import sys
import re
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext
from typing import Optional, Tuple
from urllib.parse import ParseResult, parse_qs, urlparse
import webbrowser
import requests
from PIL import Image, ImageTk
import customtkinter as ctk
import psutil

# Import custom modules
from app.settings_window import SettingsWindow
from app.about_window import AboutWindow
from downloader.bunkr import BunkrDownloader
from downloader.downloader import Downloader
from downloader.erome import EromeDownloader
from downloader.simpcity import SimpCity
from downloader.phica import Phica
from downloader.gofile import GofileDownloader
from downloader.jpg5 import Jpg5Downloader
from app.progress_manager import ProgressManager

VERSION = "V0.8.5"
MAX_LOG_LINES = 50  # Maximum number of log lines

def extract_ck_parameters(url: ParseResult) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extracts the service, user, and post ID from the URL if they exist.
    """
    match = re.search(r"/(?P<service>[^/?]+)(/user/(?P<user>[^/?]+)(/post/(?P<post>[^/?]+))?)?", url.path)
    if match:
        site, service, post = match.group("service", "user", "post")
        return site, service, post
    return None, None, None

def extract_ck_query(url: ParseResult) -> Tuple[Optional[str], int]:
    """
    Attempts to extract the query and offset from the URL if they exist.
    """
    query = parse_qs(url.query)
    q = query.get("q", [None])[0]
    o = query.get("o", ["0"])[0]
    return q, int(o) if o.isdigit() else 0

class ImageDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.errors = []
        self.warnings = []
        self.title(f"Downloader [{VERSION}]")
        
        # Initialize attributes
        self.settings_window = SettingsWindow(self, self.tr, self.load_translations, self.update_ui_texts, self.save_language_preference, VERSION, self)
        self.about_window = AboutWindow(self, self.tr, VERSION)
        self.settings = self.settings_window.load_settings()
        lang = self.load_language_preference()
        self.load_translations(lang)
        self.image_downloader = None
        self.progress_bars = {}
        self.github_icon = self.load_icon("resources/img/github-logo-24.png", "GitHub", size=(16, 16))
        self.discord_icon = self.load_icon("resources/img/discord-alt-logo-24.png", "Discord", size=(16, 16))
        self.new_icon = self.load_icon("resources/img/dollar-circle-solid-24.png", "New Icon", size=(16, 16))
        self.download_folder = self.load_download_folder()
        self.active_downloader = None
        self.max_downloads = self.settings_window.settings.get('max_downloads', 3)

        self.icons = {
            'image': self.load_and_resize_image('resources/img/image_icon.png', (40, 40)),
            'video': self.load_and_resize_image('resources/img/video_icon.png', (40, 40)),
            'zip': self.load_and_resize_image('resources/img/zip_icon.png', (40, 40)),
            'default': self.load_and_resize_image('resources/img/default_icon.png', (40, 40))
        }
        
        # Configure the main window
        self.setup_window()
        self.initialize_ui()
        self.update_ui_texts()
        
        # Configure update queue
        self.update_queue = queue.Queue()
        self.check_update_queue()
        
        # Configure close events
        self.protocol("WM_DELETE_WINDOW", self.on_app_close)
        
        # Initialize progress manager
        self.progress_manager = ProgressManager(
            root=self,
            icons=self.icons,
            footer_speed_label=self.footer_speed_label,
            footer_eta_label=self.footer_eta_label,
            progress_bar=self.progress_bar,
            progress_percentage=self.progress_percentage
        )
        
        # Configure download folder
        if self.download_folder:
            self.folder_path.configure(text=self.download_folder)
    
    def setup_window(self):
        """
        Configures the initial properties of the window.
        """
        window_width, window_height = 1000, 600
        center_x = (self.winfo_screenwidth() - window_width) // 2
        center_y = (self.winfo_screenheight() - window_height) // 2
        self.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")
        self.minsize(window_width, window_height)
        if sys.platform == "win32":
            self.iconbitmap("resources/img/window.ico")
    
    def initialize_ui(self):
        """
        Initializes all UI components.
        """
        self.create_menu_bar()
        self.create_input_frame()
        self.create_options_frame()
        self.create_action_frame()
        self.create_log_textbox()
        self.create_progress_frame()
        self.create_footer()
        self.create_context_menu()
    
    def create_menu_bar(self):
        """
        Creates the custom menu bar.
        """
        self.menu_bar = ctk.CTkFrame(self, height=30, corner_radius=0)
        self.menu_bar.pack(side="top", fill="x")
        self.create_custom_menubar()
    
    def create_custom_menubar(self):
        """
        Adds custom buttons and icons to the menu bar.
        """
        # Main menu buttons
        self.add_menu_button("File", self.toggle_archivo_menu)
        self.add_menu_button("About", self.about_window.show_about)
        
        # Add custom icons
        self.add_icon_to_menu(self.github_icon, "GitHub", "https://github.com/emy69/CoomerDL")
        self.add_icon_to_menu(self.discord_icon, "Discord", "https://discord.gg/ku8gSPsesh")
        self.add_icon_to_menu(self.new_icon, "Support", "https://buymeacoffee.com/emy_69")
        
        # Initialize variables for dropdown menus
        self.archivo_menu_frame = None
        self.ayuda_menu_frame = None
        self.donaciones_menu_frame = None
    
    def add_menu_button(self, text: str, command):
        """
        Adds a button to the menu bar.
        """
        button = ctk.CTkButton(
            self.menu_bar,
            text=self.tr(text),
            width=80,
            fg_color="transparent",
            hover_color="gray25",
            command=command
        )
        button.pack(side="left")
        button.bind("<Button-1>", lambda e: "break")
    
    def add_icon_to_menu(self, icon: Optional[ctk.CTkImage], text: str, link: str):
        """
        Adds an icon with text to the menu bar.
        """
        if icon:
            frame = ctk.CTkFrame(self.menu_bar, cursor="hand2", fg_color="transparent", corner_radius=5)
            frame.pack(side="right", padx=5)
            label = ctk.CTkLabel(
                frame,
                image=icon,
                text=text,
                compound="left"
            )
            label.pack(padx=5, pady=5)
            frame.bind("<Enter>", lambda e: frame.configure(fg_color="gray25"))
            frame.bind("<Leave>", lambda e: frame.configure(fg_color="transparent"))
            label.bind("<Enter>", lambda e: frame.configure(fg_color="gray25"))
            label.bind("<Leave>", lambda e: frame.configure(fg_color="transparent"))
            label.bind("<Button-1>", lambda e: webbrowser.open(link))
    
    def create_input_frame(self):
        """
        Creates the input frame for the URL and download folder.
        """
        self.input_frame = ctk.CTkFrame(self)
        self.input_frame.pack(fill='x', padx=20, pady=20)
        self.input_frame.grid_columnconfigure(0, weight=1)
        self.input_frame.grid_rowconfigure(1, weight=1)
        
        self.url_label = ctk.CTkLabel(self.input_frame, text=self.tr("Website URL:"))
        self.url_label.grid(row=0, column=0, sticky='w')
        
        self.url_entry = ctk.CTkEntry(self.input_frame)
        self.url_entry.grid(row=1, column=0, sticky='ew', padx=(0, 5))
        
        self.browse_button = ctk.CTkButton(self.input_frame, text=self.tr("Select Folder"), command=self.select_folder)
        self.browse_button.grid(row=1, column=1, sticky='e')
        
        self.folder_path = ctk.CTkLabel(self.input_frame, text="", cursor="hand2", font=("Arial", 13))
        self.folder_path.grid(row=2, column=0, columnspan=2, sticky='w')
        self.folder_path.bind("<Button-1>", self.open_download_folder)
        self.folder_path.bind("<Enter>", self.on_hover_enter)
        self.folder_path.bind("<Leave>", self.on_hover_leave)
    
    def create_options_frame(self):
        """
        Creates the options frame for selecting download types.
        """
        self.options_frame = ctk.CTkFrame(self)
        self.options_frame.pack(pady=10, fill='x', padx=20)
        
        self.download_images_check = self.create_checkbox(self.options_frame, self.tr("Download Images"), default=True)
        self.download_videos_check = self.create_checkbox(self.options_frame, self.tr("Download Videos"), default=True)
        self.download_compressed_check = self.create_checkbox(self.options_frame, self.tr("Download Compressed Files"), default=True)
    
    def create_checkbox(self, parent, text: str, default: bool = False) -> ctk.CTkCheckBox:
        """
        Creates a checkbox.
        """
        checkbox = ctk.CTkCheckBox(parent, text=text)
        checkbox.pack(side='left', padx=10)
        if default:
            checkbox.select()
        return checkbox
    
    def create_action_frame(self):
        """
        Creates the action frame for download and cancel buttons.
        """
        self.action_frame = ctk.CTkFrame(self)
        self.action_frame.pack(pady=10, fill='x', padx=20)
        
        self.download_button = ctk.CTkButton(self.action_frame, text=self.tr("Download"), command=self.start_download)
        self.download_button.pack(side='left', padx=10)
        
        self.cancel_button = ctk.CTkButton(self.action_frame, text=self.tr("Cancel Download"), state="disabled", command=self.cancel_download)
        self.cancel_button.pack(side='left', padx=10)
        
        self.progress_label = ctk.CTkLabel(self.action_frame, text="")
        self.progress_label.pack(side='left', padx=10)
        
        self.download_all_check = ctk.CTkCheckBox(self.action_frame)
        self.download_all_check.pack(side='left', padx=10)
        self.download_all_check.configure(command=self.update_info_text)
        
        # Add the new button for reorganizing files
        self.reorganize_button = ctk.CTkButton(self.action_frame, text=self.tr("Reorganize Files"), command=self.reorganize_files)
        self.reorganize_button.pack(side='left', padx=10)
        
        self.update_info_text()
    
    def reorganize_files(self):
        """
        Reorganizes files by moving them from subfolders into 'IMAGES' and 'VIDEOS' folders inside the selected main folder,
        and then deletes the empty subfolders.
        """
        # Ask the user to select the main folder (e.g., MYFOLDER NAME)
        main_folder = filedialog.askdirectory(
            title=self.tr("Select the main folder (MYFOLDER NAME)"),
        )
        
        if not main_folder:
            # User canceled the folder selection
            return
        
        # Create 'IMAGES' and 'VIDEOS' folders inside the main folder
        images_folder = os.path.join(main_folder, "IMAGES")
        videos_folder = os.path.join(main_folder, "VIDEOS")
        os.makedirs(images_folder, exist_ok=True)
        os.makedirs(videos_folder, exist_ok=True)
        
        # Define image and video file extensions
        image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.svg', '.heic', '.raw')
        video_extensions = ('.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.mpeg', '.mpg', '.m4v', '.3gp', '.ogg')
        
        # Walk through the main folder and move files
        for root, dirs, files in os.walk(main_folder):
            # Skip the 'IMAGES' and 'VIDEOS' folders to avoid moving files twice
            if root == images_folder or root == videos_folder:
                continue
            
            for file in files:
                file_path = os.path.join(root, file)
                if file.lower().endswith(image_extensions):
                    # Move image files to the 'IMAGES' folder
                    new_path = os.path.join(images_folder, file)
                elif file.lower().endswith(video_extensions):
                    # Move video files to the 'VIDEOS' folder
                    new_path = os.path.join(videos_folder, file)
                else:
                    # Skip other file types
                    continue
                
                # Move the file
                try:
                    os.rename(file_path, new_path)
                    self.add_log_message_safe(f"Moved {file} to {os.path.basename(new_path)} folder.")
                except Exception as e:
                    self.add_log_message_safe(f"Error moving {file}: {e}")
        
        # Delete empty subfolders
        for root, dirs, files in os.walk(main_folder, topdown=False):
            # Skip the 'IMAGES' and 'VIDEOS' folders
            if root == images_folder or root == videos_folder:
                continue
            
            for dir in dirs:
                dir_path = os.path.join(root, dir)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        self.add_log_message_safe(f"Deleted empty folder: {dir_path}")
                except Exception as e:
                    self.add_log_message_safe(f"Error deleting folder {dir_path}: {e}")
        
        self.add_log_message_safe(self.tr("File reorganization completed."))
    
    def create_log_textbox(self):
        """
        Creates the textbox for displaying logs.
        """
        self.log_textbox = ctk.CTkTextbox(self, width=590, height=200, state='disabled')
        self.log_textbox.pack(pady=(10, 0), padx=20, fill='both', expand=True)
    
    def create_progress_frame(self):
        """
        Creates the frame for the progress bar.
        """
        self.progress_frame = ctk.CTkFrame(self)
        self.progress_frame.pack(pady=(0, 10), fill='x', padx=20)
        
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.pack(side='left', fill='x', expand=True, padx=(0, 10))
        
        self.progress_percentage = ctk.CTkLabel(self.progress_frame, text="0%")
        self.progress_percentage.pack(side='left')
        
        # Download icon
        self.download_icon = self.load_and_resize_image('resources/img/download_icon.png', (24, 24))
        
        self.toggle_details_button = ctk.CTkLabel(self.progress_frame, image=self.download_icon, text="", cursor="hand2")
        self.toggle_details_button.pack(side='left', padx=(5, 0))
        self.toggle_details_button.bind("<Button-1>", lambda e: self.toggle_progress_details())
        self.toggle_details_button.bind("<Enter>", lambda e: self.toggle_details_button.configure(fg_color="gray25"))
        self.toggle_details_button.bind("<Leave>", lambda e: self.toggle_details_button.configure(fg_color="transparent"))
        
        self.progress_details_frame = ctk.CTkFrame(self)
        self.progress_details_frame.place_forget()
    
    def create_footer(self):
        """
        Creates the footer to display speed and ETA.
        """
        footer = ctk.CTkFrame(self, height=30, corner_radius=0)
        footer.pack(side="bottom", fill="x")
        
        self.footer_eta_label = ctk.CTkLabel(footer, text="", font=("Arial", 10))
        self.footer_eta_label.pack(side="left", padx=20)
        
        self.footer_speed_label = ctk.CTkLabel(footer, text="", font=("Arial", 10))
        self.footer_speed_label.pack(side="right", padx=20)
    
    def create_context_menu(self):
        """
        Creates the context menu for the URL entry.
        """
        self.context_menu = tk.Menu(self.url_entry, tearoff=0)
        self.context_menu.add_command(label=self.tr("Copy"), command=self.copy_to_clipboard)
        self.context_menu.add_command(label=self.tr("Paste"), command=self.paste_from_clipboard)
        self.context_menu.add_command(label=self.tr("Cut"), command=self.cut_to_clipboard)
        
        self.url_entry.bind("<Button-3>", self.show_context_menu)
        self.bind("<Button-1>", self.on_click)
    
    def update_ui_texts(self):
        """
        Updates the UI texts based on the selected language.
        """
        # Update menu button texts
        for widget in self.menu_bar.winfo_children():
            if isinstance(widget, ctk.CTkButton):
                text = widget.cget("text").strip()
                if text in ["File", "About", "Donations"]:
                    widget.configure(text=self.tr(text))
        
        # Update other texts
        self.url_label.configure(text=self.tr("Website URL:"))
        self.browse_button.configure(text=self.tr("Select Folder"))
        self.download_images_check.configure(text=self.tr("Download Images"))
        self.download_videos_check.configure(text=self.tr("Download Videos"))
        self.download_compressed_check.configure(text=self.tr("Download Compressed Files"))
        self.download_button.configure(text=self.tr("Download"))
        self.cancel_button.configure(text=self.tr("Cancel Download"))
        self.title(self.tr(f"Downloader [{VERSION}]"))
        
        # Update info tooltip
        if hasattr(self, 'info_label'):
            self.create_tooltip(self.info_label, self.tr(
                "Select this option to download all available content from the profile,\n"
                "instead of only the posts from the provided URL."
            ))
        
        self.update_info_text()
    
    def toggle_archivo_menu(self):
        """
        Toggles the visibility of the file menu.
        """
        if self.archivo_menu_frame and self.archivo_menu_frame.winfo_exists():
            self.archivo_menu_frame.destroy()
        else:
            self.close_all_menus()
            self.archivo_menu_frame = self.create_menu_frame([
                (self.tr("Settings"), self.settings_window.open_settings),
                ("separator", None),
                (self.tr("Exit"), self.quit),
            ], x=0)
    
    def create_menu_frame(self, options, x: int) -> ctk.CTkFrame:
        """
        Creates a menu frame with the provided options.
        """
        menu_frame = ctk.CTkFrame(self, corner_radius=5, fg_color="gray25", border_color="black", border_width=1)
        menu_frame.place(x=x, y=30)
        menu_frame.bind("<Button-1>", lambda e: "break")
        
        for option in options:
            if option[0] == "separator":
                separator = ctk.CTkFrame(menu_frame, height=1, fg_color="gray50")
                separator.pack(fill="x", padx=5, pady=5)
                separator.bind("<Button-1>", lambda e: "break")
            elif option[1] is None:
                label = ctk.CTkLabel(menu_frame, text=option[0], anchor="w", fg_color="gray30")
                label.pack(fill="x", padx=5, pady=2)
                label.bind("<Button-1>", lambda e: "break")
            else:
                btn = ctk.CTkButton(
                    menu_frame,
                    text=option[0],
                    fg_color="transparent",
                    hover_color="gray35",
                    anchor="w",
                    text_color="white",
                    command=option[1]
                )
                btn.pack(fill="x", padx=5, pady=2)
                btn.bind("<Button-1>", lambda e: "break")
        
        return menu_frame
    
    def close_all_menus(self):
        """
        Closes all open dropdown menus.
        """
        for menu_frame in [self.archivo_menu_frame, self.ayuda_menu_frame, self.donaciones_menu_frame]:
            if menu_frame and menu_frame.winfo_exists():
                menu_frame.destroy()
    
    def load_and_resize_image(self, path: str, size: Tuple[int, int]) -> ctk.CTkImage:
        """
        Loads and resizes an image.
        """
        img = Image.open(path)
        return ctk.CTkImage(img, size=size)
    
    def load_icon(self, icon_path: str, icon_name: str, size: Tuple[int, int] = (16, 16)) -> Optional[ctk.CTkImage]:
        """
        Loads an icon and handles errors if it cannot be loaded.
        """
        try:
            return self.load_and_resize_image(icon_path, size)
        except Exception as e:
            self.add_log_message_safe(f"Error loading icon {icon_name}: {e}")
            return None
    
    def on_app_close(self):
        """
        Handles the application close event.
        """
        if self.is_download_active() and not self.active_downloader.cancel_requested:
            messagebox.showwarning(
                self.tr("Active Download"),
                self.tr("There is an active download. Please cancel the download before closing.")
            )
        else:
            self.destroy()
    
    def is_download_active(self) -> bool:
        """
        Checks if there is an active download.
        """
        return self.active_downloader is not None
    
    def close_program(self):
        """
        Closes all windows and terminates the main process.
        """
        self.destroy()
        current_process = psutil.Process(os.getpid())
        for handler in current_process.children(recursive=True):
            handler.kill()
        current_process.kill()
    
    def save_language_preference(self, language_code: str):
        """
        Saves the language preference.
        """
        config = {'language': language_code}
        with open('resources/config/languages/save_language/language_config.json', 'w', encoding='utf-8') as config_file:
            json.dump(config, config_file)
        self.load_translations(language_code)
        self.update_ui_texts()
    
    def load_language_preference(self) -> str:
        """
        Loads the language preference.
        """
        try:
            with open('resources/config/languages/save_language/language_config.json', 'r', encoding='utf-8') as config_file:
                config = json.load(config_file)
                return config.get('language', 'en')
        except FileNotFoundError:
            return 'en'
    
    def load_translations(self, lang: str):
        """
        Loads translations for the selected language.
        """
        path = "resources/config/languages/translations.json"
        with open(path, 'r', encoding='utf-8') as file:
            all_translations = json.load(file)
            self.translations = {key: value.get(lang, key) for key, value in all_translations.items()}
    
    def tr(self, text: str, **kwargs) -> str:
        """
        Returns the translated text.
        """
        translated_text = self.translations.get(text, text)
        if kwargs:
            translated_text = translated_text.format(**kwargs)
        return translated_text
    
    def select_folder(self):
        """
        Opens a dialog to select the download folder.
        """
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.download_folder = folder_selected
            self.folder_path.configure(text=folder_selected)
            self.save_download_folder(folder_selected)
    
    def load_download_folder(self) -> Optional[str]:
        """
        Loads the download folder from the configuration.
        """
        config_path = 'resources/config/download_path/download_folder.json'
        config_dir = Path(config_path).parent
        config_dir.mkdir(parents=True, exist_ok=True)
        if not Path(config_path).exists():
            with open(config_path, 'w', encoding='utf-8') as config_file:
                json.dump({'download_folder': ''}, config_file)
        try:
            with open(config_path, 'r', encoding='utf-8') as config_file:
                config = json.load(config_file)
                return config.get('download_folder', '')
        except json.JSONDecodeError:
            return ''
    
    def save_download_folder(self, folder_path: str):
        """
        Saves the download folder to the configuration.
        """
        config = {'download_folder': folder_path}
        with open('resources/config/download_path/download_folder.json', 'w', encoding='utf-8') as config_file:
            json.dump(config, config_file)
    
    def load_github_icon(self) -> Optional[ctk.CTkImage]:
        """
        Loads the GitHub icon.
        """
        return self.load_icon("resources/img/github-logo-24.png", "GitHub")
    
    def load_discord_icon(self) -> Optional[ctk.CTkImage]:
        """
        Loads the Discord icon.
        """
        return self.load_icon("resources/img/discord-alt-logo-24.png", "Discord")
    
    def load_new_icon(self) -> Optional[ctk.CTkImage]:
        """
        Loads the new support icon.
        """
        return self.load_icon("resources/img/dollar-circle-solid-24.png", "New Icon")
    
    def update_info_text(self):
        """
        Updates the text of the download all checkbox.
        """
        text = self.tr("Download entire profile") if self.download_all_check.get() else self.tr("Download only posts from the provided URL")
        self.download_all_check.configure(text=text)
        
        # Add info icon if it doesn't exist
        if not hasattr(self, 'info_label'):
            info_icon = self.load_and_resize_image('resources/img/info_icon.png', (16, 16))
            self.info_label = ctk.CTkLabel(self.action_frame, image=info_icon, text="", cursor="hand2")
            self.info_label.pack(side='left', padx=5)
            self.create_tooltip(self.info_label, self.tr(
                "Select this option to download all available content from the profile,\n"
                "instead of only the posts from the provided URL."
            ))
    
    def create_tooltip(self, widget: tk.Widget, text: str):
        """
        Creates a tooltip for a widget.
        """
        tooltip = tk.Toplevel(widget)
        tooltip.wm_overrideredirect(True)
        tooltip.withdraw()
        
        tooltip_frame = tk.Frame(tooltip, bg="#333333", relief='solid', bd=1, padx=10, pady=10)
        tooltip_label = tk.Label(tooltip_frame, text=text, bg="#333333", fg="white", font=("Arial", 10), justify="left")
        tooltip_label.pack()
        tooltip_frame.pack()
        
        def enter(event):
            x = widget.winfo_rootx() + 20
            y = widget.winfo_rooty() + 20
            tooltip.wm_geometry(f"+{x}+{y}")
            tooltip.deiconify()
        
        def leave(event):
            tooltip.withdraw()
        
        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)
    
    def toggle_progress_details(self):
        """
        Toggles the visibility of progress details.
        """
        self.progress_manager.toggle_progress_details()
    
    def center_progress_details_frame(self):
        """
        Centers the progress details frame.
        """
        self.progress_manager.center_progress_details_frame()
    
    def add_log_message_safe(self, message: str):
        """
        Adds a log message safely from threads.
        """
        if "error" in message.lower():
            self.errors.append(message)
        if "warning" in message.lower():
            self.warnings.append(message)
        
        def log_in_main_thread():
            self.log_textbox.configure(state='normal')
            self.log_textbox.insert('end', message + '\n')
            self.limit_log_lines()
            self.log_textbox.configure(state='disabled')
            self.log_textbox.yview_moveto(1)
        
        self.after(0, log_in_main_thread)
    
    def limit_log_lines(self):
        """
        Limits the number of lines in the log textbox.
        """
        log_lines = self.log_textbox.get("1.0", "end-1c").split("\n")
        if len(log_lines) > MAX_LOG_LINES:
            self.log_textbox.configure(state='normal')
            self.log_textbox.delete("1.0", f"{len(log_lines) - MAX_LOG_LINES}.0")
            self.log_textbox.configure(state='disabled')
    
    def export_logs(self):
        """
        Exports logs to a file.
        """
        log_folder = "resources/config/logs/"
        Path(log_folder).mkdir(parents=True, exist_ok=True)
        log_file_path = Path(log_folder) / f"log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            total_files = self.active_downloader.total_files if self.active_downloader else 0
            completed_files = self.active_downloader.completed_files if self.active_downloader else 0
            skipped_files = self.active_downloader.skipped_files if self.active_downloader else []
            failed_files = self.active_downloader.failed_files if self.active_downloader else []
            
            total_images = completed_files if self.download_images_check.get() else 0
            total_videos = completed_files if self.download_videos_check.get() else 0
            errors = len(self.errors)
            warnings = len(self.warnings)
            duration = datetime.datetime.now() - self.download_start_time if self.download_start_time else "N/A"
            
            skipped_files_summary = "\n".join(skipped_files)
            failed_files_summary = "\n".join(failed_files)
            
            summary = (
                f"{self.tr('Total files downloaded')}: {total_files}\n"
                f"{self.tr('Total images downloaded')}: {total_images}\n"
                f"{self.tr('Total videos downloaded')}: {total_videos}\n"
                f"{self.tr('Errors')}: {errors}\n"
                f"{self.tr('Warnings')}: {warnings}\n"
                f"{self.tr('Total download time')}: {duration}\n\n"
                f"{self.tr('Skipped files (already downloaded)')}:\n{skipped_files_summary}\n\n"
                f"{self.tr('Failed files')}:\n{failed_files_summary}\n\n"
            )
            
            with open(log_file_path, 'w', encoding='utf-8') as file:
                file.write(summary)
                file.write(self.log_textbox.get("1.0", tk.END))
            self.add_log_message_safe(self.tr("Logs successfully exported to {path}", path=log_file_path))
        except Exception as e:
            self.add_log_message_safe(self.tr("Failed to export logs: {e}", e=e))
    
    def copy_to_clipboard(self):
        """
        Copies the selected text to the clipboard.
        """
        try:
            selected_text = self.url_entry.selection_get()
            if selected_text:
                self.clipboard_clear()
                self.clipboard_append(selected_text)
            else:
                self.add_log_message_safe(self.tr("No text selected to copy."))
        except tk.TclError:
            self.add_log_message_safe(self.tr("No text selected to copy."))
    
    def paste_from_clipboard(self):
        """
        Pastes text from the clipboard into the URL entry.
        """
        try:
            clipboard_text = self.clipboard_get()
            if clipboard_text:
                try:
                    self.url_entry.delete("sel.first", "sel.last")
                except tk.TclError:
                    pass
                self.url_entry.insert(tk.INSERT, clipboard_text)
            else:
                self.add_log_message_safe(self.tr("No text in clipboard to paste."))
        except tk.TclError as e:
            self.add_log_message_safe(self.tr(f"Error pasting from clipboard: {e}"))
    
    def cut_to_clipboard(self):
        """
        Cuts the selected text and copies it to the clipboard.
        """
        try:
            selected_text = self.url_entry.selection_get()
            if selected_text:
                self.clipboard_clear()
                self.clipboard_append(selected_text)
                self.url_entry.delete("sel.first", "sel.last")
            else:
                self.add_log_message_safe(self.tr("No text selected to cut."))
        except tk.TclError:
            self.add_log_message_safe(self.tr("No text selected to cut."))
    
    def show_context_menu(self, event):
        """
        Shows the context menu.
        """
        self.context_menu.tk_popup(event.x_root, event.y_root)
        self.context_menu.grab_release()
    
    def check_update_queue(self):
        """
        Checks and executes tasks in the update queue.
        """
        while not self.update_queue.empty():
            task = self.update_queue.get_nowait()
            task()
        self.after(100, self.check_update_queue)
    
    def enable_widgets(self):
        """
        Enables widgets after an operation.
        """
        self.update_queue.put(lambda: self.download_button.configure(state="normal"))
        self.update_queue.put(lambda: self.cancel_button.configure(state="disabled"))
        self.update_queue.put(lambda: self.download_all_check.configure(state="normal"))
    
    def update_max_downloads(self, max_downloads: int):
        """
        Updates the maximum number of simultaneous downloads.
        """
        self.max_downloads = max_downloads
        for downloader in [getattr(self, attr, None) for attr in ['general_downloader', 'erome_downloader', 'bunkr_downloader']]:
            if downloader:
                downloader.max_workers = max_downloads
    
    def on_hover_enter(self, event):
        """
        Applies hover effect when entering the folder label.
        """
        self.folder_path.configure(font=("Arial", 13, "underline"))
    
    def on_hover_leave(self, event):
        """
        Removes hover effect when leaving the folder label.
        """
        self.folder_path.configure(font=("Arial", 13))
    
    def open_download_folder(self, event=None):
        """
        Opens the download folder in the file explorer.
        """
        if self.download_folder and os.path.exists(self.download_folder):
            try:
                if sys.platform == "win32":
                    os.startfile(self.download_folder)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", self.download_folder])
                else:
                    subprocess.Popen(["xdg-open", self.download_folder])
            except Exception as e:
                self.add_log_message_safe(self.tr("Error opening folder: {e}", e=e))
        else:
            messagebox.showerror(self.tr("Error"), self.tr("The folder does not exist or is invalid."))
    
    def on_click(self, event):
        """
        Closes dropdown menus if clicked outside of them.
        """
        widgets_to_ignore = [self.menu_bar]
        for frame in [self.archivo_menu_frame, self.ayuda_menu_frame, self.donaciones_menu_frame]:
            if frame and frame.winfo_exists():
                widgets_to_ignore.append(frame)
                widgets_to_ignore.extend(self.get_all_children(frame))
        if event.widget not in widgets_to_ignore:
            self.close_all_menus()
    
    def get_all_children(self, widget: tk.Widget) -> list:
        """
        Recursively gets all children of a widget.
        """
        children = widget.winfo_children()
        all_children = list(children)
        for child in children:
            all_children.extend(self.get_all_children(child))
        return all_children
    
    def start_download(self):
        """
        Starts the download process based on the provided URL.
        """
        url = self.url_entry.get().strip()
        if not self.download_folder:
            messagebox.showerror(self.tr("Error"), self.tr("Please select a download folder."))
            return
        
        self.download_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.download_start_time = datetime.datetime.now()
        self.errors = []
        download_all = self.download_all_check.get()
        
        parsed_url = urlparse(url)
        
        if "erome.com" in url:
            self.handle_erome_download(url)
        elif re.search(r"https?://([a-z0-9-]+\.)?bunkr\.[a-z]{2,}", url):
            self.handle_bunkr_download(url)
        elif parsed_url.netloc in ["coomer.su", "kemono.su"]:
            self.handle_general_download(parsed_url, download_all)
        elif "phica.eu" in url:  # Add this condition for Phica
            self.handle_phica_download(url)
        elif "simpcity.su" in url:
            self.handle_simpcity_download(url)
        elif "jpg5.su" in url:
            self.handle_jpg5_download()
        else:
            self.add_log_message_safe(self.tr("Invalid URL"))
            self.download_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")

    def handle_phica_download(self, url: str):
        """
        Handles downloading from Phica.
        """
        self.add_log_message_safe(self.tr("Downloading Phica"))
        self.setup_phica_downloader()  # No need to pass base_url
        self.active_downloader = self.phica_downloader
        target = self.active_downloader.download_images_from_phica
        args = (url,)
        self.start_download_thread(target, args)

    def setup_phica_downloader(self):
        """
        Configures the Phica downloader.
        """
        self.phica_downloader = Phica(
            download_folder=self.download_folder,
            log_callback=self.add_log_message_safe,
            enable_widgets_callback=self.enable_widgets,
            update_progress_callback=self.update_progress,
            update_global_progress_callback=self.update_global_progress,
            tr=self.tr
        )

    def handle_gofile_download(self, url: str):
        """
        Handles downloading from Gofile.
        """
        self.add_log_message_safe(self.tr("Downloading Gofile"))
        self.setup_gofile_downloader()
        self.active_downloader = self.gofile_downloader
        target = self.active_downloader.descargar_gofile
        args = (url,)
        self.start_download_thread(target, args)

    def setup_gofile_downloader(self):
        """
        Configures the Gofile downloader.
        """
        self.gofile_downloader = GofileDownloader(
            download_folder=self.download_folder,
            log_callback=self.add_log_message_safe,
            enable_widgets_callback=self.enable_widgets,
            update_progress_callback=self.update_progress,
            update_global_progress_callback=self.update_global_progress,
            headers=None,
            max_workers=self.max_downloads,
            tr=self.tr  # Pass the translation function here
        )
    
    def handle_erome_download(self, url: str):
        """
        Handles downloading from Erome.
        """
        self.add_log_message_safe(self.tr("Downloading Erome"))
        is_profile_download = "/a/" not in url
        self.setup_erome_downloader(is_profile_download=is_profile_download)
        self.active_downloader = self.erome_downloader
        if "/a/" in url:
            self.add_log_message_safe(self.tr("Album URL"))
            target = self.active_downloader.process_album_page
            args = (url, self.download_folder, self.download_images_check.get(), self.download_videos_check.get())
        else:
            self.add_log_message_safe(self.tr("Profile URL"))
            target = self.active_downloader.process_profile_page
            args = (url, self.download_folder, self.download_images_check.get(), self.download_videos_check.get())
        self.start_download_thread(target, args)
    
    def handle_bunkr_download(self, url: str):
        """
        Handles downloading from Bunkr.
        """
        self.add_log_message_safe(self.tr("Downloading Bunkr"))
        self.setup_bunkr_downloader()
        self.active_downloader = self.bunkr_downloader
        if "/v/" in url or "/i/" in url:
            self.add_log_message_safe(self.tr("Post URL"))
            target = self.active_downloader.descargar_post_bunkr
            args = (url,)
        else:
            self.add_log_message_safe(self.tr("Profile URL"))
            target = self.active_downloader.descargar_perfil_bunkr
            args = (url,)
        self.start_download_thread(target, args)
    
    def handle_general_download(self, parsed_url: ParseResult, download_all: bool):
        """
        Handles downloading from general sites like coomer.su or kemono.su.
        """
        self.add_log_message_safe(self.tr("Starting download..."))
        self.setup_general_downloader()
        self.active_downloader = self.general_downloader
        
        site = parsed_url.netloc
        service, user, post = extract_ck_parameters(parsed_url)
        if not service or not user:
            error_msg = self.tr("Could not extract necessary parameters from the URL.")
            self.add_log_message_safe(error_msg)
            messagebox.showerror(self.tr("Error"), error_msg)
            self.reset_download_buttons()
            return
        
        self.add_log_message_safe(self.tr("Extracted service: {service} from site: {site}", service=service, site=site))
        
        if post:
            self.add_log_message_safe(self.tr("Downloading single post..."))
            target = self.start_ck_post_download
            args = (site, service, user, post)
        else:
            query, offset = extract_ck_query(parsed_url)
            self.add_log_message_safe(self.tr("Downloading all user content..." if download_all else "Downloading only posts from the provided URL..."))
            target = self.start_ck_profile_download
            args = (site, service, user, query, download_all, offset)
        
        self.start_download_thread(target, args)
    
    def handle_simpcity_download(self, url: str):
        """
        Handles downloading from SimpCity.
        """
        self.add_log_message_safe(self.tr("Downloading SimpCity"))
        self.setup_simpcity_downloader()
        self.active_downloader = self.simpcity_downloader
        target = self.active_downloader.download_images_from_simpcity
        args = (url,)
        self.start_download_thread(target, args)
    
    def handle_jpg5_download(self):
        """
        Handles downloading from Jpg5.
        """
        self.add_log_message_safe(self.tr("Downloading from Jpg5"))
        self.setup_jpg5_downloader()
        self.active_downloader = self.jpg5_downloader
        target = self.active_downloader.descargar_imagenes
        args = ()
        self.start_download_thread(target, args)
    
    def start_download_thread(self, target, args):
        """
        Starts a download thread.
        """
        download_thread = threading.Thread(target=self.wrapped_download, args=(target, *args))
        download_thread.start()
    
    def wrapped_download(self, download_method, *args):
        """
        Wraps the download method to handle completion.
        """
        try:
            download_method(*args)
        finally:
            self.active_downloader = None
            self.enable_widgets()
            self.export_logs()
    
    def start_ck_profile_download(self, site: str, service: str, user: str, query: Optional[str], download_all: bool, initial_offset: int):
        """
        Starts downloading an entire profile.
        """
        download_info = self.active_downloader.download_media(site, user, service, query=query, download_all=download_all, initial_offset=initial_offset)
        if download_info:
            self.add_log_message_safe(f"Download info: {download_info}")
    
    def start_ck_post_download(self, site: str, service: str, user: str, post: str):
        """
        Starts downloading a single post.
        """
        download_info = self.active_downloader.download_single_post(site, post, service, user)
        if download_info:
            self.add_log_message_safe(f"Download info: {download_info}")
    
    def cancel_download(self):
        """
        Cancels the active download.
        """
        if self.active_downloader:
            self.active_downloader.request_cancel()
            self.active_downloader = None
            self.clear_progress_bars()
        else:
            self.add_log_message_safe(self.tr("No active download to cancel."))
        self.enable_widgets()
    
    def clear_progress_bars(self):
        """
        Clears all progress bars.
        """
        for file_id in list(self.progress_bars.keys()):
            self.remove_progress_bar(file_id)
    
    def show_context_menu(self, event):
        """
        Shows the context menu.
        """
        self.context_menu.tk_popup(event.x_root, event.y_root)
        self.context_menu.grab_release()
    
    # Methods for setting up different downloaders
    def setup_erome_downloader(self, is_profile_download: bool):
        """
        Configures the Erome downloader.
        """
        self.erome_downloader = EromeDownloader(
            root=self,
            enable_widgets_callback=self.enable_widgets,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',
                'Referer': 'https://www.erome.com/'
            },
            log_callback=self.add_log_message_safe,
            update_progress_callback=self.update_progress,
            update_global_progress_callback=self.update_global_progress,
            download_images=self.download_images_check.get(),
            download_videos=self.download_videos_check.get(),
            is_profile_download=is_profile_download,
            max_workers=self.max_downloads,
            tr=self.tr
        )
    
    def setup_simpcity_downloader(self):
        """
        Configures the SimpCity downloader.
        """
        self.simpcity_downloader = SimpCity(
            download_folder=self.download_folder,
            log_callback=self.add_log_message_safe,
            enable_widgets_callback=self.enable_widgets,
            update_progress_callback=self.update_progress,
            update_global_progress_callback=self.update_global_progress,
            tr=self.tr
        )
    
    def setup_bunkr_downloader(self):
        """
        Configures the Bunkr downloader.
        """
        self.bunkr_downloader = BunkrDownloader(
            download_folder=self.download_folder,
            log_callback=self.add_log_message_safe,
            enable_widgets_callback=self.enable_widgets,
            update_progress_callback=self.update_progress,
            update_global_progress_callback=self.update_global_progress,
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                'Referer': 'https://bunkr.site/',
            },
            max_workers=self.max_downloads,
            tr=self.tr  # Pass the translation function if needed
        )
        
    def setup_general_downloader(self):
        """
        Configures the general downloader for coomer.su and kemono.su.
        """
        self.general_downloader = Downloader(
            download_folder=self.download_folder,
            log_callback=self.add_log_message_safe,
            enable_widgets_callback=self.enable_widgets,
            update_progress_callback=self.update_progress,
            update_global_progress_callback=self.update_global_progress,
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                'Referer': 'https://coomer.su/',
            },
            download_images=self.download_images_check.get(),
            download_videos=self.download_videos_check.get(),
            download_compressed=self.download_compressed_check.get(),
            tr=self.tr,
            max_workers=self.max_downloads,
            folder_structure=self.settings_window.settings.get('folder_structure', 'default')
        )
    
    def setup_jpg5_downloader(self):
        """
        Configures the Jpg5 downloader.
        """
        self.jpg5_downloader = Jpg5Downloader(
            url=self.url_entry.get().strip(),
            carpeta_destino=self.download_folder,
            log_callback=self.add_log_message_safe,
            tr=self.tr,
            progress_manager=self.progress_manager,
            max_workers=self.max_downloads
        )
    
    # Methods related to progress
    def update_progress(self, downloaded: int, total: int, file_id: Optional[str] = None, file_path: Optional[str] = None, speed: Optional[str] = None, eta: Optional[str] = None):
        """
        Updates the download progress.
        """
        self.progress_manager.update_progress(downloaded, total, file_id, file_path, speed, eta)
    
    def remove_progress_bar(self, file_id: str):
        """
        Removes a specific progress bar.
        """
        self.progress_manager.remove_progress_bar(file_id)
    
    def update_global_progress(self, completed_files: int, total_files: int):
        """
        Updates the global download progress.
        """
        self.progress_manager.update_global_progress(completed_files, total_files)
    
    # Methods for translation and localization
    def tr(self, text: str, **kwargs) -> str:
        """
        Translates the given text using the loaded translations.
        """
        translated_text = self.translations.get(text, text)
        if kwargs:
            translated_text = translated_text.format(**kwargs)
        return translated_text
    
    # Methods for managing menus and events
    def toggle_progress_details(self):
        """
        Toggles the visibility of progress details.
        """
        self.progress_manager.toggle_progress_details()
    
    def center_progress_details_frame(self):
        """
        Centers the progress details frame.
        """
        self.progress_manager.center_progress_details_frame()
    
    # Methods for handling downloads
    def start_download(self):
        """
        Starts the download process based on the provided URL.
        """
        url = self.url_entry.get().strip()
        if not self.download_folder:
            messagebox.showerror(self.tr("Error"), self.tr("Please select a download folder."))
            return
        
        self.download_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.download_start_time = datetime.datetime.now()
        self.errors = []
        download_all = self.download_all_check.get()
        
        parsed_url = urlparse(url)
        
        if "erome.com" in url:
            self.handle_erome_download(url)
        elif re.search(r"https?://([a-z0-9-]+\.)?bunkr\.[a-z]{2,}", url):
            self.handle_bunkr_download(url)
        elif re.search(r"https?://([a-z0-9-]+\.)?bunkrr\.[a-z]{2,}", url):
            self.handle_bunkr_download(url)
        elif re.search(r"https?://([a-z0-9-]+\.)?bunkrrr\.[a-z]{2,}", url):
            self.handle_bunkr_download(url)
        elif parsed_url.netloc in ["coomer.su", "kemono.su"]:
            self.handle_general_download(parsed_url, download_all)
        elif "gofile.io" in url:
            self.handle_gofile_download(url)        
        elif "phica.eu" in url:
            self.handle_phica_download(url)
        elif "simpcity.su" in url:
            self.handle_simpcity_download(url)
        elif "jpg5.su" in url:
            self.handle_jpg5_download()
        else:
            self.add_log_message_safe(self.tr("Invalid URL"))
            self.download_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
    
    def start_ck_profile_download(self, site: str, service: str, user: str, query: Optional[str], download_all: bool, initial_offset: int):
        """
        Starts downloading an entire profile.
        """
        download_info = self.active_downloader.download_media(site, user, service, query=query, download_all=download_all, initial_offset=initial_offset)
        if download_info:
            self.add_log_message_safe(f"Download info: {download_info}")
    
    def start_ck_post_download(self, site: str, service: str, user: str, post: str):
        """
        Starts downloading a single post.
        """
        download_info = self.active_downloader.download_single_post(site, post, service, user)
        if download_info:
            self.add_log_message_safe(f"Download info: {download_info}")
    
    def wrapped_download(self, download_method, *args):
        """
        Wraps the download method to handle completion.
        """
        try:
            download_method(*args)
        finally:
            self.active_downloader = None
            self.enable_widgets()
            self.export_logs()
    
    # Methods for handling menus and events
    def on_click(self, event):
        """
        Closes dropdown menus if clicked outside of them.
        """
        widgets_to_ignore = [self.menu_bar]
        for frame in [self.archivo_menu_frame, self.ayuda_menu_frame, self.donaciones_menu_frame]:
            if frame and frame.winfo_exists():
                widgets_to_ignore.append(frame)
                widgets_to_ignore.extend(self.get_all_children(frame))
        if event.widget not in widgets_to_ignore:
            self.close_all_menus()
    
    def get_all_children(self, widget: tk.Widget) -> list:
        """
        Recursively gets all children of a widget.
        """
        children = widget.winfo_children()
        all_children = list(children)
        for child in children:
            all_children.extend(self.get_all_children(child))
        return all_children
    
    # Methods for handling the update queue
    def check_update_queue(self):
        """
        Checks and executes tasks in the update queue.
        """
        while not self.update_queue.empty():
            task = self.update_queue.get_nowait()
            task()
        self.after(100, self.check_update_queue)
    
    def enable_widgets(self):
        """
        Enables widgets after an operation.
        """
        self.update_queue.put(lambda: self.download_button.configure(state="normal"))
        self.update_queue.put(lambda: self.cancel_button.configure(state="disabled"))
        self.update_queue.put(lambda: self.download_all_check.configure(state="normal"))
    
    # Methods for error handling and logging
    def log_error(self, error_message: str):
        """
        Logs an error.
        """
        self.errors.append(error_message)
        self.add_log_message_safe(f"Error: {error_message}")
    
    def log_warning(self, warning_message: str):
        """
        Logs a warning.
        """
        self.warnings.append(warning_message)
        self.add_log_message_safe(f"Warning: {warning_message}")
    
    # Methods for loading icons
    def load_github_icon(self) -> Optional[ctk.CTkImage]:
        """
        Loads the GitHub icon.
        """
        return self.load_icon("resources/img/github-logo-24.png", "GitHub")
    
    def load_discord_icon(self) -> Optional[ctk.CTkImage]:
        """
        Loads the Discord icon.
        """
        return self.load_icon("resources/img/discord-alt-logo-24.png", "Discord")
    
    def load_new_icon(self) -> Optional[ctk.CTkImage]:
        """
        Loads the new support icon.
        """
        return self.load_icon("resources/img/dollar-circle-solid-24.png", "New Icon")