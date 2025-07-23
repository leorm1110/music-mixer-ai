from flask import Flask, request, jsonify, send_from_directory, session, render_template, send_file
from flask_cors import CORS
import torch
import torchaudio
import replicate
import requests
import subprocess
import numpy as np
import os
import uuid
import logging
from pathlib import Path
import io

# Funzione per convertire l'audio in WAV a 16-bit usando ffmpeg
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

# --- App Setup ---
app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.urandom(24)  # Necessary for session management
CORS(app)

# --- Model and File Configuration (v2) ---
# Aggiungo un commento per forzare l'aggiornamento del file su GitHub e risolvere l'errore di deployment.
logging.basicConfig(level=logging.INFO)
OUTPUT_FOLDER = Path('output')
OUTPUT_FOLDER.mkdir(exist_ok=True)
app.config['OUTPUT_FOLDER'] = str(OUTPUT_FOLDER)

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'audio' not in request.files:
        return jsonify({'error': 'No file sent'}), 400
    file = request.files['audio']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    session_id = str(uuid.uuid4())
    output_dir = OUTPUT_FOLDER / session_id
    output_dir.mkdir(exist_ok=True)

    original_filepath = output_dir / file.filename
    wav_filepath = output_dir / 'temp.wav'

    try:
        file.save(original_filepath)
        logging.info(f"Original file saved to: {original_filepath}")

        # Convert to WAV using ffmpeg
        logging.info(f"Converting {original_filepath} to {wav_filepath}...")
        subprocess.run([
            'ffmpeg',
            '-i', str(original_filepath),
            '-ar', '44100',  # Sample rate for demucs
            '-ac', '2',      # Stereo channels
            '-c:a', 'pcm_s16le',
            str(wav_filepath)
        ], check=True, capture_output=True)
        logging.info("Conversion to WAV successful.")

        # --- Audio Separation with Demucs ---
        logging.info("Starting audio separation with Demucs (htdemucs_ft)...")
        try:
            model = get_model('htdemucs_ft')
            model.cpu()
            model.eval()

            wav, sr = load_track(wav_filepath, model.audio_channels, model.samplerate)

            ref = wav.mean(0)
            wav = (wav - ref.mean()) / ref.std()
            
            sources = apply_model(model, wav[None], device='cpu', shifts=1, split=True, overlap=.25, progress=True)[0]
            sources = sources * ref.std() + ref.mean()

            logging.info("Separation complete. Saving tracks...")

            track_urls = []
            for i, source in enumerate(sources):
                stem = model.sources[i]
                # Sanitize stem name for filename
                safe_stem_name = stem.replace('/', '_') 
                track_filename = f"{safe_stem_name}.wav"
                track_path = session_dir / track_filename
                
                torchaudio.save(str(track_path), source, model.samplerate)
                
                # Create a URL-friendly path
                url_path = f"/output/{session_id}/{track_filename}"
                track_urls.append({'name': stem.capitalize(), 'url': url_path})

        except Exception as e:
            logging.error(f"Demucs separation failed: {e}")
            return jsonify({'error': 'Failed to process audio with Demucs.'}), 500

        return jsonify({'tracks': track_urls, 'path': session_id})

    except Exception as e:
        logging.error(f"Error during processing: {e}", exc_info=True)
        return jsonify({'error': 'An internal error occurred during processing.'}), 500
    finally:
        # Clean up temporary files
        if original_filepath.exists():
            os.remove(original_filepath)
        if wav_filepath.exists():
            os.remove(wav_filepath)

@app.route('/output/<session_id>/<filename>')
def serve_output_file(session_id, filename):
    directory = Path(app.config['OUTPUT_FOLDER']) / session_id
    return send_from_directory(directory, filename)

@app.route('/export', methods=['POST'])
def export_mix():
    data = request.get_json()
    if not data or 'tracks' not in data or 'session_path' not in data:
        return jsonify({'error': 'Dati mancanti per l\'esportazione'}), 400

    session_id = data['session_path']
    tracks_data = data['tracks']
    solo_track_name = data.get('solo_track')
    output_dir = Path(app.config['OUTPUT_FOLDER']) / session_id
    mixed_audio_path = output_dir / "final_mix.wav"

    try:
        # Filtra le tracce da includere nel mix
        if solo_track_name:
            audible_tracks = [t for t in tracks_data if t['name'] == solo_track_name and t.get('volume', 0) > 0]
        else:
            audible_tracks = [t for t in tracks_data if not t.get('mute', False) and t.get('volume', 0) > 0]

        if not audible_tracks:
            return jsonify({'error': 'Nessuna traccia udibile da esportare.'}), 400

        command = ['ffmpeg', '-y']
        filter_complex_parts = []
        stream_specifiers = ''
        input_files = []

        for i, track_info in enumerate(audible_tracks):
            # Il nome del file è il nome della traccia in minuscolo
            track_filename = f"{track_info['name'].lower()}.wav"
            track_path = output_dir / track_filename
            
            if not track_path.exists():
                logging.warning(f"File traccia non trovato: {track_path}")
                continue
            
            input_files.append(str(track_path))
            volume = track_info.get('volume', 1.0)
            filter_complex_parts.append(f"[{i}:a]volume={volume}[a{i}]")
            stream_specifiers += f"[a{i}]"

        if not stream_specifiers:
            return jsonify({'error': 'File sorgente per le tracce udibili non trovati.'}), 400

        for file_path in input_files:
            command.extend(['-i', file_path])

        filter_complex = f'{';'.join(filter_complex_parts)};{stream_specifiers}amix=inputs={len(audible_tracks)}:duration=longest[aout]'
        command.extend(['-filter_complex', filter_complex, '-map', '[aout]', str(mixed_audio_path)])

        logging.info(f"Running ffmpeg export command: {' '.join(command)}")
        subprocess.run(command, check=True, capture_output=True)

        return send_file(
            mixed_audio_path,
            as_attachment=True,
            download_name='mixed_audio.wav',
            mimetype='audio/wav'
        )

    except subprocess.CalledProcessError as e:
        logging.error(f"ffmpeg export error: {e.stderr.decode()}")
        return jsonify({'error': 'Failed to export mix.'}), 500
    except Exception as e:
        logging.error(f"Export error: {e}", exc_info=True)
        return jsonify({'error': 'An internal error occurred during export.'}), 500
    finally:
        if mixed_audio_path.exists():
            os.remove(mixed_audio_path)

if __name__ == '__main__':
    app.run(debug=True, port=5001)
