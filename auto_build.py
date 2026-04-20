import os
import subprocess
import sys
import urllib.request
import zipfile
import shutil
from pathlib import Path

def print_step(msg):
    print(f"\n[{'*'*10}] {msg} [{'='*10}]")

def run_cmd(cmd, cwd=None, env=None):
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, env=env, check=True)

def download_progress(block_num, block_size, total_size):
    downloaded = block_num * block_size
    percent = downloaded * 100 / total_size if total_size > 0 else 0
    sys.stdout.write(f"\rDownloading FFmpeg: {downloaded/1024/1024:.2f} MB / {total_size/1024/1024:.2f} MB ({percent:.1f}%)")
    sys.stdout.flush()

def main():
    repo_root = Path(__file__).resolve().parent

    # 1. Create venv
    venv_dir = repo_root / '.venv'
    
    # Check if venv is valid for Windows (needs Scripts folder)
    if venv_dir.exists() and not (venv_dir / 'Scripts').exists():
        print_step("Found invalid or non-Windows .venv directory, removing it...")
        shutil.rmtree(venv_dir, ignore_errors=True)

    if not venv_dir.exists():
        print_step("Creating virtual environment (.venv)")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    else:
        print_step("Virtual environment (.venv) already exists")

    python_exe = venv_dir / 'Scripts' / 'python.exe'
    pip_exe = venv_dir / 'Scripts' / 'pip.exe'

    # 2. Install nodeenv and Node.js/npm into venv
    print_step("Installing nodeenv and Node.js/npm into venv")
    run_cmd([str(pip_exe), "install", "nodeenv"])
    nodeenv_exe = venv_dir / 'Scripts' / 'nodeenv.exe'
    run_cmd([str(nodeenv_exe), "-p"])
    
    # On Windows, nodeenv puts 'npm.cmd' in the Scripts folder
    npm_cmd = venv_dir / 'Scripts' / 'npm.cmd'

    # 3. Download and extract FFmpeg/FFprobe
    vendor_bin_dir = repo_root / "vendor" / "windows" / "bin"
    vendor_bin_dir.mkdir(parents=True, exist_ok=True)
    
    ffmpeg_exe = vendor_bin_dir / "ffmpeg.exe"
    ffprobe_exe = vendor_bin_dir / "ffprobe.exe"
    
    if not ffmpeg_exe.exists() or not ffprobe_exe.exists():
        print_step("Downloading FFmpeg (might take a few minutes)...")
        # URL for latest Windows static build
        ffmpeg_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        zip_path = repo_root / "ffmpeg_temp.zip"
        
        try:
            urllib.request.urlretrieve(ffmpeg_url, zip_path, download_progress)
            print("\nExtracting FFmpeg binaries...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    filename = os.path.basename(member)
                    if filename == 'ffmpeg.exe':
                        source = zip_ref.open(member)
                        target = open(ffmpeg_exe, "wb")
                        with source, target:
                            shutil.copyfileobj(source, target)
                    elif filename == 'ffprobe.exe':
                        source = zip_ref.open(member)
                        target = open(ffprobe_exe, "wb")
                        with source, target:
                            shutil.copyfileobj(source, target)
            print("FFmpeg and FFprobe extracted successfully.")
        finally:
            if zip_path.exists():
                os.remove(zip_path)
    else:
        print_step("FFmpeg and FFprobe already exist in vendor/windows/bin")

    # 4. Install Python requirements for app and build tools
    print_step("Installing Python requirements and PyInstaller")
    run_cmd([str(pip_exe), "install", "-r", str(repo_root / "requirements.txt")])
    run_cmd([str(pip_exe), "install", "pyinstaller"])

    # 5. Build Web frontend
    web_dir = repo_root / "web"
    env = os.environ.copy()
    # Add venv/Scripts to path so tools find node and npm
    env["PATH"] = str(venv_dir / 'Scripts') + os.pathsep + env.get("PATH", "")

    if (web_dir / "package.json").exists():
        print_step("Building Web frontend via npm")
        if npm_cmd.exists():
            run_cmd([str(npm_cmd), "install"], cwd=str(web_dir), env=env)
            run_cmd([str(npm_cmd), "run", "build"], cwd=str(web_dir), env=env)
        else:
            print("Warning: Could not find npm.cmd inside venv. Trying system global npm...")
            sh_npm = shutil.which("npm")
            if sh_npm:
                run_cmd([sh_npm, "install"], cwd=str(web_dir), env=env)
                run_cmd([sh_npm, "run", "build"], cwd=str(web_dir), env=env)
            else:
                print("Could not find global npm. Skipping web build.")

    # 6. Run PyInstaller
    print_step("Running PyInstaller to package the application...")
    build_dir = repo_root / "build"
    dist_dir = repo_root / "dist"
    
    if build_dir.exists():
        try:
            shutil.rmtree(build_dir, ignore_errors=True)
        except Exception:
            pass
            
    pyinstaller_exe = venv_dir / 'Scripts' / 'pyinstaller.exe'
    spec_file = repo_root / "packaging" / "windows" / "video_downloader.spec"
    
    run_cmd([str(pyinstaller_exe), str(spec_file), "--noconfirm", "--clean"], cwd=str(repo_root), env=env)
    
    print_step("SUCCESS! BUILD COMPLETE!")
    print(f"Output folder: {dist_dir / 'VideoDownloader'}")
    print("\nBạn có thể vào thư mục dist/VideoDownloader và chạy VideoDownloader.exe.")

if __name__ == "__main__":
    main()
