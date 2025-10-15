FROM kitware/trame:uv

ENV TRAME_PYTHON=3.13
ENV TRAME_CLIENT_TYPE=vue2

# Install X11 libraries and OSMesa required by VTK
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libxrender1 \
    libxcursor1 \
    libxft2 \
    libxinerama1 \
    libgomp1 \
    libosmesa6 \
    libosmesa6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=trame-user:trame-user . /deploy

RUN /opt/trame/entrypoint.sh build
