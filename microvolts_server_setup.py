import tkinter as tk
from tkinter import ttk, messagebox, filedialog, font
import customtkinter
import requests
import zipfile
import os
import subprocess
from multiprocessing import Process, Queue
import json
import shutil
from pathlib import Path
import configparser
import secrets
import string
import sys
import time
import re
import queue
from collections import deque
import glob
import threading

customtkinter.set_appearance_mode("Dark")
customtkinter.set_default_color_theme("blue")

def worker_log(q, message):
    q.put({'type': 'log', 'message': message})

def worker_ask_yes_no(q, title, prompt):
    response_q = Queue()
    q.put({'type': 'ask', 'method': 'askyesno', 'title': title, 'prompt': prompt, 'response_queue': response_q})
    return response_q.get()

def worker_show_error(q, title, message):
    q.put({'type': 'showerror', 'title': title, 'message': message})

def worker_show_info(q, title, message):
    q.put({'type': 'showinfo', 'title': title, 'message': message})

def worker_install_llvm(q, config):
    try:
        worker_log(q, "Checking for LLVM (clang-cl) installation...")
        try:
            result = subprocess.run(['clang-cl', '--version'], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                worker_log(q, "LLVM (clang-cl) is already installed")
                q.put({'type': 'result', 'success': True})
                return
        except FileNotFoundError:
            pass
        
        worker_log(q, "LLVM (clang-cl) not found. Installing...")
        
        llvm_version = "18.1.8"
        llvm_url = f"https://github.com/llvm/llvm-project/releases/download/llvmorg-{llvm_version}/LLVM-{llvm_version}-win64.exe"
        
        worker_log(q, f"Downloading LLVM {llvm_version}...")
        response = requests.get(llvm_url, stream=True)
        response.raise_for_status()
        
        installer_path = os.path.join(config['project_path'], f"LLVM-{llvm_version}-win64.exe")
        
        with open(installer_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        worker_log(q, "LLVM downloaded successfully. Installing...")
        
        result = subprocess.run([installer_path, '/S', '/D=C:\\Program Files\\LLVM'], capture_output=True, text=True, check=False)
        
        try:
            os.remove(installer_path)
        except OSError:
            pass

        worker_log(q, "LLVM installation complete.")
        q.put({'type': 'result', 'success': True})

    except Exception as e:
        worker_log(q, f"LLVM installation failed: {e}")
        if worker_ask_yes_no(q, "LLVM Installation Failed", "LLVM installation failed. Continue anyway?"):
             q.put({'type': 'result', 'success': True})
        else:
             q.put({'type': 'result', 'success': False})

def worker_download_repository(q, config):
    try:
        worker_log(q, "Cloning MicroVolts Emulator repository...")
        repo_url = "https://github.com/SoWeBegin/MicrovoltsEmulator.git"
        repo_path = os.path.join(config['project_path'], "MicrovoltsEmulator")
        
        if os.path.exists(repo_path):
            worker_log(q, "Removing existing MicrovoltsEmulator directory...")
            shutil.rmtree(repo_path)
        
        worker_log(q, "Cloning repository (this may take a few minutes)...")
        result = subprocess.run([
            "git", "clone", "-b", "mv1.1_2.0", repo_url, repo_path
        ], capture_output=True, text=True, check=False)
        
        if result.returncode != 0:
            raise Exception(f"Git clone failed: {result.stderr}")
            
        worker_log(q, "Repository cloned successfully")
        q.put({'type': 'result', 'success': True})
    except Exception as e:
        worker_log(q, f"Failed to clone repository: {str(e)}")
        q.put({'type': 'result', 'success': False})

def worker_setup_vcpkg(q, config):
    try:
        worker_log(q, "Setting up vcpkg...")
        repo_path = os.path.join(config['project_path'], "MicrovoltsEmulator")
        ext_lib_path = os.path.join(repo_path, "ExternalLibraries")
        os.makedirs(ext_lib_path, exist_ok=True)
        
        vcpkg_path = os.path.join(ext_lib_path, "vcpkg")
        
        if not os.path.exists(os.path.join(vcpkg_path, ".git")):
            worker_log(q, "Cloning vcpkg repository...")
            if os.path.exists(vcpkg_path):
                shutil.rmtree(vcpkg_path)
            
            result = subprocess.run([
                "git", "clone", "https://github.com/microsoft/vcpkg.git", vcpkg_path
            ], capture_output=True, text=True, check=False)
            
            if result.returncode != 0:
                raise Exception(f"Git clone failed: {result.stderr}")
        else:
            worker_log(q, "vcpkg repository already exists.")

        worker_log(q, "Bootstrapping vcpkg...")
        bootstrap_script = os.path.join(vcpkg_path, "bootstrap-vcpkg.bat")
        result = subprocess.run([bootstrap_script], cwd=vcpkg_path, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            worker_log(q, f"Bootstrap warning/error: {result.stderr or result.stdout}")

        worker_log(q, "Integrating vcpkg with Visual Studio...")
        vcpkg_exe = os.path.join(vcpkg_path, "vcpkg.exe")
        result = subprocess.run([vcpkg_exe, "integrate", "install"], cwd=vcpkg_path, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            worker_log(f"vcpkg integrate install failed: {result.stderr or result.stdout}")
        else:
            worker_log(q, "vcpkg integrated successfully.")

        vcpkg_json_source = os.path.join(repo_path, "vcpkg.json")
        vcpkg_json_dest = os.path.join(vcpkg_path, "vcpkg.json")
        if os.path.exists(vcpkg_json_source):
            worker_log(q, f"Moving vcpkg.json to {vcpkg_path}")
            shutil.move(vcpkg_json_source, vcpkg_json_dest)
        else:
            worker_log(q, "Root vcpkg.json not found, skipping move. It might already be in place.")

        worker_log(q, "Running vcpkg install...")
        result = subprocess.run([vcpkg_exe, "install"], cwd=vcpkg_path, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise Exception(f"vcpkg install failed: {result.stderr or result.stdout}")

        worker_log(q, "vcpkg setup and package installation completed")
        q.put({'type': 'result', 'success': True})
    except Exception as e:
        worker_log(q, f"Failed to setup vcpkg: {str(e)}")
        q.put({'type': 'result', 'success': False})

def worker_delete_service(q, service_name):
    """Attempts to delete a Windows service."""
    try:
        worker_log(q, f"Attempting to delete service: {service_name}")
        # Use sc.exe to delete the service. This is a standard Windows command.
        # We don't check the return code here because it will fail if the service doesn't exist,
        # which is a normal and expected outcome in many cases.
        result = subprocess.run(['sc', 'delete', service_name], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            worker_log(q, f"Service '{service_name}' deleted successfully.")
        else:
            # It's not necessarily an error if the service doesn't exist.
            # We can check the output to be more specific.
            if "The specified service does not exist" in result.stderr:
                worker_log(q, f"Service '{service_name}' did not exist, no action needed.")
            else:
                worker_log(q, f"Warning: 'sc delete {service_name}' failed with code {result.returncode}: {result.stderr.strip()}")
        return True
    except Exception as e:
        worker_log(q, f"An error occurred while trying to delete service '{service_name}': {e}")
        # We don't want to fail the whole installation for this, so we return True.
        # The installer will likely fail with a more specific error if this was the root cause.
        return True
def worker_install_mariadb(q, config):
    try:
        if config['existing_mariadb']:
            worker_log(q, "Skipping MariaDB installation as per user's choice.")
            q.put({'type': 'result', 'success': True})
            return

        # Attempt to delete a lingering service from a previous failed install
        worker_delete_service(q, "MariaDB")

        worker_log(q, "Installing MariaDB...")
        mariadb_version = "11.5.1"
        installer_name = f"mariadb-{mariadb_version}-winx64.msi"
        
        try:
            script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        except NameError:
            script_dir = os.getcwd()

        installer_path = os.path.join(script_dir, installer_name)

        if not os.path.exists(installer_path):
            worker_log(q, f"MariaDB installer not found at '{installer_path}'. Attempting to download...")
            mariadb_url = f"https://archive.mariadb.org/mariadb-{mariadb_version}/winx64-packages/{installer_name}"
            
            try:
                response = requests.get(mariadb_url, stream=True)
                response.raise_for_status()

                with open(installer_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                worker_log(q, "MariaDB installer downloaded successfully.")
            except requests.exceptions.RequestException as e:
                error_msg = f"Could not download MariaDB installer: {e}. Please place '{installer_name}' in the same directory as the setup script and try again."
                worker_log(q, error_msg)
                worker_show_error(q, "Download Failed", error_msg)
                q.put({'type': 'result', 'success': False})
                return
        else:
            worker_log(q, f"Found existing MariaDB installer: {installer_path}")
        
        worker_log(q, "Starting MariaDB installation (this may take a few minutes)...")
        
        log_file_path = os.path.join(config['project_path'], "mariadb_install_log.txt")
        worker_log(q, f"MariaDB installation log will be saved to: {log_file_path}")

        install_cmd = [
            'msiexec', '/i', installer_path, '/qn',
            f'/L*v', log_file_path,
            f'PASSWORD={config["db_password"]}',
            'ADDLOCAL=ALL',
            'SERVICENAME=MariaDB',
            'PORT=3306',
            'CLEANUPDATA=1'
        ]
        result = subprocess.run(install_cmd, capture_output=True, text=True, check=False)

        if result.returncode not in [0, 3010]:
            log_contents = ""
            try:
                with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as log_file:
                    log_contents = log_file.read()
            except Exception as e:
                worker_log(q, f"Could not read MariaDB install log: {e}")

            if "CreateService failed (1073)" in log_contents:
                error_message = (
                    "MariaDB installation failed because the service already exists.\n\n"
                    "The setup tried to remove the old service automatically but failed, "
                    "likely due to insufficient permissions.\n\n"
                    "Please run this setup tool as an Administrator."
                )
                worker_log(q, "Detected 'CreateService failed (1073)' error. Instructing user to run as admin.")
            elif "data directory exist and not empty" in log_contents:
                error_message = (
                    "MariaDB installation failed because the data directory is not empty.\n\n"
                    "Please manually delete the following directory and then try again:\n"
                    "C:\\Program Files\\MariaDB 11.5\\data"
                )
                worker_log(q, "Detected 'data directory not empty' error. Instructing user to manually delete.")
            else:
                error_message = f"MariaDB installation failed with exit code {result.returncode}.\n\nPlease check the log file for details:\n{log_file_path}"
                worker_log(q, error_message)
                if log_contents:
                     worker_log(q, f"--- MariaDB Install Log (last 2000 chars) ---\n{log_contents[-2000:]}")

            worker_show_error(q, "MariaDB Installation Failed", error_message)
            q.put({'type': 'result', 'success': False})
            return

        worker_log(q, "MariaDB installed successfully.")
        q.put({'type': 'result', 'success': True})
    except Exception as e:
        worker_log(q, f"An unexpected error occurred during MariaDB installation: {e}")
        q.put({'type': 'result', 'success': False})

def worker_setup_database(q, config):
    try:
        worker_log(q, "Setting up database...")
        repo_path = os.path.join(config['project_path'], "MicrovoltsEmulator")
        sql_script_path = os.path.join(repo_path, "microvolts-db.sql")

        if not os.path.exists(sql_script_path):
            raise Exception("Database script not found")

        mysql_exe = ""
        custom_path = config.get("mariadb_path")

        if custom_path:
            path_to_check = os.path.join(custom_path, "bin", "mysql.exe")
            if os.path.exists(path_to_check):
                mysql_exe = path_to_check
                worker_log(q, f"Using custom MariaDB path: {mysql_exe}")

        if not mysql_exe:
            worker_log(q, "Custom MariaDB path not provided or invalid. Searching default locations...")
            for version in ["11.5", "11.4", "11.3", "11.2", "11.1", "11.0", "10.11", "10.6", "10.5"]:
                path = f"C:\\Program Files\\MariaDB {version}\\bin\\mysql.exe"
                if os.path.exists(path):
                    mysql_exe = path
                    worker_log(q, f"Found MariaDB at: {mysql_exe}")
                    break
        
        if not mysql_exe:
            raise Exception("Could not find mysql.exe. Please specify the path in the DB Config tab if you have an existing installation.")

        # Create the database first
        worker_log(q, f"Ensuring database '{config['db_name']}' exists...")
        create_db_cmd = [
            mysql_exe, "-u", config['db_username'], f"-p{config['db_password']}",
            "-h", config['db_ip'], f"-P", str(config['db_port']),
            "-e", f"CREATE DATABASE IF NOT EXISTS `{config['db_name']}`;"
        ]
        result = subprocess.run(create_db_cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise Exception(f"Failed to create database: {result.stderr}")
        worker_log(q, f"Database '{config['db_name']}' created or already exists.")

        # Now import the script
        with open(sql_script_path, 'r') as f:
            sql_script_content = f.read()

        import_cmd = [
            mysql_exe, "-u", config['db_username'], f"-p{config['db_password']}",
            "-h", config['db_ip'], f"-P", str(config['db_port']),
            "-D", config['db_name']
        ]
        result = subprocess.run(import_cmd, input=sql_script_content, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            raise Exception(f"Database script execution failed: {result.stderr}")

        worker_log(q, "Database setup complete.")
        q.put({'type': 'result', 'success': True})
    except Exception as e:
        worker_log(q, f"Failed to set up database: {e}")
        q.put({'type': 'result', 'success': False})

class MicroVoltsServerSetup(customtkinter.CTk):
    def __init__(self):
        super().__init__()
        self.title("MicroVolts Server Setup v3.0 | @Mikael")
        self.geometry("1100x850")
        self.resizable(True, True)

        self.title_font = customtkinter.CTkFont(family="Segoe UI", size=20, weight="bold")
        self.header_font = customtkinter.CTkFont(family="Segoe UI", size=13, weight="bold")

        self.project_path = tk.StringVar()
        self.local_ip = tk.StringVar()
        
        self.db_ip = tk.StringVar(value="127.0.0.1")
        self.db_port = tk.StringVar(value="3306")
        self.db_username = tk.StringVar(value="root")
        self.db_password = tk.StringVar()
        self.db_name = tk.StringVar(value="microvolts-db")

        self.config_file = "mv_setup_config.json"
        self.existing_mariadb = tk.BooleanVar(value=False)
        self.db_root_password = tk.StringVar()
        self.mariadb_path = tk.StringVar()

        self.state_file = "setup_state.json"
        self.setup_state = {}

        self.servers = []
        self.server_widgets = []
        self.server_manager = ServerProcessManager(self.log)
        self.console_server_selection = tk.StringVar()
        self.server_status_vars = {}
        
        self.gui_queue = Queue()
        self.command_editor_window = None
        self.worker_process = None
        self.current_step = 0
        self.setup_steps = []
        
        self.notebook = None

        self.setup_gui()
        self.load_settings()

        if not self.project_path.get():
            self.generate_random_password()
        
        self.center_window()
        self.process_gui_queue()
        
    def center_window(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.winfo_width() // 2)
        y = (self.winfo_screenheight() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")

    def browse_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.project_path.set(directory)

    def browse_mariadb_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.mariadb_path.set(directory)

    def load_settings(self):
        if os.path.exists(self.config_file):
            self.log(f"Loading settings from {self.config_file}")
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                
                self.project_path.set(config.get("project_path", ""))
                self.local_ip.set(config.get("local_ip", ""))
                self.db_ip.set(config.get("db_ip", "127.0.0.1"))
                self.db_port.set(config.get("db_port", "3306"))
                self.db_username.set(config.get("db_username", "root"))
                self.db_password.set(config.get("db_password", ""))
                self.db_name.set(config.get("db_name", "microvolts-db"))
                self.mariadb_path.set(config.get("mariadb_path", ""))
                
                for widgets in self.server_widgets:
                    widgets["frame"].destroy()
                self.server_widgets.clear()

                self.servers = config.get("servers", [])
                for server_data in self.servers:
                    self.add_server_row()
                    widgets = self.server_widgets[-1]
                    widgets["main_local_ip"].set(server_data.get("main_local_ip", ""))
                    widgets["main_public_ip"].set(server_data.get("main_public_ip", ""))
                    widgets["main_port"].set(server_data.get("main_port", ""))
                    widgets["main_ipc_port"].set(server_data.get("main_ipc_port", ""))
                    widgets["cast_local_ip"].set(server_data.get("cast_local_ip", ""))
                    widgets["cast_public_ip"].set(server_data.get("cast_public_ip", ""))
                    widgets["cast_port"].set(server_data.get("cast_port", ""))
                    widgets["cast_ipc_port"].set(server_data.get("cast_ipc_port", ""))

                self.log("Settings loaded successfully.")
            except Exception as e:
                self.log(f"Error loading settings: {e}")
                messagebox.showerror("Error", f"Could not load settings from {self.config_file}.\n{e}")
        else:
            self.log("No existing configuration file found. Starting with default settings.")

    def save_settings(self):
        self.log(f"Saving settings to {self.config_file}")
        try:
            servers_data = []
            for widgets in self.server_widgets:
                server_data = {
                    "main_local_ip": widgets["main_local_ip"].get(),
                    "main_public_ip": widgets["main_public_ip"].get(),
                    "main_port": widgets["main_port"].get(),
                    "main_ipc_port": widgets["main_ipc_port"].get(),
                    "cast_local_ip": widgets["cast_local_ip"].get(),
                    "cast_public_ip": widgets["cast_public_ip"].get(),
                    "cast_port": widgets["cast_port"].get(),
                    "cast_ipc_port": widgets["cast_ipc_port"].get(),
                }
                servers_data.append(server_data)

            config = {
                "project_path": self.project_path.get(),
                "local_ip": self.local_ip.get(),
                "db_ip": self.db_ip.get(),
                "db_port": self.db_port.get(),
                "db_username": self.db_username.get(),
                "db_password": self.db_password.get(),
                "db_name": self.db_name.get(),
                "mariadb_path": self.mariadb_path.get(),
                "servers": servers_data
            }
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=4)
            self.log("Settings saved successfully.")
        except Exception as e:
            self.log(f"Error saving settings: {e}")
            messagebox.showerror("Error", f"Could not save settings to {self.config_file}.\n{e}")
        
    def setup_gui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=20)
        
        title_label = customtkinter.CTkLabel(header_frame, text="MicroVolts Server Setup", font=self.title_font)
        title_label.pack(side="left")

        main_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        main_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(1, weight=1)

        path_frame = customtkinter.CTkFrame(main_frame)
        path_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        path_frame.grid_columnconfigure(0, weight=1)
        
        customtkinter.CTkEntry(path_frame, textvariable=self.project_path).grid(row=0, column=0, sticky="ew", pady=5, padx=5)
        customtkinter.CTkButton(path_frame, text="Browse...", command=self.browse_directory, width=100).grid(row=0, column=1, pady=5, padx=5)

        self.notebook = customtkinter.CTkTabview(main_frame)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        
        tab_names = ["Setup Progress", "Server Config", "DB Config", "Multi-Server", "Server Console", "Tools & Updates"]
        for name in tab_names:
            self.notebook.add(name)
            self.notebook.tab(name).grid_columnconfigure(0, weight=1)

        self.setup_progress_tab(self.notebook.tab("Setup Progress"))
        self.setup_server_config_tab(self.notebook.tab("Server Config"))
        self.setup_db_config_tab(self.notebook.tab("DB Config"))
        self.setup_multi_server_tab(self.notebook.tab("Multi-Server"))
        self.setup_console_tab(self.notebook.tab("Server Console"))
        self.setup_tools_tab(self.notebook.tab("Tools & Updates"))

        button_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=10)
        button_frame.grid_columnconfigure(0, weight=1)
        
        self.start_button = customtkinter.CTkButton(button_frame, text="Start Setup", command=self.start_setup)
        self.start_button.pack(side="left", padx=5)
        
        self.stop_button = customtkinter.CTkButton(button_frame, text="Stop Setup", command=self.stop_setup, state=tk.DISABLED, fg_color="#D32F2F", hover_color="#B71C1C")
        self.stop_button.pack(side="left", padx=5)
        
        customtkinter.CTkButton(button_frame, text="Exit", command=self.on_closing, fg_color="transparent", border_width=1).pack(side="right", padx=5)

    def setup_server_config_tab(self, tab):
        tab.grid_columnconfigure(1, weight=1)
        ip_frame = customtkinter.CTkFrame(tab)
        ip_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
        ip_frame.grid_columnconfigure(1, weight=1)
        customtkinter.CTkLabel(ip_frame, text="Local IP:").grid(row=0, column=0, sticky=tk.W, pady=2, padx=10)
        customtkinter.CTkEntry(ip_frame, textvariable=self.local_ip).grid(row=0, column=1, sticky="ew", pady=2, padx=5)
        customtkinter.CTkButton(ip_frame, text="Auto-detect", command=self.auto_detect_ip, width=120).grid(row=0, column=2, padx=10, pady=2)

    def setup_db_config_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        self.db_install_frame = customtkinter.CTkFrame(tab, fg_color="transparent")
        self.db_install_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.db_install_frame.grid_columnconfigure(1, weight=1)

        db_frame = customtkinter.CTkFrame(self.db_install_frame)
        db_frame.grid(row=0, column=0, columnspan=4, sticky="ew")
        db_frame.grid_columnconfigure(1, weight=1)
        db_frame.grid_columnconfigure(3, weight=1)

        customtkinter.CTkLabel(db_frame, text="DB IP:").grid(row=0, column=0, sticky=tk.W, pady=5, padx=10)
        customtkinter.CTkEntry(db_frame, textvariable=self.db_ip).grid(row=0, column=1, sticky="ew", pady=5, padx=5)
        customtkinter.CTkLabel(db_frame, text="DB Port:").grid(row=0, column=2, sticky=tk.W, pady=5, padx=10)
        customtkinter.CTkEntry(db_frame, textvariable=self.db_port).grid(row=0, column=3, sticky="ew", pady=5, padx=5)
        customtkinter.CTkLabel(db_frame, text="Username:").grid(row=1, column=0, sticky=tk.W, pady=5, padx=10)
        customtkinter.CTkEntry(db_frame, textvariable=self.db_username).grid(row=1, column=1, sticky="ew", pady=5, padx=5)
        customtkinter.CTkLabel(db_frame, text="DB Name:").grid(row=1, column=2, sticky=tk.W, pady=5, padx=10)
        customtkinter.CTkEntry(db_frame, textvariable=self.db_name).grid(row=1, column=3, sticky="ew", pady=5, padx=5)
        customtkinter.CTkLabel(db_frame, text="Password:").grid(row=2, column=0, sticky=tk.W, pady=5, padx=10)
        self.password_entry = customtkinter.CTkEntry(db_frame, textvariable=self.db_password, show="*")
        self.password_entry.grid(row=2, column=1, columnspan=2, sticky="ew", pady=5, padx=5)
        customtkinter.CTkButton(db_frame, text="Generate", command=self.generate_random_password, width=100).grid(row=2, column=3, padx=5, pady=5)

        customtkinter.CTkCheckBox(tab, text="Use existing MariaDB installation", variable=self.existing_mariadb, command=self.toggle_mariadb_fields).grid(row=1, column=0, sticky=tk.W, pady=10, padx=10)

        self.existing_db_frame = customtkinter.CTkFrame(tab)
        self.existing_db_frame.grid_columnconfigure(1, weight=1)
        customtkinter.CTkLabel(self.existing_db_frame, text="Root Password:").grid(row=0, column=0, sticky=tk.W, pady=5, padx=10)
        customtkinter.CTkEntry(self.existing_db_frame, textvariable=self.db_root_password, show="*").grid(row=0, column=1, sticky="ew", pady=5, padx=5)

        self.mariadb_path_frame = customtkinter.CTkFrame(self.existing_db_frame)
        self.mariadb_path_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5,0), padx=0)
        self.mariadb_path_frame.grid_columnconfigure(1, weight=1)

        customtkinter.CTkLabel(self.mariadb_path_frame, text="MariaDB Path:").grid(row=0, column=0, sticky=tk.W, pady=5, padx=10)
        customtkinter.CTkEntry(self.mariadb_path_frame, textvariable=self.mariadb_path, placeholder_text="Optional: Auto-detect if empty").grid(row=0, column=1, sticky="ew", pady=5, padx=5)
        customtkinter.CTkButton(self.mariadb_path_frame, text="Browse...", command=self.browse_mariadb_directory, width=100).grid(row=0, column=2, pady=5, padx=5)
        
        self.toggle_mariadb_fields()

    def setup_multi_server_tab(self, tab):
        tab.grid_rowconfigure(0, weight=1)
        self.server_list_frame = customtkinter.CTkScrollableFrame(tab)
        self.server_list_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.server_list_frame.grid_columnconfigure(0, weight=1)
        
        button_frame_multi = customtkinter.CTkFrame(tab, fg_color="transparent")
        button_frame_multi.grid(row=1, column=0, sticky="e", pady=(0,10), padx=10)
        add_server_button = customtkinter.CTkButton(button_frame_multi, text="+ Add Server", command=self.add_server_row, width=120)
        add_server_button.pack()

    def setup_progress_tab(self, tab):
        tab.grid_rowconfigure(0, weight=1)
        progress_frame = customtkinter.CTkFrame(tab)
        progress_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        progress_frame.grid_columnconfigure(0, weight=1)
        progress_frame.grid_rowconfigure(0, weight=1)
        self.log_text = customtkinter.CTkTextbox(progress_frame, font=("Consolas", 13))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.progress_bar = customtkinter.CTkProgressBar(progress_frame, mode='indeterminate')
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(10, 0))

    def setup_tools_tab(self, tab):
        tools_frame = customtkinter.CTkFrame(tab)
        tools_frame.grid(row=0, column=0, sticky="new", padx=10, pady=10)
        tools_frame.grid_columnconfigure(0, weight=1)

        self.update_button = customtkinter.CTkButton(tools_frame, text="Check for Updates & Recompile", command=self.check_for_updates)
        self.update_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        command_editor_button = customtkinter.CTkButton(tools_frame, text="Command Permissions Editor", command=self.open_command_editor)
        command_editor_button.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
        
        cache_frame = customtkinter.CTkFrame(tab)
        cache_frame.grid(row=1, column=0, sticky="new", padx=10, pady=10)
        cache_frame.grid_columnconfigure(0, weight=1)
        customtkinter.CTkButton(cache_frame, text="Clear Cache & Restart", command=self.clear_cache_and_restart, fg_color="#D32F2F", hover_color="#B71C1C").grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        
        self.setup_running = False
        self.update_all_consoles()

    def setup_console_tab(self, console_tab):
        console_tab.grid_columnconfigure(0, weight=1)
        console_tab.grid_rowconfigure(1, weight=1)

        controls_frame = customtkinter.CTkFrame(console_tab, fg_color="transparent")
        controls_frame.grid(row=0, column=0, sticky="ew", pady=(10, 10), padx=10)
        controls_frame.grid_columnconfigure(1, weight=1)
        
        action_frame = customtkinter.CTkFrame(controls_frame, fg_color="transparent")
        action_frame.pack(side="left")

        customtkinter.CTkButton(action_frame, text="Start All Servers", command=self.start_all_servers).pack(side="left", padx=(0, 5))
        customtkinter.CTkButton(action_frame, text="Stop All Servers", command=self.stop_all_servers, fg_color="#D32F2F", hover_color="#B71C1C").pack(side="left")

        status_frame = customtkinter.CTkFrame(controls_frame)
        status_frame.pack(side="right", padx=(10, 0))
        self.server_status_frame = status_frame

        console_frame = customtkinter.CTkFrame(console_tab)
        console_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0,10))
        console_frame.grid_columnconfigure(0, weight=1)
        console_frame.grid_rowconfigure(1, weight=1)

        selector_frame = customtkinter.CTkFrame(console_frame, fg_color="transparent")
        selector_frame.grid(row=0, column=0, sticky="ew", pady=(0,5))
        
        customtkinter.CTkLabel(selector_frame, text="Show output for:").pack(side="left")
        self.console_server_selector = customtkinter.CTkComboBox(selector_frame, variable=self.console_server_selection, state="readonly", width=200, command=self.on_server_select)
        self.console_server_selector.pack(side="left", padx=5)

        self.console_text = customtkinter.CTkTextbox(console_frame, state='disabled', font=("Consolas", 14))
        self.console_text.grid(row=1, column=0, sticky="nsew")
        
        self.console_text.tag_config("ERROR", foreground="#ff8787")
        self.console_text.tag_config("WARN", foreground="#ffd966")
        self.console_text.tag_config("INFO", foreground="#82c0ff")
        self.console_text.tag_config("SUCCESS", foreground="#78e08f")
        self.console_text.tag_config("DEBUG", foreground="#b2b2b2")
        self.console_text.tag_config("DEFAULT", foreground="#ffffff")

        self.console_outputs = {}
        self.max_console_lines = 1000

    def start_all_servers(self):
        if not self.project_path.get():
            messagebox.showerror("Error", "Please select an installation directory first.")
            return

        base_path = os.path.join(self.project_path.get(), "MicrovoltsEmulator", "x64")
        if not os.path.isdir(base_path):
            messagebox.showerror("Error", f"Server executable directory not found:\n{base_path}\n\nPlease build the project first.")
            return

        servers_to_start = {
            "AuthServer": os.path.join(base_path, "AuthServer.exe"),
            "MainServer": os.path.join(base_path, "MainServer.exe"),
            "CastServer": os.path.join(base_path, "CastServer.exe"),
        }

        server_order = ["AuthServer", "CastServer", "MainServer"]
        for name in server_order:
            if name in servers_to_start:
                self.server_manager.start_server(name, servers_to_start[name])

        self.update_server_status()
        
        server_names = sorted(self.server_manager.server_names)
        self.console_server_selector.configure(values=server_names)
        if server_names and not self.console_server_selection.get():
            self.console_server_selection.set(server_names[0])
            self.on_server_select(server_names[0])

    def stop_all_servers(self):
        self.server_manager.stop_all_servers()
        self.update_server_status()

    def update_server_status(self):
        if set(self.server_status_vars.keys()) != set(self.server_manager.server_names):
            for widget in self.server_status_frame.winfo_children():
                widget.destroy()
            self.server_status_vars.clear()
            
            for server_name in sorted(self.server_manager.server_names):
                frame = customtkinter.CTkFrame(self.server_status_frame, fg_color="transparent")
                frame.pack(side="left", padx=5)
                indicator = customtkinter.CTkLabel(frame, text="●", font=("Segoe UI", 16))
                indicator.pack(side="left")
                label = customtkinter.CTkLabel(frame, text=server_name)
                label.pack(side="left", padx=(0, 5))
                self.server_status_vars[server_name] = {'indicator': indicator, 'label': label}

        for server_name, widgets in self.server_status_vars.items():
            status = self.server_manager.get_status(server_name)
            color = "#57e893" if status == "Running" else "#ff6b6b"
            widgets['indicator'].configure(text_color=color)

    def update_all_consoles(self):
        """The main loop that orchestrates updates for all server consoles."""
        for server_name in self.server_manager.server_names:
            self.process_individual_server_output(server_name)

        current_statuses = {name: self.server_manager.get_status(name) for name in self.server_manager.server_names}
        if not hasattr(self, '_last_statuses') or self._last_statuses != current_statuses:
            self.update_server_status()
            self._last_statuses = current_statuses

        delay = 250 if self.server_manager.processes else 1000
        self.after(delay, self.update_all_consoles)

    def process_individual_server_output(self, server_name):
        """Drains the output queue for a single server and updates the display if it's the selected one."""
        q = self.server_manager.output_queues.get(server_name)
        if not q:
            return

        lines_to_add = []
        try:
            while not q.empty():
                lines_to_add.append(q.get_nowait())
        except queue.Empty:
            pass

        if not lines_to_add:
            return

        if server_name not in self.console_outputs:
            self.console_outputs[server_name] = deque(maxlen=self.max_console_lines)
        self.console_outputs[server_name].extend(lines_to_add)

        if self.console_server_selection.get() == server_name:
            self.append_text_to_console(lines_to_add)

    def append_text_to_console(self, lines):
        """Appends a list of lines to the console text widget."""
        self.console_text.configure(state='normal')
        for line in lines:
            tag = self._get_line_tag(line)
            self.console_text.insert(tk.END, line, tag)
        self.console_text.see(tk.END)
        self.console_text.configure(state='disabled')

    def _get_line_tag(self, line):
        line_upper = line.upper()
        if "ERROR" in line_upper or "FAIL" in line_upper: return "ERROR"
        if "WARN" in line_upper or "WARNING" in line_upper: return "WARN"
        if "SUCCESS" in line_upper or "OK" in line_upper: return "SUCCESS"
        if "INFO" in line_upper: return "INFO"
        if "DEBUG" in line_upper: return "DEBUG"
        return "DEFAULT"

    def on_server_select(self, selected_server):
        self.console_text.configure(state='normal')
        self.console_text.delete(1.0, tk.END)
        
        if selected_server in self.console_outputs:
            lines_to_insert = list(self.console_outputs[selected_server])
            
            for line in lines_to_insert:
                tag = self._get_line_tag(line)
                self.console_text.insert(tk.END, line, (tag,))
            
            self.console_text.see(tk.END)
        
        self.console_text.configure(state='disabled')

    def on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to quit? This will stop all running servers."):
            self.stop_all_servers()
            self.destroy()

    def open_database_editor(self):
        self.log("Database Editor functionality has been removed.")
        messagebox.showinfo("Feature Removed", "The standalone database editor has been removed to simplify the application.")

    def add_server_row(self):
        server_number = len(self.server_widgets) + 2
        
        row_frame = customtkinter.CTkFrame(self.server_list_frame, border_width=1)
        row_frame.pack(fill="x", expand=True, padx=10, pady=5)
        row_frame.grid_columnconfigure((1, 3), weight=1)

        customtkinter.CTkLabel(row_frame, text=f"Server {server_number}", font=self.header_font).grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=5)

        customtkinter.CTkLabel(row_frame, text="MainServer Local IP:").grid(row=1, column=0, sticky=tk.W, pady=2, padx=10)
        main_local_ip = tk.StringVar()
        customtkinter.CTkEntry(row_frame, textvariable=main_local_ip).grid(row=1, column=1, sticky="ew", pady=2, padx=5)

        customtkinter.CTkLabel(row_frame, text="MainServer Public IP:").grid(row=1, column=2, sticky=tk.W, pady=2, padx=10)
        main_public_ip = tk.StringVar()
        customtkinter.CTkEntry(row_frame, textvariable=main_public_ip).grid(row=1, column=3, sticky="ew", pady=2, padx=5)

        customtkinter.CTkLabel(row_frame, text="MainServer Port:").grid(row=2, column=0, sticky=tk.W, pady=2, padx=10)
        main_port = tk.StringVar()
        customtkinter.CTkEntry(row_frame, textvariable=main_port).grid(row=2, column=1, sticky="ew", pady=2, padx=5)

        customtkinter.CTkLabel(row_frame, text="MainServer IPC Port:").grid(row=2, column=2, sticky=tk.W, pady=2, padx=10)
        main_ipc_port = tk.StringVar()
        customtkinter.CTkEntry(row_frame, textvariable=main_ipc_port).grid(row=2, column=3, sticky="ew", pady=2, padx=5)

        customtkinter.CTkLabel(row_frame, text="CastServer Local IP:").grid(row=3, column=0, sticky=tk.W, pady=2, padx=10)
        cast_local_ip = tk.StringVar()
        customtkinter.CTkEntry(row_frame, textvariable=cast_local_ip).grid(row=3, column=1, sticky="ew", pady=2, padx=5)

        customtkinter.CTkLabel(row_frame, text="CastServer Public IP:").grid(row=3, column=2, sticky=tk.W, pady=2, padx=10)
        cast_public_ip = tk.StringVar()
        customtkinter.CTkEntry(row_frame, textvariable=cast_public_ip).grid(row=3, column=3, sticky="ew", pady=2, padx=5)

        customtkinter.CTkLabel(row_frame, text="CastServer Port:").grid(row=4, column=0, sticky=tk.W, pady=2, padx=10)
        cast_port = tk.StringVar()
        customtkinter.CTkEntry(row_frame, textvariable=cast_port).grid(row=4, column=1, sticky="ew", pady=2, padx=5)

        customtkinter.CTkLabel(row_frame, text="CastServer IPC Port:").grid(row=4, column=2, sticky=tk.W, pady=2, padx=10)
        cast_ipc_port = tk.StringVar()
        customtkinter.CTkEntry(row_frame, textvariable=cast_ipc_port).grid(row=4, column=3, sticky="ew", pady=2, padx=5)

        remove_button = customtkinter.CTkButton(row_frame, text="-", command=lambda: self.remove_server_row(row_frame), width=30, fg_color="#D32F2F", hover_color="#B71C1C")
        remove_button.grid(row=0, column=4, padx=10)

        widgets = {
            "frame": row_frame,
            "main_local_ip": main_local_ip, "main_public_ip": main_public_ip,
            "main_port": main_port, "main_ipc_port": main_ipc_port,
            "cast_local_ip": cast_local_ip, "cast_public_ip": cast_public_ip,
            "cast_port": cast_port, "cast_ipc_port": cast_ipc_port
        }
        self.server_widgets.append(widgets)

    def remove_server_row(self, row_frame):
        for i, widgets in enumerate(self.server_widgets):
            if widgets["frame"] == row_frame:
                self.server_widgets.pop(i)
                break
        row_frame.destroy()
        
        for i, widgets in enumerate(self.server_widgets):
            label = widgets["frame"].winfo_children()[0]
            label.configure(text=f"Server {i + 2}")

    def auto_detect_ip(self):
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            self.local_ip.set(ip)
            self.log(f"Auto-detected local IP: {ip}")
        except Exception as e:
            self.log(f"Failed to auto-detect IP: {str(e)}. Falling back to 127.0.0.1")
            self.local_ip.set("127.0.0.1")

    def toggle_mariadb_fields(self):
        if self.existing_mariadb.get():
            self.existing_db_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=10, padx=5)
            self.db_install_frame.grid_remove()
        else:
            self.existing_db_frame.grid_remove()
            self.db_install_frame.grid()
    
    def is_valid_ip(self, ip):
        try:
            parts = ip.split('.')
            if len(parts) != 4:
                return False
            
            for part in parts:
                num = int(part)
                if num < 0 or num > 255:
                    return False
            
            return True
        except (ValueError, AttributeError):
            return False
    
    def is_private_ip(self, ip):
        try:
            parts = ip.split('.')
            if len(parts) != 4:
                return False
            
            octets = [int(part) for part in parts]
            
            if octets[0] == 10:
                return True
            
            if octets[0] == 172 and 16 <= octets[1] <= 31:
                return True
            
            if octets[0] == 192 and octets[1] == 168:
                return True
            
            return False
        except (ValueError, IndexError):
            return False
            
    def generate_random_password(self):
        alphabet = string.ascii_letters + string.digits
        password = ''.join(secrets.choice(alphabet) for _ in range(16))
        self.db_password.set(password)
        return password
            
    def log(self, message):
        if hasattr(self, 'log_text') and self.log_text.winfo_exists():
            self.log_text.insert(tk.END, f"{message}\n")
            self.log_text.see(tk.END)
        
    def clear_log(self):
        if hasattr(self, 'log_text') and self.log_text.winfo_exists():
            self.log_text.delete(1.0, tk.END)
        
    def start_setup(self):
        if not self.project_path.get():
            messagebox.showerror("Error", "Please select an installation directory")
            return

        self.save_settings()
            
        self.setup_running = True
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.progress_bar.start()
        
        self.run_setup_sequentially()
        
    def stop_setup(self):
        self.setup_running = False
        if self.worker_process and self.worker_process.is_alive():
            self.worker_process.terminate()
        self.finalize_setup_ui()
        self.log("Setup stopped by user")
        
    def process_gui_queue(self):
        try:
            while True:
                message = self.gui_queue.get_nowait()
                if message['type'] == 'log':
                    self.log(message['message'])
                elif message['type'] == 'ask':
                    response_queue = message['response_queue']
                    answer = messagebox.askyesno(message['title'], message['prompt'])
                    response_queue.put(answer)
                elif message['type'] == 'showerror':
                    messagebox.showerror(message['title'], message['message'])
                elif message['type'] == 'showinfo':
                    messagebox.showinfo(message['title'], message['message'])
                elif message['type'] == 'result':
                    self.handle_step_result(message['success'])
        except queue.Empty:
            pass
        self.after(100, self.process_gui_queue)

    def get_current_config(self):
        return {
            "project_path": self.project_path.get(),
            "local_ip": self.local_ip.get(),
            "db_ip": self.db_ip.get(),
            "db_port": self.db_port.get(),
            "db_username": self.db_username.get(),
            "db_password": self.db_password.get(),
            "db_name": self.db_name.get(),
            "existing_mariadb": self.existing_mariadb.get(),
            "db_root_password": self.db_root_password.get(),
            "mariadb_path": self.mariadb_path.get(),
            "servers": [
                {
                    "main_local_ip": w["main_local_ip"].get(),
                    "main_public_ip": w["main_public_ip"].get(),
                    "main_port": w["main_port"].get(),
                    "main_ipc_port": w["main_ipc_port"].get(),
                    "cast_local_ip": w["cast_local_ip"].get(),
                    "cast_public_ip": w["cast_public_ip"].get(),
                    "cast_port": w["cast_port"].get(),
                    "cast_ipc_port": w["cast_ipc_port"].get(),
                } for w in self.server_widgets
            ]
        }

    def run_setup_sequentially(self):
        self.load_setup_state()
        self.setup_steps = [
            ("prerequisites", self.check_prerequisites, False),
            ("install_type", self.ask_for_install_type, False),
            ("install_llvm", worker_install_llvm, True),
            ("download_repo", worker_download_repository, True),
            ("extract_cleanup", self.extract_and_cleanup, False),
            ("setup_vcpkg", worker_setup_vcpkg, True),
            ("configure_project", self.configure_project, False),
            ("configure_vs_projects", self.worker_configure_vs_projects, False),
            ("install_mariadb", worker_install_mariadb, True),
            ("setup_config", self.setup_config, False),
            ("setup_database", worker_setup_database, True)
        ]
        self.current_step = 0
        self.run_next_step()

    def run_next_step(self):
        if not self.setup_running:
            self.log("Setup stopped by user.")
            self.finalize_setup_ui()
            return

        while self.current_step < len(self.setup_steps):
            step_name, _, _ = self.setup_steps[self.current_step]
            if not self.setup_state.get(step_name, False):
                break
            self.log(f"--- Skipping already completed step: {step_name} ---")
            self.current_step += 1
        
        if self.current_step >= len(self.setup_steps):
            self.log("Setup completed successfully!")
            self.log("Next steps:")
            self.log("1. Open the Visual Studio solution (.sln) file")
            self.log("2. Build projects in order: Common, then MainServer/AuthServer/CastServer")
            self.log("3. Configure your database connection")
            self.log("4. Start the servers!")
            messagebox.showinfo("Success", "MicroVolts Server setup completed successfully!")
            self.finalize_setup_ui()
            return

        step_name, step_func, is_process = self.setup_steps[self.current_step]
        self.log(f"--- Running step: {step_name} ---")

        if is_process:
            config = self.get_current_config()
            self.worker_process = Process(target=step_func, args=(self.gui_queue, config))
            self.worker_process.start()
            self.check_step_completion()
        else:
            step_success = step_func()
            self.handle_step_result(step_success)

    def handle_step_result(self, success):
        step_name, _, _ = self.setup_steps[self.current_step]
        if success:
            self.log(f"Step {step_name} completed successfully.")
            self.setup_state[step_name] = True
            self.save_setup_state()
            self.current_step += 1
            self.run_next_step()
        else:
            self.log(f"Step {step_name} failed. Aborting.")
            messagebox.showerror("Setup Failed", f"The setup failed at step: {step_name}.\nCheck the log for details.")
            self.finalize_setup_ui()

    def check_step_completion(self):
        if self.worker_process and self.worker_process.is_alive():
            self.after(100, self.check_step_completion)
            return
        
        if self.worker_process and self.worker_process.exitcode != 0:
             self.handle_step_result(False)

    def finalize_setup_ui(self):
        self.setup_running = False
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.progress_bar.stop()
        self.log("To start fresh, click 'Clear Cache & Restart'.")

    def load_setup_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    self.setup_state = json.load(f)
                self.log("Loaded previous setup state. Will attempt to resume.")
            except Exception as e:
                self.log(f"Could not load state file, starting fresh: {e}")
                self.setup_state = {}
        else:
            self.setup_state = {}

    def save_setup_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.setup_state, f, indent=4)
        except Exception as e:
            self.log(f"Warning: Could not save setup state: {e}")

    def clear_cache_and_restart(self):
        if messagebox.askyesno("Confirm", "This will delete the setup state and configuration file. Are you sure you want to start over?"):
            if os.path.exists(self.state_file):
                os.remove(self.state_file)
                self.log("Setup state file deleted.")
            if os.path.exists(self.config_file):
                os.remove(self.config_file)
                self.log("Configuration file deleted.")
            
            self.setup_state = {}
            self.project_path.set("")
            self.local_ip.set("")
            self.generate_random_password()
            self.log("Cache cleared. Restarting setup tool.")
            
            python = sys.executable
            os.execl(python, python, *sys.argv)

    def ask_for_install_type(self):
        if not os.path.exists(self.config_file):
            answer = messagebox.askquestion("Installation Type", "This looks like a first-time setup.\n\nWould you like to download and compile the source code (Yes) or download pre-compiled executables (No)?", icon='question')
            if answer == 'yes':
                self.log("User chose to install from source.")
            else:
                self.log("User chose to use pre-compiled executables.")
                messagebox.showinfo("Not Implemented", "Downloading pre-compiled executables is not yet implemented. The setup will proceed with source installation.")
        return True

    def check_prerequisites(self):
        self.log("Checking prerequisites...")
        
        try:
            result = subprocess.run(['git', '--version'], capture_output=True, text=True)
            if result.returncode == 0:
                self.log(f"Git is installed: {result.stdout.strip()}")
            else:
                raise FileNotFoundError
        except FileNotFoundError:
            self.log("Git not found.")
            if messagebox.askyesno("Prerequisite Missing", "Git is not installed or not in your PATH. Would you like to download and install it?"):
                self.install_git()
                return False
            else:
                self.log("User chose not to install Git. Setup may fail.")
                return False

        if not self.is_vs_installed():
            self.log("Visual Studio with C++ workload not found.")
            messagebox.showerror("Prerequisite Missing", "Visual Studio with the 'Desktop development with C++' workload is required. Please install it from the Visual Studio Installer.")
            return False
        else:
            self.log("Visual Studio with C++ workload found.")
            
        return True

    def is_vs_installed(self):
        try:
            vswhere_path = None
            possible_paths = [
                "C:\\Program Files (x86)\\Microsoft Visual Studio\\Installer\\vswhere.exe",
                "C:\\Program Files\\Microsoft Visual Studio\\Installer\\vswhere.exe"
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    vswhere_path = path
                    break
            if not vswhere_path: return False
            
            cmd_find_path = [vswhere_path, "-latest", "-property", "installationPath"]
            path_result = subprocess.run(cmd_find_path, capture_output=True, text=True, shell=False)
            if path_result.returncode != 0 or not path_result.stdout.strip(): return False
            
            vs_install_path = path_result.stdout.strip()
            vcvarsall_path = os.path.join(vs_install_path, "VC", "Auxiliary", "Build", "vcvarsall.bat")
            return os.path.exists(vcvarsall_path)
        except Exception as e:
            self.log(f"Error checking for Visual Studio: {e}")
            return False

    def install_git(self):
        self.log("Downloading Git...")
        git_installer_url = "https://github.com/git-for-windows/git/releases/download/v2.45.2.windows.1/Git-2.45.2-64-bit.exe"
        installer_path = os.path.join(self.project_path.get(), "Git-Installer.exe")
        try:
            response = requests.get(git_installer_url, stream=True)
            response.raise_for_status()
            with open(installer_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            self.log("Git downloaded. Starting installation...")
            subprocess.run([installer_path], shell=True, check=False)
            
            self.log("Git installation finished. Please restart the setup tool.")
            messagebox.showinfo("Restart Required", "Git has been installed. Please restart the setup tool.")
            self.quit()
        except Exception as e:
            self.log(f"Failed to download or install Git: {e}")
            messagebox.showerror("Error", f"Failed to install Git: {e}")

    def startup_update_check(self):
        if self.project_path.get() and os.path.exists(os.path.join(self.project_path.get(), "MicrovoltsEmulator", ".git")):
            update_thread = threading.Thread(target=self.check_for_updates, args=(True,))
            update_thread.daemon = True
            update_thread.start()

    def check_for_updates(self, startup=False):
        repo_path = os.path.join(self.project_path.get(), "MicrovoltsEmulator")
        if not os.path.exists(os.path.join(repo_path, ".git")):
            if not startup:
                messagebox.showerror("Error", "This is not a Git repository. Cannot check for updates.")
            return

        self.log("Checking for updates...")
        try:
            subprocess.run(["git", "fetch"], cwd=repo_path, check=True, capture_output=True, text=True)
            status_result = subprocess.run(["git", "status", "-uno"], cwd=repo_path, check=True, capture_output=True, text=True)
            
            updated = False
            if "Your branch is behind" in status_result.stdout:
                if messagebox.askyesno("Update Available", "A new version of the emulator is available. Would you like to update now?"):
                    self.log("New update found. Pulling changes...")
                    subprocess.run(["git", "pull"], cwd=repo_path, check=True, capture_output=True, text=True)
                    self.log("Update complete.")
                    updated = True
            else:
                self.log("You have the most updated version of the Emulator available.")
                if not startup:
                    messagebox.showinfo("Up to Date", "You have the most updated version of the Emulator available.")

            if not startup or updated:
                if messagebox.askyesno("Recompile Project", "Would you like to recompile the project now?"):
                    self.run_recompile_in_thread()

        except subprocess.CalledProcessError as e:
            self.log(f"Error checking for updates: {e.stderr}")
            if not startup:
                messagebox.showerror("Error", f"An error occurred while checking for updates:\n{e.stderr}")

    def run_recompile_in_thread(self):
        self.start_button.configure(state=tk.DISABLED)
        self.update_button.configure(state=tk.DISABLED)
        self.progress_bar.start()
        
        recompile_thread = threading.Thread(target=self.run_recompile)
        recompile_thread.daemon = True
        recompile_thread.start()

    def schedule_gui_task(self, func, *args):
        self.after(0, lambda: func(*args))

    def run_recompile(self):
        if self.recompile_project():
            self.schedule_gui_task(messagebox.showinfo, "Success", "Project recompiled successfully.")
        
        self.schedule_gui_task(self.finalize_recompile_ui)

    def finalize_recompile_ui(self):
        self.start_button.configure(state=tk.NORMAL)
        self.update_button.configure(state=tk.NORMAL)
        self.progress_bar.stop()

    def find_vcvarsall(self):
        self.log("Finding vcvarsall.bat...")
        try:
            vswhere_path = None
            possible_paths = [
                os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft Visual Studio", "Installer", "vswhere.exe"),
                os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft Visual Studio", "Installer", "vswhere.exe")
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    vswhere_path = path
                    break
            
            if not vswhere_path:
                self.log("vswhere.exe not found.")
                return None

            cmd = [vswhere_path, "-latest", "-property", "installationPath"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            vs_path = result.stdout.strip()
            
            if not vs_path:
                self.log("Visual Studio installation path not found.")
                return None

            vcvarsall_path = os.path.join(vs_path, "VC", "Auxiliary", "Build", "vcvarsall.bat")
            if os.path.exists(vcvarsall_path):
                self.log(f"Found vcvarsall.bat at: {vcvarsall_path}")
                return vcvarsall_path
            else:
                self.log("vcvarsall.bat not found in the latest VS installation.")
                return None
        except Exception as e:
            self.log(f"Error finding vcvarsall.bat: {e}")
            return None

    def find_msbuild(self):
        self.log("Finding MSBuild.exe...")
        try:
            vswhere_path = None
            possible_paths = [
                os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft Visual Studio", "Installer", "vswhere.exe"),
                os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft Visual Studio", "Installer", "vswhere.exe")
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    vswhere_path = path
                    break
            
            if not vswhere_path:
                self.log("vswhere.exe not found.")
                return None

            cmd = [vswhere_path, "-latest", "-requires", "Microsoft.Component.MSBuild", "-find", "MSBuild\\**\\Bin\\MSBuild.exe"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            msbuild_path = result.stdout.strip()

            if msbuild_path and os.path.exists(msbuild_path):
                self.log(f"Found MSBuild.exe at: {msbuild_path}")
                return msbuild_path
            else:
                self.log("MSBuild.exe not found via vswhere.")
                return None
        except Exception as e:
            self.log(f"Error finding MSBuild.exe: {e}")
            return None
            
    def recompile_project(self):
        self.log("Attempting to recompile project...")
        
        msbuild_path = self.find_msbuild()
        if not msbuild_path:
            self.log("Could not find MSBuild.exe. Cannot recompile.")
            self.schedule_gui_task(messagebox.showerror, "Error", "Could not find MSBuild.exe. Please ensure Visual Studio is installed correctly.")
            return False

        vcvarsall_path = self.find_vcvarsall()
        if not vcvarsall_path:
            self.log("Could not find vcvarsall.bat. Cannot recompile.")
            self.schedule_gui_task(messagebox.showerror, "Error", "Could not find vcvarsall.bat. Please ensure Visual Studio C++ tools are installed.")
            return False

        repo_path = os.path.join(self.project_path.get(), "MicrovoltsEmulator")
        sln_file = os.path.join(repo_path, "Microvolts-Emulator-V2.sln")
        if not os.path.exists(sln_file):
            self.log(f"Solution file not found at {sln_file}")
            self.schedule_gui_task(messagebox.showerror, "Error", f"Solution file (.sln) not found.")
            return False

        try:
            self.log("Starting recompile process...")
            
            compile_cmd = (
                f'call "{vcvarsall_path}" x64 && '
                f'"{msbuild_path}" "{sln_file}" /t:Rebuild /p:Configuration=Release /p:Platform=x64'
            )

            self.log(f"Executing command: {compile_cmd}")

            process = subprocess.Popen(
                compile_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=True,
                cwd=repo_path,
                creationflags=subprocess.CREATE_NO_WINDOW,
                encoding='utf-8',
                errors='replace'
            )

            for line in iter(process.stdout.readline, ''):
                self.log(line.strip())

            process.stdout.close()
            return_code = process.wait()

            if return_code == 0:
                self.log("Recompile successful.")
                return True
            else:
                self.log(f"Recompile failed with exit code: {return_code}")
                self.schedule_gui_task(messagebox.showerror, "Recompile Failed", f"Recompilation failed with exit code {return_code}. Check the log for details.")
                return False

        except Exception as e:
            self.log(f"An error occurred during recompilation: {e}")
            self.schedule_gui_task(messagebox.showerror, "Recompile Error", f"An unexpected error occurred during recompilation:\n{e}")
            return False

    def find_mariadb_executable(self):
        self.log("Searching for MariaDB executable...")
        for version in ["11.5", "11.4", "11.3", "11.2", "11.1", "11.0", "10.11", "10.6", "10.5"]:
            path = f"C:\\Program Files\\MariaDB {version}\\bin\\mariadb.exe"
            if os.path.exists(path):
                self.log(f"Found MariaDB executable at: {path}")
                return path
        
        try:
            result = subprocess.run(['where', 'mariadb'], capture_output=True, text=True, shell=True)
            if result.returncode == 0:
                path = result.stdout.strip().split('\n')[0]
                self.log(f"Found MariaDB executable in PATH: {path}")
                return path
        except Exception:
            pass

        self.log("MariaDB executable not found.")
        messagebox.showerror("Error", "Could not find mariadb.exe.")
        return None
            
    def extract_and_cleanup(self):
        self.log("Verifying repository structure...")
        try:
            repo_path = os.path.join(self.project_path.get(), "MicrovoltsEmulator")
            if not os.path.exists(repo_path):
                raise Exception("Repository directory not found")
            sln_file = os.path.join(repo_path, "Microvolts-Emulator-V2.sln")
            if not os.path.exists(sln_file):
                raise Exception("Visual Studio solution file not found")
            return True
        except Exception as e:
            self.log(f"Failed to verify repository: {str(e)}")
            return False
            
    def configure_project(self):
        self.log("Project configuration completed")
        return True
        
    def worker_configure_vs_projects(self):
        self.log("Configuring Visual Studio projects...")
        # Placeholder for the logic to modify .vcxproj files.
        self.log("Visual Studio project configuration step is a placeholder.")
        return True
        
    def setup_config(self):
        self.log("Setting up configuration files...")
        try:
            repo_path = os.path.join(self.project_path.get(), "MicrovoltsEmulator")
            setup_dir = os.path.join(repo_path, "Setup")
            os.makedirs(setup_dir, exist_ok=True)
            
            config_path = os.path.join(setup_dir, "config.ini")
            
            config = configparser.ConfigParser()
            config.optionxform = str
            
            local_ip = self.local_ip.get() if self.local_ip.get() else "127.0.0.1"

            config['Database'] = {
                'Ip': self.db_ip.get(),
                'Port': self.db_port.get(),
                'DatabaseName': self.db_name.get(),
                'Username': self.db_username.get(),
                'PasswordEnvironmentName': 'MICROVOLTS_DB_PASSWORD'
            }
            
            with open(config_path, 'w') as configfile:
                config.write(configfile)
                
            self.log(f"Configuration file created: {config_path}")
            
            db_password = self.db_password.get()
            os.environ['MICROVOLTS_DB_PASSWORD'] = db_password
            self.log("Database password set as environment variable for this session.")
            
            return True
        except Exception as e:
            self.log(f"Failed to setup configuration: {str(e)}")
            return False

    def open_command_editor(self):
        if not self.project_path.get() or not os.path.isdir(self.project_path.get()):
            messagebox.showerror("Error", "Please select a valid installation directory first.")
            return

        if self.command_editor_window is None or not self.command_editor_window.winfo_exists():
            try:
                self.command_editor_window = CommandEditorWindow(self, self.project_path.get())
            except Exception as e:
                self.log(f"Error creating Command Editor window: {e}")
                messagebox.showerror("Error", f"Could not create Command Editor window:\n{e}")
                return
        else:
            self.command_editor_window.focus()

        self.command_editor_window.load_commands()
        self.command_editor_window.deiconify()
        self.command_editor_window.grab_set()

class CommandEditorWindow(customtkinter.CTkToplevel):
    def __init__(self, parent, project_path):
        super().__init__(parent)
        self.title("Command Permission Editor")
        self.geometry("900x600")
        self.transient(parent)

        self.project_path = project_path
        self.commands = {}
        self.command_files_path = os.path.join(self.project_path, 'MicrovoltsEmulator', 'MainServer', 'include', 'ChatCommands', 'Commands')
        self.player_enums_path = os.path.join(self.project_path, 'MicrovoltsEmulator', 'Common', 'include', 'Enums', 'PlayerEnums.h')

        self.grades = self.load_grades()
        
        self.style = ttk.Style(self)
        self.style.theme_use("default")
        self.style.configure("Treeview", background="#2a2d2e", foreground="white", fieldbackground="#2a2d2e", borderwidth=0, rowheight=25)
        self.style.map("Treeview", background=[('selected', '#24527a')])
        self.style.configure("Treeview.Heading", background="#565b5e", foreground="white", relief="flat", font=('Calibri', 10, 'bold'))
        self.style.map("Treeview.Heading", background=[('active', '#3484F0')])

        self.main_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)

        self.create_widgets()
        self.load_commands()

        button_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        button_frame.pack(fill="x", pady=10, padx=10)
        
        instructions = "Double-click a permission to change it. Your changes are temporary until you click 'Save Changes'."
        customtkinter.CTkLabel(button_frame, text=instructions, text_color="gray60").pack(side="left", expand=True, fill="x")
        
        save_button = customtkinter.CTkButton(button_frame, text="Save Changes", command=self.save_changes)
        save_button.pack(side="right")

    def load_grades(self):
        try:
            with open(self.player_enums_path, 'r') as f:
                content = f.read()
            
            enum_content_match = re.search(r'enum\s+PlayerGrade\s*{([^}]+)}', content)
            if not enum_content_match:
                raise ValueError("PlayerGrade enum not found")

            enum_content = enum_content_match.group(1)
            grade_regex = re.compile(r'(\w+)\s*=\s*\d+')
            grades = grade_regex.findall(enum_content)
            
            if not grades:
                raise ValueError("No grades found in PlayerGrade enum")

            return grades
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load player grades from PlayerEnums.h:\n{e}")
            self.destroy()
            return []

    def load_commands(self):
        description_regex = re.compile(r'ICommand\s*{\s*[^,]+,\s*"([^"]+)"')
        permission_regex = re.compile(r"REGISTER_CMD\(\s*(\w+)\s*,\s*Common::Enums::PlayerGrade::(\w+)\)")

        if not os.path.isdir(self.command_files_path):
            messagebox.showerror("Error", f"Commands directory not found at:\n{self.command_files_path}")
            self.destroy()
            return

        for filepath in glob.glob(os.path.join(self.command_files_path, "*.h")):
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                
                matches = permission_regex.finditer(content)
                for match in matches:
                    command_name = match.group(1)
                    permission = match.group(2)
                    
                    class_def_search_area = content[:match.start()]
                    
                    class_regex = re.compile(r"(?:class|struct)\s+" + re.escape(command_name) + r"\s*(?:final)?\s*:\s*public")
                    class_match = class_regex.search(class_def_search_area)
                    
                    if class_match:
                        constructor_area = class_def_search_area[class_match.start():]
                        desc_match = description_regex.search(constructor_area)
                        if desc_match:
                            description = desc_match.group(1)
                            self.commands[command_name] = {
                                "file": filepath,
                                "permission": permission,
                                "description": description,
                                "original_permission": permission
                            }
        
        self.populate_tree()

    def create_widgets(self):
        tree_frame = customtkinter.CTkFrame(self.main_frame, fg_color="transparent")
        tree_frame.grid(row=0, column=0, sticky="nsew")
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(tree_frame, columns=("Command", "Description", "Permission"), show="headings")
        self.tree.heading("Command", text="Command")
        self.tree.heading("Description", text="Description / Usage")
        self.tree.heading("Permission", text="Permission")

        self.tree.column("Command", width=150, stretch=False, anchor="w")
        self.tree.column("Description", width=450, anchor="w")
        self.tree.column("Permission", width=200, stretch=False, anchor="center")

        self.tree.tag_configure('oddrow', background='#343638')
        self.tree.tag_configure('evenrow', background='#2a2d2e')

        scrollbar = customtkinter.CTkScrollbar(tree_frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.tree.bind("<Double-1>", self.on_double_click)

    def populate_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, (name, data) in enumerate(sorted(self.commands.items())):
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            self.tree.insert("", "end", values=(name, data['description'], data['permission']), tags=(tag,), iid=name)

    def on_double_click(self, event):
        if hasattr(self, '_editor') and self._editor.winfo_exists():
            self._editor.destroy()

        rowid = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        
        if not rowid or self.tree.heading(column_id, "text") != "Permission":
            return

        x, y, width, height = self.tree.bbox(rowid, column_id)

        current_value = self.tree.set(rowid, "Permission")
        
        self._editor = customtkinter.CTkComboBox(self.tree, values=self.grades)
        self._editor.set(current_value)
        self._editor.place(x=x, y=y, width=width, height=height)
        
        self._editor.focus_force()

        def on_combo_select(event):
            new_permission = self._editor.get()
            self.tree.set(rowid, "Permission", new_permission)
            command_name = self.tree.item(rowid, "values")[0]
            self.commands[command_name]['permission'] = new_permission
            self._editor.destroy()

        def on_focus_out(event):
            if hasattr(self, '_editor') and self._editor.winfo_exists():
                self._editor.destroy()

        self._editor.bind("<<ComboboxSelected>>", on_combo_select)
        self._editor.bind("<FocusOut>", on_focus_out)
        self._editor.bind("<Escape>", lambda e: self._editor.destroy())

    def save_changes(self):
        changed_files = set()
        for name, data in self.commands.items():
            if data['permission'] != data['original_permission']:
                filepath = data['file']
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()

                    old_line = f"REGISTER_CMD({name}, Common::Enums::PlayerGrade::{data['original_permission']})"
                    new_line = f"REGISTER_CMD({name}, Common::Enums::PlayerGrade::{data['permission']})"
                    
                    if old_line in content:
                        content = content.replace(old_line, new_line, 1)
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(content)
                        
                        data['original_permission'] = data['permission']
                        changed_files.add(os.path.basename(filepath))
                    else:
                        messagebox.showwarning("Warning", f"Could not find the line to update for command '{name}' in {os.path.basename(filepath)}. It might have been modified externally or the file has changed.")

                except Exception as e:
                    messagebox.showerror("Error", f"Failed to save changes for {name} in {os.path.basename(filepath)}.\n\nError: {e}")


        if changed_files:
            messagebox.showinfo("Success", f"Changes saved successfully to:\n\n" + "\n".join(sorted(list(changed_files))))
        else:
            messagebox.showinfo("No Changes", "No permissions were changed.")
        
        self.withdraw()

class ServerProcessManager:
    def __init__(self, log_callback):
        self.log = log_callback
        self.processes = {}
        self.output_queues = {}
        self.server_names = []
        self.reader_threads = {}

    def _reader_thread(self, stream, q):
        try:
            for line in iter(stream.readline, b''):
                q.put(line.decode('utf-8', errors='replace'))
        finally:
            stream.close()

    def start_server(self, server_name, exe_path):
        if server_name in self.processes and self.processes[server_name].poll() is None:
            self.log(f"{server_name} is already running.")
            return True

        if not os.path.exists(exe_path):
            self.log(f"Error: Executable not found at {exe_path}")
            messagebox.showerror("Server Error", f"Executable not found for {server_name} at:\n{exe_path}")
            return False

        try:
            self.log(f"Starting {server_name} from {exe_path}...")
            
            process = subprocess.Popen(
                [exe_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.path.dirname(exe_path),
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.processes[server_name] = process

            if server_name not in self.server_names:
                self.server_names.append(server_name)

            q = queue.Queue()
            self.output_queues[server_name] = q

            stdout_thread = threading.Thread(target=self._reader_thread, args=(process.stdout, q))
            stderr_thread = threading.Thread(target=self._reader_thread, args=(process.stderr, q))
            stdout_thread.daemon = True
            stderr_thread.daemon = True
            stdout_thread.start()
            stderr_thread.start()
            self.reader_threads[server_name] = (stdout_thread, stderr_thread)

            self.log(f"{server_name} started successfully (PID: {process.pid}).")
            return True
        except Exception as e:
            self.log(f"Failed to start {server_name}: {e}")
            messagebox.showerror("Server Error", f"Failed to start {server_name}:\n{e}")
            return False

    def stop_server(self, server_name):
        if server_name in self.processes:
            process = self.processes[server_name]
            if process.poll() is None:
                self.log(f"Stopping {server_name} (PID: {process.pid})...")
                try:
                    # Using taskkill is more forceful and ensures child processes are also terminated.
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.log(f"{server_name} stopped successfully.")
                except (subprocess.CalledProcessError, FileNotFoundError) as e:
                    self.log(f"Failed to stop {server_name} via taskkill, falling back to terminate: {e}")
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.log(f"{server_name} did not terminate gracefully, killing.")
                        process.kill()

            del self.processes[server_name]
            if server_name in self.output_queues:
                del self.output_queues[server_name]
            if server_name in self.reader_threads:
                del self.reader_threads[server_name]
        
    def stop_all_servers(self):
        self.log("Stopping all running servers...")
        for server_name in list(self.processes.keys()):
            self.stop_server(server_name)
        self.log("All servers stopped.")

    def get_status(self, server_name):
        if server_name in self.processes and self.processes[server_name].poll() is None:
            return "Running"
        return "Stopped"

def main():
    app = MicroVoltsServerSetup()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()

if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    main()
