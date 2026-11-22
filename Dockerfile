# Build from this folder: docker build -t my-bot .
# The match runs it with no network, a read-only root (writable /tmp), 1 CPU, 512 MB, and the map at /arena.
FROM python:3.13-slim
WORKDIR /bot
COPY mechfight.py t800.py t8core.py t8world.py ./
COPY mechfight-kit/arena ./mechfight-kit/arena
COPY LICENSE LICENSE-giddygiddyboy ./
# Precompute t800's map grids from the kit's copy of the map (about 2 s). At runtime the cache is used
# only when its hash matches the mounted /arena; otherwise the bot rebuilds the grids itself.
RUN python3 t8world.py /bot/mechfight-kit/arena /bot/t8cache.pkl \
    && python3 -m compileall -q /bot
ENTRYPOINT ["python3", "-u", "/bot/t800.py"]
