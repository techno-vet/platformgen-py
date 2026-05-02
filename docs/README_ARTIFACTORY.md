# Artifactory Widget

The Artifactory widget provides a Docker image browser and management interface for your JFrog Artifactory registry.

## Features

- **Browse repositories** — list Docker repositories in your Artifactory instance
- **Image tags** — view all tags for a selected repository
- **Pull images** — pull any image tag directly to your host Docker daemon
- **Push images** — push local images to Artifactory
- **Run with Bash** — launch a container from any image with an interactive bash shell

## Configuration

Set these in your `~/.auger/.env`:

```bash
ARTIFACTORY_URL=https://artifactory.your-org.com
ARTIFACTORY_USER=your.username
ARTIFACTORY_IDENTITY_TOKEN=your-token
DOCKER_REPO=your-docker-repo-name
```

## Usage

1. Open the Artifactory widget from the Widgets menu
2. Click **Refresh** to load repositories
3. Select a repository to browse its tags
4. Use **Pull**, **Push**, or **Run Bash** on any image

## Ask Auger

> "pull the latest airflow image from artifactory"
> "what images are available in my artifactory?"
> "run a bash shell in the latest release image"
