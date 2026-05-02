#!/bin/bash
set -euo pipefail

STATE_DIR="${AUGER_HOME:-$HOME/.platformgen}"
SOURCE_DIR="${AUGER_MIGRATION_SOURCE:-$HOME/.auger}"

mkdir -p "$STATE_DIR"

if [ -d "$SOURCE_DIR" ]; then
    rsync -a --ignore-existing \
        --exclude 'venv' \
        --exclude '*.pid' \
        --exclude '*.sock' \
        --exclude 'daemon.log' \
        --exclude 'tray.log' \
        --exclude 'startup-progress.log' \
        --exclude 'icons' \
        --exclude '.copilot.lock' \
        --exclude '.session_id' \
        --exclude '.session_snapshot.json' \
        --exclude 'chat_history.jsonl' \
        --exclude 'logs/chat_history' \
        "$SOURCE_DIR/" "$STATE_DIR/"

    mkdir -p "$STATE_DIR/logs"

    for name in .session_id .session_snapshot.json chat_history.jsonl .copilot.lock; do
        if [ -e "$SOURCE_DIR/$name" ] || [ -L "$SOURCE_DIR/$name" ]; then
            rm -rf "$STATE_DIR/$name"
            ln -s "$SOURCE_DIR/$name" "$STATE_DIR/$name"
        fi
    done

    if [ -d "$SOURCE_DIR/logs/chat_history" ]; then
        rm -rf "$STATE_DIR/logs/chat_history"
        ln -s "$SOURCE_DIR/logs/chat_history" "$STATE_DIR/logs/chat_history"
    fi
fi
