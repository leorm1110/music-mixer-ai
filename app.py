import os
import uuid
import logging
from pathlib import Path
import subprocess

from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

from demucs.api import Separator
import torch
import torchaudio

# --- App Setup ---
app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.urandom(24)
CORS(app)

logging.basicConfig(level=logging.INFO)
OUTPUT_FOLDER = Path('output')
OUTPUT_FOLDER.mkdir(exist_ok=True)
app.config['OUTPUT_FOLDER'] = str(OUTPUT_FOLDER)

# --- Helper Functions ---
def convert_to_wav(input_path, output_path):
    command = [
        "ffmpeg",
        "-i", input_path,
        "-ac", "2",
        "-ar", "44100",
        "-acodec", "pcm_s16le",
        output_path
    ]
    subprocess.run(command, check=True, capture_output=True)

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file:
        session_id = str(uuid.uuid4())
        session_dir = OUTPUT_FOLDER / session_id
        session_dir.mkdir(exist_ok=True)

        filename = secure_filename(file.filename)
        original_filepath = session_dir / filename
        file.save(original_filepath)
        logging.info(f"Original file saved to: {original_filepath}")

        wav_filepath = session_dir / 'temp.wav'
        logging.info(f"Converting {original_filepath} to {wav_filepath}...")
        try:
            convert_to_wav(original_filepath, wav_filepath)
            logging.info("Conversion to WAV successful.")
        except subprocess.CalledProcessError as e:
            logging.error(f"FFmpeg conversion failed: {e.stderr.decode()}")
            return jsonify({'error': 'Failed to convert audio file.'}), 500

        # --- Audio Separation with Demucs v4 API ---
        logging.info("Starting audio separation with Demucs v4 (htdemucs_ft)...")
        try:
            # 1. Initialize the Separator model
            # Using the 'htdemucs_ft' model which is a high-quality fine-tuned model.
            # We specify 'cpu' device as it's more reliable on free hosting tiers.
            separator = Separator(model='htdemucs_ft', device='cpu')

            # 2. Load the audio file
            wav, sr = torchaudio.load(wav_filepath)

            # 3. Separate the tracks
            # The separate_tensor method returns the original mix and a dictionary of separated tracks.
            logging.info("Applying separation model...")
            _, separated_tracks = separator.separate_tensor(wav, sr)
            logging.info("Separation complete. Saving tracks...")

            track_urls = []
            # The `separated_tracks` dict contains tensors for 'vocals', 'drums', etc.
            for stem, source in separated_tracks.items():
                track_filename = f"{stem}.wav"
                track_path = session_dir / track_filename
                
                # Save the separated track tensor to a file
                torchaudio.save(str(track_path), source, sr)
                
                # Create a URL-friendly path for the frontend
                url_path = f"/output/{session_id}/{track_filename}"
                track_urls.append({'name': stem.capitalize(), 'url': url_path})

        except Exception as e:
            logging.error(f"Demucs separation failed: {e}", exc_info=True)
            return jsonify({'error': 'Failed to process audio with Demucs.'}), 500

        return jsonify({'tracks': track_urls, 'path': session_id})

@app.route('/output/<path:session_id>/<path:filename>')
def serve_output_file(session_id, filename):
    return send_from_directory(Path(app.config['OUTPUT_FOLDER']) / session_id, filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
