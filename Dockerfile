FROM tensorflow/tensorflow:latest-gpu

COPY requirements.txt requirements.txt

RUN apt-get update \
    && apt-get install --no-install-recommends ffmpeg libsm6 libxext6 -y \
    && pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt \
    && pip cache purge \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /root/.cache/pip

COPY . . 
WORKDIR . 
CMD [ "streamlit", "run", "app_local.py", "--server.enableCORS=false", "--server.enableXsrfProtection=false","--server.enableWebsocketCompression=false" ]
