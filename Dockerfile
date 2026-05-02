# Auger Platform - Docker Container
# Full development and runtime environment with all dependencies

FROM ubuntu:22.04

# Build arg for tracking which git commit is baked in
ARG GIT_COMMIT=unknown
ARG BUILD_HASH=unknown
LABEL git-commit=$GIT_COMMIT
LABEL build-hash=$BUILD_HASH

# Proxy build args (passed from docker-run.sh when Zscaler is detected)
ARG http_proxy=""
ARG https_proxy=""
ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ENV http_proxy=$http_proxy
ENV https_proxy=$https_proxy
ENV HTTP_PROXY=$HTTP_PROXY
ENV HTTPS_PROXY=$HTTPS_PROXY

# Prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    # Core tools
    python3.10 \
    python3-pip \
    python3-tk \
    git \
    curl \
    wget \
    unzip \
    ca-certificates \
    gnupg \
    lsb-release \
    # X11 for GUI
    xvfb \
    x11-apps \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libxtst6 \
    libxi6 \
    # Other utilities
    vim \
    nano \
    jq \
    htop \
    net-tools \
    iputils-ping \
    # xdg-utils for URL handling (Chrome mounted from host via docker-run.sh)
    xdg-utils \
    # Chrome runtime dependencies (Chrome binary mounted from host)
    libnspr4 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Add Zscaler Root Certificate
ADD zscaler_certs/ZscalerRootCertificate-2048-SHA256.crt /usr/local/share/ca-certificates/ZscalerRootCertificate.crt
RUN chmod 644 /usr/local/share/ca-certificates/ZscalerRootCertificate.crt

# Add Amazon Root CA certificates (copied from build context — no external curl needed)
ADD zscaler_certs/AmazonRootCA1.crt /usr/local/share/ca-certificates/AmazonRootCA1.crt
ADD zscaler_certs/AmazonRootCA2.crt /usr/local/share/ca-certificates/AmazonRootCA2.crt
ADD zscaler_certs/AmazonRootCA3.crt /usr/local/share/ca-certificates/AmazonRootCA3.crt
ADD zscaler_certs/AmazonRootCA4.crt /usr/local/share/ca-certificates/AmazonRootCA4.crt
RUN chmod 644 /usr/local/share/ca-certificates/AmazonRootCA*.crt

# Update CA certificates bundle
RUN update-ca-certificates

# Configure pip and other tools to use system certificates
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt

# Install Docker CLI (for docker socket access)
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && \
    apt-get install -y docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

# Install kubectl
RUN curl -fsSLO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/

# Install GitHub CLI and Copilot extension
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && \
    apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# Install standalone Copilot CLI (recommended by GitHub)
RUN curl -fsSL https://gh.io/copilot-install | bash

# Install k9s
RUN wget -q https://github.com/derailed/k9s/releases/latest/download/k9s_Linux_amd64.tar.gz && \
    tar -xzf k9s_Linux_amd64.tar.gz -C /usr/local/bin && \
    rm k9s_Linux_amd64.tar.gz

# Install Node.js 20 LTS (required by Panner widget DataDog log downloader)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Setup Python environment
RUN python3 -m pip install --upgrade pip setuptools wheel

# Create user (non-root) BEFORE any COPY --chown=auger steps
RUN useradd -m -s /bin/bash auger && \
    mkdir -p /home/auger/.local/bin /home/auger/.auger /home/auger/.kube /home/auger/.config && \
    echo 'export PATH="/home/auger/.local/bin:$PATH"' >> /home/auger/.bashrc && \
    chmod 755 /home/auger && \
    chown -R auger:auger /home/auger

# Pre-install Panner widget npm dependencies (runs as root; chown after)
COPY --chown=auger:auger auger/ui/widgets/package.json /home/auger/auger-platform/auger/ui/widgets/package.json
RUN cd /home/auger/auger-platform/auger/ui/widgets && \
    npm install --strict-ssl=false && \
    chown -R auger:auger /home/auger/auger-platform/

# Copy full application code
WORKDIR /home/auger
COPY --chown=auger:auger . /home/auger/auger-platform
WORKDIR /home/auger/auger-platform

# System-wide pip install — must run BEFORE mv/symlink (auger/ dir must exist).
# Packages land in /usr/local/lib/ (shared by all users, no per-user copy needed).
RUN pip install -e /home/auger/auger-platform/

# ── Live-code symlink ──────────────────────────────────────────────────────
# Rename the baked auger/ dir and create a symlink that defaults to auger_baked.
# In prod (auger-launch.sh) the symlink works immediately — no runtime fix needed.
# In dev (docker-run.sh) entrypoint.sh repoints it to ~/repos/...auger for hot-reload.
RUN mv auger auger_baked && \
    ln -sfn /home/auger/auger-platform/auger_baked auger

# Make app dir world-readable/executable so any container user (host uid) can access it.
# Also world-writable on the top-level dir so entrypoint.sh (running as host user)
# can replace the dangling auger→repos symlink with auger→auger_baked fallback.
RUN chmod -R o+rX /home/auger/auger-platform/ && \
    chmod o+rwX /home/auger/auger-platform/ && \
    chmod o+rX /home/auger/

# auger CLI is now at /usr/local/bin/auger — on PATH for all users.
ENV PATH="/usr/local/bin:$PATH"

# Bake entrypoint into the image (needs root ownership so root can exec it)
COPY scripts/entrypoint.sh /usr/local/bin/auger-entrypoint.sh
RUN chmod +x /usr/local/bin/auger-entrypoint.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD auger --version || exit 1

# Entrypoint: auto-initialize auger config if needed
ENTRYPOINT ["/usr/local/bin/auger-entrypoint.sh"]

# Default command
CMD ["/bin/bash"]
