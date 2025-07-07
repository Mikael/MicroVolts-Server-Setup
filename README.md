# MicroVolts Server Setup

This tool provides a graphical user interface (GUI) to automate the setup of a MicroVolts game server emulator. It handles downloading the source code, installing dependencies, setting up the database, and creating the necessary configuration files.

## Features

- **Automated Setup:** Simplifies the server setup process with a user-friendly GUI.
- **Prerequisite Checks:** Automatically checks for required software like Git, Python, and Visual Studio.
- **Dependency Management:** Installs C++ dependencies using `vcpkg` and Python packages using `pip`.
- **Database Configuration:** Installs and configures a MariaDB server or connects to an existing one.
- **Configuration Generation:** Creates the `config.ini` file based on user input.
- **Update Functionality:** Can check for updates to the emulator source code and recompile the project.
- **Multi-Server Support:** Allows for the configuration of multiple game servers.

## Prerequisites

Before running the setup, ensure you have the following installed:

- **Python 3.7+:** The setup script is written in Python. If not installed, the script will prompt you to install it.
- **Git:** Required for cloning the server emulator repository. The setup can attempt to install this for you.
- **Visual Studio:** Visual Studio with the "Desktop development with C++" workload is required to compile the server source code.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Mikael/MicroVolts-Server-Setup.git
    cd MicroVolts-Server-Setup
    ```

2.  **Run the setup script:**
    Double-click on `run_setup.bat`. This will:
    - Request administrator privileges (required for installing software and modifying system settings).
    - Check for and install Python dependencies from `requirements.txt`.
    - Launch the MicroVolts Server Setup GUI.

## Usage

Once the GUI is open, follow these steps:

1.  **Installation Directory:**
    - Click "Browse" to select a directory where the server files will be installed.

2.  **Server Configuration:**
    - The tool will attempt to auto-detect your local IP address. You can manually change it if needed.

3.  **Database Configuration:**
    - **New Installation (Default):** The setup will install a new MariaDB instance. A secure password will be generated for you, or you can provide your own.
    - **Existing Installation:** If you already have MariaDB installed, check the "Use existing MariaDB installation" box and provide your root password.

4.  **Multi-Server (Optional):**
    - If you plan to run more than one game server, go to the "Multi-Server" tab and click "+ Add Server" to configure additional servers.

5.  **Start Setup:**
    - Click the "Start Setup" button to begin the automated process. The progress will be displayed in the log window.

The setup process will perform the following actions:
- Install LLVM (clang-cl) if not found.
- Clone the `MicrovoltsEmulator` repository.
- Set up `vcpkg` and install C++ dependencies.
- Install and configure MariaDB.
- Create the `config.ini` file.
- Set a system environment variable (`MICROVOLTS_DB_PASSWORD`) for the database password.

## Post-Setup

After the setup completes successfully:

1.  **Open the Solution:**
    - Navigate to the `MicrovoltsEmulator` directory inside your chosen installation path.
    - Open the `Microvolts-Emulator-V2.sln` file in Visual Studio.

2.  **Build the Project:**
    - In Visual Studio, set the build configuration to **Release** and the platform to **x64**.
    - Build the solution. The recommended build order is:
        1.  Common
        2.  AuthServer
        3.  MainServer
        4.  CastServer

3.  **Run the Servers:**
    - Once built, you can run the server executables from the build output directory.

## Configuration

- **`config.ini`:** This file is located in the `MicrovoltsEmulator/Setup` directory and contains all the IP, port, and database settings for the servers.
- **Environment Variable:** The database password is stored in a system environment variable named `MICROVOLTS_DB_PASSWORD` for security.
