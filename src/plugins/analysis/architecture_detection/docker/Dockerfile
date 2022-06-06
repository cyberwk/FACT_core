FROM ubuntu:jammy
RUN apt update && apt install -y device-tree-compiler && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/usr/bin/dtc"]
