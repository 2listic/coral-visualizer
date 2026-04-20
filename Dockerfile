FROM mambaorg/micromamba:2.3.3

USER root

ENV DEBIAN_FRONTEND=noninteractive
ENV MAMBA_DOCKERFILE_ACTIVATE=1
ENV TRAME_CLIENT_TYPE=vue2
ENV PV_VENV=1

# ParaView offscreen rendering still needs a minimal Mesa/X11 userspace.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgl1 \
    libxrender1 \
    libxcursor1 \
    libxft2 \
    libxinerama1 \
    libgomp1 \
    libosmesa6 \
    libosmesa6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=$MAMBA_USER:$MAMBA_USER setup/environment-docker.yml /tmp/environment-docker.yml

USER $MAMBA_USER

RUN micromamba create -y -n coral -f /tmp/environment-docker.yml && \
    micromamba run -n coral python -m pip install --no-cache-dir \
    trame \
    trame-vtk \
    trame-vuetify && \
    micromamba clean --all --yes

WORKDIR /deploy
COPY --chown=$MAMBA_USER:$MAMBA_USER . /deploy

EXPOSE 8080

CMD ["micromamba", "run", "-n", "coral", "python", "app.py", "--server", "--backend", "paraview", "--host", "0.0.0.0", "--port", "8080"]
