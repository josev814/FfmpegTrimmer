# FfmpegTrimmer

## How to Run?
1.	Run the application.
2.	Drag and drop a video file into the app OR click “Browse”.
3.	Enter start & end times (hh:mm:ss format).
4.	Choose an output folder (if needed).
5.	Click “Extract Video” → Progress bar updates, and the clip is saved.

### Supported Features:

- Audio dB level analysis to display the current volume level.
- Audio normalization options (-1 dB, -3 dB, -5 dB, or skip).
- Automatic video duration display.
- Preview feature before extraction.
- Drag-and-drop support.

## Compiling
To compile the PyQt6 video cutter into a Windows executable, follow these steps using PyInstaller:

### Step 1: Install requirements

pip install -r requirements.txt

### Step 2: Create a PyInstaller Spec File

Run the following command in the directory containing your script:

pyinstaller --onefile --windowed trimmer.py

- --onefile:
  - Bundles everything into a single executable.
- --windowed:
  - Hides the terminal window when running the app.


### Step 3: Run the Build Process

pyinstaller trimmer.spec

After completion, the executable will be inside the dist folder.