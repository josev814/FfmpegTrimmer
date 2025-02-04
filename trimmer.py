import shutil
import json
import sys
import subprocess
import os
import re
import glob
import time

# third party libs
import ffmpeg
import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QWidget, QGridLayout, QPushButton, QFileDialog,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QComboBox, QTimeEdit
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
import requests
from py7zip import py7zip

APP_NAME = "FFmpeg Video Trim"
# FFmpeg download URL (Windows version)
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z"
FFMPEG_DIR = "ffmpeg"
VLC_WINDOWS_URL = 'https://download.videolan.org/pub/videolan/vlc/last/win64/vlc-3.0.20-win64.exe'
VLC_PATH = r'C:\Program Files\VideoLAN\VLC'
# possibly switch to github builds
# https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n7.1-latest-win64-gpl-7.1.zip
SUPPORTED_VIDEOS = ('.mp4', '.mkv', '.avi', '.mov', '.flv')


class InstallRequirementsThread(QThread):
    progress = pyqtSignal(str)  # Signal to send progress updates
    install_complete = pyqtSignal()  # Signal when installation is complete
    installed = pyqtSignal()
    error_occurred = pyqtSignal(str)  # Signal when an error occurs

    def __init__(self):
        super().__init__()

    def run(self):
        installed = True
        try:
            # Check and install VLC if needed
            if not self.is_vlc_installed():
                installed = False
                self.progress.emit("Installing VLC...")
                self.install_vlc()

            # Check and install FFmpeg if needed
            if not self.is_ffmpeg_installed():
                installed = False
                self.progress.emit("Installing FFmpeg...")
                self.install_ffmpeg()

            # Emit completion signal
            if installed:
                self.installed.emit()
            else:
                self.install_complete.emit()
        except Exception as e:
            # If something goes wrong, emit the error message
            self.error_occurred.emit(str(e))

    def is_vlc_installed(self):
        if os.path.isfile(os.path.join(VLC_PATH, 'vlc.exe')):
            return True
        return False

    def install_vlc(self):
        installer_path = 'vlc_installer.exe'
        if not os.path.isfile(installer_path):
            self.download_vlc(installer_path)
        subprocess.run([installer_path, '/S'], shell=True)
        os.remove(installer_path)

    def download_vlc(self, installer_path):
        self.progress.emit('Downloading VLC...')
        self.download_file(VLC_WINDOWS_URL, installer_path)

    def download_file(self, url, dest):
        response = requests.get(url, stream=True)
        with open(dest, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)

    def is_ffmpeg_installed(self):
        if os.path.isdir(FFMPEG_DIR) and os.path.isfile(os.path.join(FFMPEG_DIR, 'ffmpeg.exe')):
            return True
        return False

    def install_ffmpeg(self):
        build_file = 'ffmpeg-release-full.7z'
        if not os.path.isfile(build_file):
            self.download_file(FFMPEG_URL, build_file)

        self.progress.emit("Extracting FFmpeg...")
        self.extract_ffmpeg(build_file)

        exes = ['ffmpeg', 'ffplay', 'ffprobe']
        if not os.path.isdir(FFMPEG_DIR):
            os.mkdir(FFMPEG_DIR)
        for ffmpeg_dir in glob.glob('ffmpeg-*-full_build'):
            for entry in os.scandir(os.path.join(ffmpeg_dir, 'bin')):
                if entry.name.endswith('exe') and entry.name.replace('.exe', '') in exes and not os.path.isfile(
                        f'./{FFMPEG_DIR}/{entry.name}'):
                    os.rename(entry.path, f'./{FFMPEG_DIR}/{entry.name}')
        for entry in os.scandir('./'):
            if entry.is_dir() and entry.name.endswith('full_build'):
                shutil.rmtree(entry.path)

    def extract_ffmpeg(self, build_file):
        py7 = py7zip.Py7zip()
        if not os.path.exists(py7.binary_path):
            py7.download_binary()
            py7.setup()
        dst = './'
        cmd = [py7.binary_path, 'x', build_file, f'-bb3', f'-o{dst}']
        subprocess.run(cmd, check=False, text=False, capture_output=False)
        os.remove(build_file)


class AudioLevelAnalysisThread(QThread):
    """Thread for analyzing the audio level without blocking the UI."""
    update_audio_level = pyqtSignal(str)  # Signal to update the UI with the audio level
    update_dots = pyqtSignal(str)  # Signal to update the dots on the UI

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        """Run the FFmpeg command to analyze the audio level."""
        cmd = [
            f"{FFMPEG_DIR}/ffmpeg.exe",
            "-i", self.file_path,
            "-af", "volumedetect",
            "-f", "null", "-"
        ]
        try:
            process = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            # Loop to update the UI with dots as long as the process runs
            while True:
                line = process.stderr.readline()
                if not line:
                    break
                if "mean_volume" in line:
                    dB_level = line.split(":")[-1].strip()
                    self.update_audio_level.emit(f"{dB_level}")
                    return

                # Update the dots periodically to indicate the process is running
                self.update_dots.emit('.')

            process.wait()
        except Exception:
            self.update_audio_level.emit("Current Audio Level: Error")


class VideoCutterThread(QThread):
    """Runs FFmpeg in a separate thread to prevent UI freezing."""
    progress = pyqtSignal(int)  # Signal to update progress bar
    finished = pyqtSignal(str)  # Signal when extraction is done
    cancel_requested = pyqtSignal()

    def __init__(self, file_path, start_time, end_time, output_path, audio_level):
        super().__init__()
        self.file_path = file_path
        self.start_time = start_time
        self.end_time = end_time
        self.output_path = output_path
        self.audio_level = audio_level
        self.process = None  # Initialize process as None
        self._is_cancelled = False

    def run(self):

        command = [
            f"{FFMPEG_DIR}/ffmpeg.exe",
            '-y', # override prompt to overwrite
            "-i", self.file_path,
            "-ss", self.start_time,
            "-to", self.end_time,
            "-c:v", "copy",
            "-c:a", "aac",
        ]

        file_level = 'skip'
        if not self.audio_level == 'Skip':
            command.extend(["-af", f"loudnorm=I={self.audio_level}"])
            file_level = f'{self.audio_level}db'

        output_file = os.path.join(
            self.output_path,
            f"clip_{self.start_time.replace(':', '-')}"
            f"_{self.end_time.replace(':', '-')}"
            f"_{file_level}.mp4"
        )
        command.append(output_file)
        # print(' '.join(command))
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        for line in self.process.stdout:
            if self._is_cancelled:
                # If cancellation is requested, terminate FFmpeg
                self.process.terminate()
                self.process.wait()
                break

            if "time=" in line:
                time_str = line.split("time=")[1].split(" ")[0]
                progress = self.calculate_progress(time_str)
                self.progress.emit(progress)

        self.process.wait()
        if not self._is_cancelled:
            self.finished.emit(output_file)

    def calculate_progress(self, time_str):
        """Estimates progress based on the extracted time."""
        try:
            hh, mm, ss = map(float, time_str.split(":"))
            current_seconds = hh * 3600 + mm * 60 + ss
            input_start_seconds = sum(
                int(x) * 60 ** i for i, x in enumerate(
                    reversed(self.start_time.split(":"))
                )
            )
            start_seconds = 0
            input_end_seconds = sum(
                int(x) * 60 ** i for i, x in enumerate(
                    reversed(self.end_time.split(":"))
                )
            )
            end_seconds = input_end_seconds - input_start_seconds

            return int(((current_seconds - start_seconds) /
                        (end_seconds - start_seconds)) * 100)
        except ValueError:
            return 0  # Default to 0 if parsing fails

    def cancel(self):
        """Cancel the FFmpeg process."""
        self._is_cancelled = True
        if self.process:
            self.process.terminate()  # Terminate the FFmpeg process
            self.process.wait()  # Wait for the process to clean up
            self.finished.emit('Cancelled')


class VideoCutterApp(QWidget):
    """Main UI for the FFmpeg Video Cutter with audio normalization support."""
    def __init__(self):
        super().__init__()

        self.setWindowTitle(APP_NAME)
        self.setGeometry(300, 200, 600, 300)
        self.setAcceptDrops(True)  # Enable drag-and-drop

        layout = QGridLayout()
        layout.setVerticalSpacing(5)

        # File selection
        self.label_file = QLabel("Drag and drop a video file or browse:")
        layout.addWidget(self.label_file, 0, 0)

        self.input_file = QLineEdit()
        self.input_file.setReadOnly(True)
        layout.addWidget(self.input_file, 1, 0, 1,2)

        self.btn_browse = QPushButton("Browse Video")
        self.btn_browse.clicked.connect(self.select_file)
        layout.addWidget(self.btn_browse, 1, 2)

        # Video duration display
        self.label_duration = QLabel("Duration:")
        layout.addWidget(self.label_duration, 3, 0)
        self.duration_value = QLabel('--:--:--')
        layout.addWidget(self.duration_value, 3, 1)

        # Audio dB level display
        self.label_audio_level = QLabel("Current Audio Level:")
        layout.addWidget(self.label_audio_level, 4, 0)
        self.audio_level_value = QLabel('--')
        layout.addWidget(self.audio_level_value, 4, 1)

        self.btn_audio_level = QPushButton("Get Current Level")
        self.btn_audio_level.clicked.connect(self.analyze_audio_level)
        layout.addWidget(self.btn_audio_level, 4, 2)

        # Start time input
        self.label_start = QLabel("Start Time (hh:mm:ss):")
        layout.addWidget(self.label_start, 5, 0)

        self.input_start = QLineEdit()
        layout.addWidget(self.input_start, 5, 1)

        # End time input
        self.label_end = QLabel("End Time (hh:mm:ss):")
        layout.addWidget(self.label_end, 6, 0)

        self.input_end = QLineEdit()
        layout.addWidget(self.input_end, 6, 1)

        # Audio Normalization options
        self.label_audio = QLabel("Audio Normalization:")
        layout.addWidget(self.label_audio, 7, 0)

        self.audio_options = QComboBox()
        self.audio_options.addItems(["Skip", "-5 dB", "-10 dB", "-15 dB"])
        layout.addWidget(self.audio_options, 7, 1)

        # Output folder selection
        self.label_output = QLabel("Output Folder:")
        layout.addWidget(self.label_output, 8, 0)

        self.input_output = QLineEdit()
        self.input_output.setReadOnly(True)
        layout.addWidget(self.input_output, 8, 1)

        self.btn_output = QPushButton("Select Output Folder")
        self.btn_output.clicked.connect(self.select_output_folder)
        layout.addWidget(self.btn_output, 8, 2)

        # Video preview button
        self.btn_preview = QPushButton("Preview Selected Clip")
        self.btn_preview.clicked.connect(self.preview_clip)
        layout.addWidget(self.btn_preview, 10, 0)

        # Extract button
        self.btn_extract = QPushButton("Extract Video")
        self.btn_extract.clicked.connect(self.extract_video)
        layout.addWidget(self.btn_extract, 10, 1)

        self.btn_cancel = QPushButton("Cancel Extract")
        self.btn_cancel.clicked.connect(self.cancel_extract)
        self.btn_cancel.setEnabled(False)
        layout.addWidget(self.btn_cancel, 10, 2)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar, 11, 0, 1, 3)

        self.setLayout(layout)
        self.ensure_requirements()

    def ensure_requirements(self):
        self.msg = None
        # Start the installation of requirements when the app starts
        self.install_thread = InstallRequirementsThread()
        self.install_thread.progress.connect(self.show_install_progress)
        self.install_thread.install_complete.connect(self.on_install_complete)
        self.install_thread.installed.connect(self.on_install_not_required)
        self.install_thread.error_occurred.connect(self.on_install_error)

        # Start the installation thread
        self.install_thread.start()

    def show_install_progress(self, message):
        """Displays a progress message during installation."""
        self.show_message(message)

    def on_install_complete(self):
        """Handles actions when installation completes."""
        self.show_message("Installation complete! FFmpeg and VLC are ready to use.")

    def on_install_not_required(self):
        """Handles actions when installation completes."""
        self.install_thread.exit()

    def on_install_error(self, error_message):
        """Handles installation errors."""
        self.show_message(f"Error: {error_message}", QMessageBox.Critical)

    def show_message(self, message):
        """Show a message box with the specified message"""
        if not self.msg:
            self.msg = QMessageBox(self)
        self.msg.setText(message)
        self.msg.setWindowTitle("Installation Progress")
        self.msg.exec()

    def select_file(self):
        self.progress_bar.setValue(0)
        """Opens a file dialog for selecting a video file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", f"Video Files (*{' *'.join(SUPPORTED_VIDEOS)})"
        )
        if file_path:
            self.input_file.setText(file_path)
            self.update_video_duration(file_path)
            self.audio_level_value.setText('--')

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.progress_bar.setValue(0)
        try:
            file_url = event.mimeData().urls()[0].toLocalFile()
            if file_url and file_url.lower().endswith(SUPPORTED_VIDEOS):
                self.input_file.setText(file_url)
                self.update_video_duration(file_url)
                self.audio_level_value.setText('--')
                print(f'File Dropped: {file_url}')
            else:
                QMessageBox.critical(self, 'Invalid File', f'Only ({SUPPORTED_VIDEOS}) are accepted')
        except Exception as e:
            print(e)

    def update_video_duration(self, file_path):
        """Retrieves and displays the video duration."""
        try:
            # Run ffprobe to get video metadata in JSON format
            cmd = [
                f'{FFMPEG_DIR}/ffprobe.exe',
                '-v', 'error',
                '-show_entries',
                'format=duration',
                '-of', 'json',
                file_path
            ]
            result = subprocess.run(
                cmd,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            # Parse the JSON output from ffprobe
            probe_output = json.loads(result.stdout)
            duration = float(probe_output['format']['duration'])

            # Convert duration to hh:mm:ss format
            hh, mm, ss = int(duration // 3600), int((duration % 3600) // 60), int(duration % 60)
            self.duration_value.setText(f"{hh:02}:{mm:02}:{ss:02}")
            self.input_end.setText(f"{hh:02}:{mm:02}:{ss:02}")
            self.input_start.setText("00:00:00")

        except Exception as e:
            self.label_duration.setText("Duration: Error reading")
            print(f"Error: {e}")

    def analyze_audio_level(self):
        """Analyzes the current audio dB level of the video."""
        file_path = self.input_file.text()
        self.audio_level_value.setText("")
        self.btn_audio_level.setEnabled(False)

        # Start the thread for audio analysis
        self.audio_thread = AudioLevelAnalysisThread(file_path)
        self.audio_thread.update_audio_level.connect(self.update_audio_level_display)
        self.audio_thread.update_dots.connect(self.update_dots)
        self.audio_thread.start()

    def update_audio_level_display(self, level):
        """Update the audio level label."""
        self.audio_level_value.setText(f"{level}")
        self.btn_audio_level.setEnabled(True)

    def update_dots(self, dots):
        """Update the dots on the UI during the process."""
        current_text = self.audio_level_value.text()
        if current_text == "......":
            self.audio_level_value.setText("")
        else:
            self.audio_level_value.setText(current_text + dots)

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
        max_time = self.duration_value.text()
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

        hh, mm, ss = map(int, start_time.split(":"))
        start = hh * 3600 + mm * 60 + ss
        hh, mm, ss = map(int, end_time.split(":"))
        end = hh * 3600 + mm * 60 + ss
        hh, mm, ss = map(int, max_time.split(":"))
        max = hh * 3600 + mm * 60 + ss
        if start >= end:
            QMessageBox.critical(self, 'Error', 'The start time must be less than the end time')
            valid = False

        if end > max:
            QMessageBox.critical(self, 'Error', 'The end time can not be longer than the detected duration of the video.')
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
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.btn_cancel.setEnabled(True)
        self.btn_extract.setEnabled(False)
        self.start_runtime = time.time()
        try:
            self.thread = VideoCutterThread(file_path, start_time, end_time, output_path, audio_level)
            self.thread.progress.connect(self.progress_bar.setValue)
            self.thread.finished.connect(self.on_extraction_complete)
            self.thread.start()
        except Exception as e:
            print(e)

    def cancel_extract(self):
        """Cancels the FFmpeg process."""
        if self.thread:
            self.thread.cancel()  # Cancel the thread's process
        self.btn_cancel.setEnabled(False)  # Disable the cancel button
        self.progress_bar.setValue(0)
        self.btn_extract.setEnabled(True)

    def on_extraction_complete(self, output_file):
        self.btn_extract.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        elapsed_time = time.time() - self.start_runtime
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = int(elapsed_time % 60)

        # Format elapsed time as hh:mm:ss
        elapsed_time_str = f"{hours:02}:{minutes:02}:{seconds:02}"

        QMessageBox.information(
            self,
            "Success",
            f"Clip saved as:\n{output_file}\nElapsed Time: {elapsed_time_str}")
        self.progress_bar.setValue(100)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoCutterApp()
    window.show()
    sys.exit(app.exec())
