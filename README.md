# FfmpegTrimmer

To compile the PyQt6 video cutter into a Windows executable, follow these steps using PyInstaller:

## Step 1: Install requirements

pip install -r requirements.txt

## Step 2: Create a PyInstaller Spec File

Run the following command in the directory containing your script:

pyinstaller --onefile --windowed trimmer.py

	•	--onefile: Bundles everything into a single executable.
	•	--windowed: Hides the terminal window when running the app.


## Step 3: Run the Build Process

pyinstaller trimmer.spec

After completion, the executable will be inside the dist folder.