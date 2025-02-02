import sys
import subprocess
import os
import ffmpeg
import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QFileDialog,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QComboBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
import requests

# FFmpeg download URL (Windows version)
FFMPEG_URL = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-i686-static.tar.xz"
FFMPEG_DIR = "ffmpeg"
# possibly switch to github builds
# https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n7.1-latest-win64-gpl-7.1.zip

def download_ffmpeg():
    """Downloads FFmpeg if not found in the current directory."""
    if not os.path.exists(FFMPEG_DIR):
        print("FFmpeg not found. Downloading...")
        response = requests.get(FFMPEG_URL, stream=True)
        with open("ffmpeg-release-i686-static.tar.xz", "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
        
        # Extract the tar file
        import tarfile
        with tarfile.open("ffmpeg-release-i686-static.tar.xz", "r:xz") as tar:
            tar.extractall()
        
        exes = ['ffmpeg', 'ffplay', 'ffprob']

        for exe in exes:
            os.rename(f"ffmpeg-*-static/{exe}.exe", f"{exe}.exe")
        os.rmdir("ffmpeg-*-static")


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
            "ffmpeg",
            "-i", self.file_path,
            "-ss", self.start_time,
            "-to", self.end_time,
            "-c:v", "copy",
            "-c:a", "aac"
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
            probe = ffmpeg.probe(file_path)
            duration = float(probe["format"]["duration"])
            hh, mm, ss = int(duration // 3600), int((duration % 3600) // 60), int(duration % 60)
            self.label_duration.setText(f"Duration: {hh:02}:{mm:02}:{ss:02}")
        except Exception:
            self.label_duration.setText("Duration: Error reading")

    def analyze_audio_level(self, file_path):
        """Analyzes the current audio dB level of the video."""
        try:
            result = subprocess.run(
                ["ffmpeg", "-i", file_path, "-af", "volumedetect", "-f", "null", "-"],
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

        command = ["ffplay", "-i", file_path, "-ss", start_time, "-to", end_time]
        subprocess.Popen(command)

    def select_output_folder(self):
        """Opens a folder dialog for selecting an output folder."""
        folder_path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder_path:
            self.input_output.setText(folder_path)

    def extract_video(self):
        """Extracts a video segment based on user input."""
        file_path = self.input_file.text()
        start_time = self.input_start.text()
        end_time = self.input_end.text()
        output_path = self.input_output.text()
        audio_level = self.audio_options.currentText().split()[0]

        if not file_path or not start_time or not end_time or not output_path:
            QMessageBox.critical(self, "Error", "Please complete all fields.")
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
    download_ffmpeg()
    app = QApplication(sys.argv)
    window = VideoCutterApp()
    window.show()
    sys.exit(app.exec())
