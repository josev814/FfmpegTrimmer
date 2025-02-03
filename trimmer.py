import shutil
import json
import sys
import subprocess
import os
import glob
import ffmpeg
import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QFileDialog,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QComboBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
import requests
from py7zip import py7zip

# FFmpeg download URL (Windows version)
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z"
FFMPEG_DIR = "ffmpeg"
VLC_WINDOWS_URL = 'https://download.videolan.org/pub/videolan/vlc/last/win64/vlc-3.0.20-win64.exe'
VLC_PATH = r'C:\Program Files\VideoLAN\VLC'
# possibly switch to github builds
# https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n7.1-latest-win64-gpl-7.1.zip

class Install_Requirements():

    def __init__(self):
        if not self.is_vlc_installed():
            self.install_vlc()
        self.install_ffmpeg()

    def is_vlc_installed(self):
        if os.path.isfile(os.path.join(VLC_PATH, 'vlc.exe')):
            return True
        return False

    def download_vlc(self, installer_path):
        print('VLC is not installed. Downloading...')
        self.download_file(VLC_WINDOWS_URL, installer_path)

    def download_file(self, url, dest):
        response = requests.get(url, stream=True)
        with open(dest, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)

    def install_vlc(self):
        installer_path = 'vlc_installer.exe'
        if not os.path.isfile(installer_path):
            self.download_vlc(installer_path)
        print('Installing VLC')
        subprocess.run([installer_path, '/S'], shell=True)
        os.remove(installer_path)
        print('VLC install Complete')

    def extract_ffmpeg(self, build_file):
        # Extract the tar file
        py7 = py7zip.Py7zip()
        bin_url = py7.get_binary_url()
        # Download and set up the binary if it isn't already set up
        if not os.path.exists(py7.binary_path):
            py7.download_binary()
            py7.setup()
        dst=f'./'
        cmd = [py7.binary_path, 'x', build_file, f'-bb3', f'-o{dst}']

        # Run the subprocess and capture output
        try:
            result = subprocess.run(cmd, check=False, text=False, capture_output=False)
            print(f"Decompression completed successfully! Output:\n{result.stdout}")
        except subprocess.CalledProcessError as e:
            print(f"Error during decompression: {e.stderr}")
        os.remove(build_file)

    def download_ffmpeg(self, build_file):
        """Downloads FFmpeg if not found in the current directory."""
        if os.path.exists(FFMPEG_DIR) and os.path.isfile(os.path.join(FFMPEG_DIR, 'ffmpeg.exe')):
            return
        if os.path.isfile(build_file):
            # release already downloaded
            return
        print("Downloading FFmpeg...")
        self.download_file(FFMPEG_URL, build_file)

    def install_ffmpeg(self):
        build_file = 'ffmpeg-release-full.7z'
        self.download_ffmpeg(build_file)
        if os.path.isfile(build_file):
            extract_ffmpeg(build_file)
        else:
            raise FileNotFoundError(f'Failed to find {build_file}')

        exes = ['ffmpeg', 'ffplay', 'ffprobe']
        for ffmpeg_dir in glob.glob('ffmpeg-*-full_build'):
            for entry in os.scandir(os.path.join(ffmpeg_dir, 'bin')):
                if entry.name.endswith('exe') and entry.name.replace('.exe', '') in exes and not os.path.isfile(f'./{FFMPEG_DIR}/{entry.name}'):
                    os.rename(entry.path, f'./{FFMPEG_DIR}/{entry.name}')
                    continue
        for entry in os.scandir('./'):
            if entry.is_dir() and entry.name.endswith('full_build'):
                shutil.rmtree(entry.path)


class VideoCutterThread(QThread):
    """Runs FFmpeg in a separate thread to prevent UI freezing."""
    progress = pyqtSignal(int)  # Signal to update progress bar
    finished = pyqtSignal(str)  # Signal when extraction is done

    def __init__(self, file_path, start_time, end_time, output_path, audio_level):
        super().__init__()
        self.file_path = file_path
        self.start_time = start_time
        self.end_time = end_time
        self.output_path = output_path
        self.audio_level = audio_level

    def run(self):
        output_file = os.path.join(
            self.output_path,
            f"clip_{self.start_time.replace(':', '-')}"
            f"_{self.end_time.replace(':', '-')}.mp4"
        )

        command = [
            f"{FFMPEG_DIR}/ffmpeg.exe",
            "-i", self.file_path,
            "-ss", self.start_time,
            "-to", self.end_time,
            "-c:v", "copy",
            "-c:a", "aac",
        ]

        if self.audio_level in ["-1", "-3", "-5"]:
            command.extend(["-af", f"loudnorm=I={self.audio_level}"])

        command.append(output_file)

        process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)

        for line in process.stdout:
            if "time=" in line:
                time_str = line.split("time=")[1].split(" ")[0]
                progress = self.calculate_progress(time_str)
                self.progress.emit(progress)

        process.wait()
        self.finished.emit(output_file)

    def calculate_progress(self, time_str):
        """Estimates progress based on the extracted time."""
        try:
            hh, mm, ss = map(float, time_str.split(":"))
            current_seconds = hh * 3600 + mm * 60 + ss
            start_seconds = sum(
                int(x) * 60 ** i for i, x in enumerate(
                    reversed(self.start_time.split(":"))
                )
            )
            end_seconds = sum(
                int(x) * 60 ** i for i, x in enumerate(
                    reversed(self.end_time.split(":"))
                )
            )
            return int(((current_seconds - start_seconds) /
                        (end_seconds - start_seconds)) * 100)
        except ValueError:
            return 0  # Default to 0 if parsing fails


class VideoCutterApp(QWidget):
    """Main UI for the FFmpeg Video Cutter with audio normalization support."""
    def __init__(self):
        super().__init__()

        self.setWindowTitle("FFmpeg Video Cutter")
        self.setGeometry(300, 200, 600, 500)
        self.setAcceptDrops(True)  # Enable drag-and-drop

        layout = QVBoxLayout()

        # File selection
        self.label_file = QLabel("Drag and drop a video file or browse:")
        layout.addWidget(self.label_file)

        self.input_file = QLineEdit()
        self.input_file.setReadOnly(True)
        layout.addWidget(self.input_file)

        self.btn_browse = QPushButton("Browse Video")
        self.btn_browse.clicked.connect(self.select_file)
        layout.addWidget(self.btn_browse)

        # Video duration display
        self.label_duration = QLabel("Duration: N/A")
        layout.addWidget(self.label_duration)

        # Audio dB level display
        self.label_audio_level = QLabel("Current Audio Level: Analyzing...")
        layout.addWidget(self.label_audio_level)

        # Start time input
        self.label_start = QLabel("Start Time (hh:mm:ss):")
        layout.addWidget(self.label_start)

        self.input_start = QLineEdit()
        layout.addWidget(self.input_start)

        # End time input
        self.label_end = QLabel("End Time (hh:mm:ss):")
        layout.addWidget(self.label_end)

        self.input_end = QLineEdit()
        layout.addWidget(self.input_end)

        # Audio Normalization options
        self.label_audio = QLabel("Audio Normalization:")
        layout.addWidget(self.label_audio)

        self.audio_options = QComboBox()
        self.audio_options.addItems(["Skip", "-1 dB", "-3 dB", "-5 dB"])
        layout.addWidget(self.audio_options)

        # Output folder selection
        self.label_output = QLabel("Output Folder:")
        layout.addWidget(self.label_output)

        self.input_output = QLineEdit()
        self.input_output.setReadOnly(True)
        layout.addWidget(self.input_output)

        self.btn_output = QPushButton("Select Output Folder")
        self.btn_output.clicked.connect(self.select_output_folder)
        layout.addWidget(self.btn_output)

        # Video preview button
        self.btn_preview = QPushButton("Preview Selected Clip")
        self.btn_preview.clicked.connect(self.preview_clip)
        layout.addWidget(self.btn_preview)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Extract button
        self.btn_extract = QPushButton("Extract Video")
        self.btn_extract.clicked.connect(self.extract_video)
        layout.addWidget(self.btn_extract)

        self.setLayout(layout)

    def select_file(self):
        """Opens a file dialog for selecting a video file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", "Video Files (*.mp4 *.mkv *.avi *.mov *.flv)"
        )
        if file_path:
            self.input_file.setText(file_path)
            self.update_video_duration(file_path)
            self.analyze_audio_level(file_path)

    def update_video_duration(self, file_path):
        """Retrieves and displays the video duration."""
        try:
            # Run ffprobe to get video metadata in JSON format
            cmd = [f'{FFMPEG_DIR}/ffprobe.exe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', file_path]
            result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

            # Parse the JSON output from ffprobe
            probe_output = json.loads(result.stdout)
            duration = float(probe_output['format']['duration'])

            # Convert duration to hh:mm:ss format
            hh, mm, ss = int(duration // 3600), int((duration % 3600) // 60), int(duration % 60)
            self.label_duration.setText(f"Duration: {hh:02}:{mm:02}:{ss:02}")
            self.input_end.setText(f"{hh:02}:{mm:02}:{ss:02}")
            self.input_start.setText("00:00:00")

        except Exception as e:
            self.label_duration.setText("Duration: Error reading")
            print(f"Error: {e}")

    def analyze_audio_level(self, file_path):
        """Analyzes the current audio dB level of the video."""
        try:
            result = subprocess.run(
                [f"{FFMPEG_DIR}/ffmpeg.exe", "-i", file_path, "-af", "volumedetect", "-f", "null", "-"],
                stderr=subprocess.PIPE,
                text=True
            )
            for line in result.stderr.split("\n"):
                if "mean_volume" in line:
                    dB_level = line.split(":")[-1].strip()
                    self.label_audio_level.setText(f"Current Audio Level: {dB_level} dB")
                    return
            self.label_audio_level.setText("Current Audio Level: Not detected")
        except Exception:
            self.label_audio_level.setText("Current Audio Level: Error")

    def preview_clip(self):
        """Previews the selected video clip."""
        file_path = self.input_file.text()
        start_time = self.input_start.text()
        end_time = self.input_end.text()

        if not file_path or not start_time or not end_time:
            QMessageBox.critical(self, "Error", "Please select a file and enter start/end times.")
            return

        # Convert start_time and end_time to seconds (useful for calculating duration)
        start_time_seconds = sum(x * int(t) for x, t in zip([3600, 60, 1], start_time.split(":")))
        end_time_seconds = sum(x * int(t) for x, t in zip([3600, 60, 1], end_time.split(":")))

        # Calculate the duration to play
        duration = end_time_seconds - start_time_seconds

        # try:
        #     command = [f"{FFMPEG_DIR}/ffplay.exe", "-i", file_path, "-ss", start_time, "-t", f'{duration}']
        #     process = subprocess.Popen(command)
        #     stdout, stderr = process.communicate()
        # except Exception as e:
        #     print(e)
        vlc_command = [
            os.path.join(VLC_PATH, 'vlc.exe'), f'file:///{file_path}',
            f'--start-time={start_time_seconds}',
            f'--stop-time={end_time_seconds}',
            '--play-and-exit'
        ]
        try:
            subprocess.Popen(vlc_command)
        except FileNotFoundError:
            QMessageBox.critical(
                self,
                'Error',
                'VLC installation failed'
            )

    def select_output_folder(self):
        """Opens a folder dialog for selecting an output folder."""
        folder_path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder_path:
            self.input_output.setText(folder_path)

    def validate_inputs(self):
        valid = True
        file_path = self.input_file.text()
        start_time = self.input_start.text()
        end_time = self.input_end.text()
        output_path = self.input_output.text()

        if not file_path or not start_time or not end_time or not output_path:
            QMessageBox.critical(self, "Error", "Please complete all fields.")
            valid = False

        if not re.match(r'^[0-9]+:[0-5][0-9]:[0-5][0-9]$', start_time):
            QMessageBox.critical(self, "Error", "Invalid Start Time Format.")
            valid = False

        if not re.match(r'^[0-9]+:[0-5][0-9]:[0-5][0-9]$', end_time):
            QMessageBox.critical(self, "Error", "Invalid End Time Format.")
            valid = False

        if not os.path.isdir(output_path):
            QMessageBox.critical(self, "Error", "Output Path doesn't exist.")
            valid = False
        return valid

    def extract_video(self):
        """Extracts a video segment based on user input."""
        file_path = self.input_file.text()
        start_time = self.input_start.text()
        end_time = self.input_end.text()
        output_path = self.input_output.text()
        audio_level = self.audio_options.currentText().split()[0]

        if not self.validate_inputs():
            return

        self.progress_bar.setValue(0)

        self.thread = VideoCutterThread(file_path, start_time, end_time, output_path, audio_level)
        self.thread.progress.connect(self.progress_bar.setValue)
        self.thread.finished.connect(self.on_extraction_complete)
        self.thread.start()

    def on_extraction_complete(self, output_file):
        QMessageBox.information(self, "Success", f"Clip saved as:\n{output_file}")
        self.progress_bar.setValue(100)


if __name__ == "__main__":
    Install_Requirements()
    app = QApplication(sys.argv)
    window = VideoCutterApp()
    window.show()
    sys.exit(app.exec())
