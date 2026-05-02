import os

# True when running inside a Docker container (/.dockerenv is created by Docker)
IN_DOCKER = os.path.exists('/.dockerenv')
