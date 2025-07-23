# 1. Usa un'immagine ufficiale Python 3.11 come base
FROM python:3.11-slim

# 2. Imposta la cartella di lavoro all'interno del container
WORKDIR /app

# 3. Aggiorna il package manager e installa ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# 4. Copia il file delle dipendenze e installale
# Questo passaggio viene eseguito separatamente per sfruttare la cache di Docker
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 5. Copia tutto il resto del codice del progetto nella cartella di lavoro
COPY . .

# 6. Esponi la porta su cui Gunicorn ascolterà
# Render si aspetta la porta 10000 per i servizi Docker
EXPOSE 10000

# 7. Definisci il comando per avviare l'applicazione
# Usiamo --bind per dire a Gunicorn di ascoltare su tutte le interfacce sulla porta 10000
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--timeout", "600", "app:app"]
