FROM mambaorg/micromamba:2.3.3

USER root

ENV DEBIAN_FRONTEND=noninteractive
ENV MAMBA_DOCKERFILE_ACTIVATE=1
ENV TRAME_CLIENT_TYPE=vue2
ENV PV_VENV=1

# ParaView offscreen rendering and Playwright dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgl1 \
    libxrender1 \
    libxcursor1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libxft2 \
    libxinerama1 \
    libgomp1 \
    libosmesa6 \
    libosmesa6-dev \
    # Playwright dependencies
    libnss3 \
    libnspr4 \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libexpat1 \
    libgbm1 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=$MAMBA_USER:$MAMBA_USER setup/environment-docker.yml /tmp/environment-docker.yml
COPY --chown=$MAMBA_USER:$MAMBA_USER setup/requirements.txt /tmp/requirements.txt
COPY --chown=$MAMBA_USER:$MAMBA_USER setup/requirements-dev.txt /tmp/requirements-dev.txt

USER $MAMBA_USER

RUN micromamba create -y -n coral -f /tmp/environment-docker.yml && \
    micromamba run -n coral python -m pip install --no-cache-dir \
    -r /tmp/requirements.txt \
    -r /tmp/requirements-dev.txt && \
    micromamba run -n coral playwright install chromium && \
    micromamba clean --all --yes

# Verify ParaView availability
RUN micromamba run -n coral python -c "import paraview.simple; print('ParaView version:', paraview.simple.GetParaViewVersion())"

WORKDIR /deploy
COPY --chown=$MAMBA_USER:$MAMBA_USER . /deploy

EXPOSE 8080

# Paths here must stay absolute. Apptainer/Singularity ignore the image WORKDIR and
# start in the host's current directory, where "app.py" and the "./data" default for
# --data-directory would not resolve.
CMD ["micromamba", "run", "-n", "coral", "python", "/deploy/app.py", "--server", "--host", "0.0.0.0", "--port", "8080", "--data-directory", "/deploy/data"]
